import { describe, expect, it } from 'vitest'
import { SESSION_MIME, buildIntro, canDrop, readDrag, type SessionDrag, noticePrefixOf } from './session-drop'

const src: SessionDrag = {
  id: '2026-0824-1501-006h',
  label: 'fix-missing-search',
  project: 'XiaoHui',
  dir: '/home/ai/codes/ybz/xh/XiaoHui',
  agent: 'codex',
}

// 真 t()：把 {x} 换掉就行，这里只关心拼出来的形状
const t = (k: string, v?: Record<string, unknown>) => {
  const table: Record<string, string> = {
    'pair.intro.head': '你旁边还有一个会话，可以直接跟它说话。',
    'pair.intro.who': '它是谁：{who}',
    'pair.intro.dir': '工作目录：{dir}',
    'pair.intro.id': '会话名：{id}',
    'pair.intro.sendHead': '给它发消息：',
    'pair.intro.replyHead': '想让它回你，就在消息里带上你自己的会话名：',
    'pair.intro.note': '它收到的是一行文字并自动回车，和人敲进去的没区别。',
  }
  return (table[k] || k).replace(/\{(\w+)\}/g, (_, n) => String(v?.[n] ?? ''))
}

describe('接不接得住', () => {
  it('正常情况接得住', () => {
    expect(canDrop(src, { id: 'other' })).toEqual({ ok: true })
  })
  it('拖自己身上不接', () => {
    expect(canDrop(src, { id: src.id })).toEqual({ ok: false, why: 'self' })
  })
  it('空载荷不接', () => {
    expect(canDrop(null, { id: 'x' }).ok).toBe(false)
  })
  it('目标里没有 Agent 在跑就不接 —— 真机上撞出来的', () => {
    // 投递是「粘一段文本 + 按回车」。落进 Agent 的输入框，整段是一条消息；
    // 落进普通 shell，**每一行都被当成命令执行**——包括介绍词里那两行示例命令，
    // 于是它真的替你发了一条消息出去。
    expect(canDrop(src, { id: 'x', hasAgent: false })).toEqual({ ok: false, why: 'noagent' })
    expect(canDrop(src, { id: 'x', hasAgent: true }).ok).toBe(true)
  })
  it('没说有没有 Agent 时不拦 —— 判定不了就别假装判定得了', () => {
    expect(canDrop(src, { id: 'x' }).ok).toBe(true)
  })
  it('跨机不接 —— roami session send 走本机 tmux，过不去', () => {
    // 让它撞一堵看不见的墙，Agent 只会拿到「会话不存在」然后开始瞎猜
    expect(canDrop({ ...src, node: 'jetson' }, { id: 'x', node: '' }))
      .toEqual({ ok: false, why: 'cross' })
  })
  it('单机两边都没有 node，算同机', () => {
    expect(canDrop({ ...src, node: undefined }, { id: 'x', node: undefined }).ok).toBe(true)
  })
})

describe('读载荷', () => {
  const dt = (type: string, data: string) =>
    ({ getData: (k: string) => (k === type ? data : '') }) as unknown as DataTransfer

  it('认自己的 MIME', () => {
    expect(readDrag(dt(SESSION_MIME, JSON.stringify(src)))?.id).toBe(src.id)
  })
  it('不认 text/plain —— 那条归文件拖放', () => {
    expect(readDrag(dt('text/plain', '/tmp/a.txt'))).toBeNull()
  })
  it('坏 JSON 不炸', () => {
    expect(readDrag(dt(SESSION_MIME, '{oops'))).toBeNull()
  })
  it('没有 id 的载荷不算数', () => {
    expect(readDrag(dt(SESSION_MIME, '{"label":"x"}'))).toBeNull()
  })
})

describe('注进去的那段话', () => {
  const intro = buildIntro(src, '2026-0823-1043-0001', t)

  it('命令里用会话 id，不用展示名', () => {
    // Resolve 认展示名，但展示名可以重复（同名取排序第一个）——用 id 才不会发错人
    expect(intro).toContain('roami session send 2026-0824-1501-006h "…"')
    expect(intro).not.toContain('roami session send fix-missing-search')
  })

  it('带上自己的会话名当回信地址', () => {
    // 少了这行，对面收到消息只能干瞪眼
    expect(intro).toContain('roami session send 2026-0823-1043-0001 "…"')
  })

  it('身份那行带项目、展示名和 Agent 种类', () => {
    expect(intro).toContain('XiaoHui · fix-missing-search（codex）')
  })

  it('带工作目录 —— 缺了它第一句话要花在问路上', () => {
    expect(intro).toContain('/home/ai/codes/ybz/xh/XiaoHui')
  })

  it('说清这条通道是「直接替对方按回车」', () => {
    expect(intro).toContain('和人敲进去的没区别')
  })

  it('没有工作目录时那一行整行不出现，不留空占位', () => {
    const bare = buildIntro({ id: 'a', label: 'A' }, 'self', t)
    expect(bare).not.toContain('工作目录')
    expect(bare).toContain('roami session send a "…"')
  })

  it('没有 Agent 种类时不留空括号', () => {
    expect(buildIntro({ id: 'a', label: 'A' }, 'self', t)).not.toContain('（）')
  })

  it('是多行的 —— 投递走 paste-buffer，多行没问题', () => {
    expect(intro.split('\n').length).toBeGreaterThan(8)
  })
})

describe('对面不是 Agent 的时候', () => {
  it('说清楚发过去的会被当命令执行，而不是照抄「和人敲进去没区别」', () => {
    // 真用起来才发现的：Roam 告诉我「可以跟它说话」，而那头跑的是 bash——
    // 照着介绍写一句人话过去，在那头就是 command not found
    const shell = buildIntro({ id: 'a', label: 'A' }, 'self', (k) =>
      k === 'pair.intro.noteShell' ? '那边是个普通 shell，每一行都会被当成命令执行' : k)
    expect(shell).toContain('普通 shell')
  })
  it('对面是 Agent 时用原来那句', () => {
    const agent = buildIntro({ id: 'a', label: 'A', agent: 'claude' }, 'self', (k) =>
      k === 'pair.intro.note' ? '和人敲进去的没区别' : k)
    expect(agent).toContain('和人敲进去的没区别')
    expect(agent).not.toContain('noteShell')
  })
})

describe('noticePrefixOf', () => {
  it('认新标记，也认改名前的那批——历史注入还躺在转录里', () => {
    expect(noticePrefixOf('[Roami] 你旁边还有一个会话')).toBe('[Roami] ')
    expect(noticePrefixOf('[Roam] 你旁边还有一个会话')).toBe('[Roam] ')
    expect(noticePrefixOf('普通的一句话')).toBeNull()
    expect(noticePrefixOf(undefined)).toBeNull()
  })
})
