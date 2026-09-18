import { describe, expect, it } from 'vitest'
import {
  bulkPreview, counts, filterRows, fmtIdle, idleIsLong, moveRule, normalizeRules,
  nudgedRecently, quietSec, rowState, sortRows, type KaGuard, type KaRow, type KaRule,
} from './keepalive-view'

const NOW = 1_800_000_000

function guard(p: Partial<KaGuard> = {}): KaGuard {
  return {
    session: 's', label: 'x', enabled: true, effPrompt: '继续',
    effIdleMin: 10, effEveryMin: 30, sends: 0, lastSent: 0, quietSince: 0,
    streak: 0, maxQuiet: 3, stoppedAt: 0, ...p,
  }
}
function row(p: Partial<KaRow> = {}): KaRow {
  return { session: '2026-0918-1000-0001', label: '会话', agent: 'claude', dir: '~/x', attached: false, idleSec: 0, created: 0, ...p }
}

describe('一行处在哪一档', () => {
  it('没记过 = 未守护', () => expect(rowState(row())).toBe('off'))
  it('开着 = 守护中', () => expect(rowState(row({ guard: guard() }))).toBe('guarded'))
  it('关着且停过手 = 已停手（全表唯一的红）', () => {
    expect(rowState(row({ guard: guard({ enabled: false, stoppedAt: NOW - 60 }) }))).toBe('stopped')
  })
  it('自己手动关的不算「已停手」——那是正常状态，不该染红', () => {
    expect(rowState(row({ guard: guard({ enabled: false, stoppedAt: 0 }) }))).toBe('off')
  })
})

describe('「安静了」显示哪个数', () => {
  it('守护中的用 quietSince —— 那才是阈值真正比对的数', () => {
    const r = row({ idleSec: 9999, guard: guard({ quietSince: NOW - 120 }) })
    expect(quietSec(r, NOW)).toBe(120)
  })
  it('没守护的退回 tmux 活动时间（没有指纹可比）', () => {
    expect(quietSec(row({ idleSec: 300 }), NOW)).toBe(300)
  })
  it('停手的那行也用 tmux 时间：它已经不在巡检里了，quietSince 是老黄历', () => {
    const r = row({ idleSec: 400, guard: guard({ enabled: false, stoppedAt: NOW - 10, quietSince: NOW - 5 }) })
    expect(quietSec(r, NOW)).toBe(400)
  })
})

describe('格式与阈值', () => {
  it('短到能纵向对齐', () => {
    // 刚打开守护的那一行确实「安静了 0 秒」，那是真数字；破折号留给「没有这个数」
    expect(fmtIdle(0)).toBe('0s')
    expect(fmtIdle(NaN)).toBe('—')
    expect(fmtIdle(-1)).toBe('—')
    expect(fmtIdle(45)).toBe('45s')
    expect(fmtIdle(120)).toBe('2m')
    expect(fmtIdle(3600 * 6)).toBe('6h')
    expect(fmtIdle(86400 * 3)).toBe('3d')
  })
  it('超阈值才转暖色；守护行按它自己的阈值算', () => {
    expect(idleIsLong(row({ idleSec: 9 * 60 }), NOW, 10)).toBe(false)
    expect(idleIsLong(row({ idleSec: 11 * 60 }), NOW, 10)).toBe(true)
    // 这条守护自己说了 2 分钟就算停住
    const r = row({ guard: guard({ effIdleMin: 2, quietSince: NOW - 3 * 60 }) })
    expect(idleIsLong(r, NOW, 60)).toBe(true)
  })
  it('「刚刚催过」只亮 5 分钟', () => {
    expect(nudgedRecently(guard({ lastSent: NOW - 60 }), NOW)).toBe(true)
    expect(nudgedRecently(guard({ lastSent: NOW - 400 }), NOW)).toBe(false)
    expect(nudgedRecently(guard({ lastSent: 0 }), NOW)).toBe(false)
    expect(nudgedRecently(undefined, NOW)).toBe(false)
  })
})

describe('排序：不是按名字，是按「该管谁」', () => {
  const rows = [
    row({ session: 'a', label: '未守护的 shell', agent: '', idleSec: 99999 }),
    row({ session: 'b', label: '守护中·很久没动', guard: guard({ quietSince: NOW - 3600 }) }),
    row({ session: 'c', label: '未守护的 Agent', agent: 'codex', idleSec: 60 }),
    row({ session: 'd', label: '已停手', idleSec: 10, guard: guard({ enabled: false, stoppedAt: NOW - 5 }) }),
    row({ session: 'e', label: '守护中·刚动过', guard: guard({ quietSince: NOW - 60 }) }),
  ]
  it('出事的置顶，其次守护中，最后未守护', () => {
    expect(sortRows(rows, NOW).map((r) => r.session)).toEqual(['d', 'b', 'e', 'c', 'a'])
  })
  it('未守护那一档里 Agent 在前，哪怕 shell 安静得更久', () => {
    const only = sortRows([rows[0], rows[2]], NOW).map((r) => r.session)
    expect(only).toEqual(['c', 'a'])
  })
  it('不改原数组', () => {
    const src = [...rows]
    sortRows(rows, NOW)
    expect(rows).toEqual(src)
  })
  it('同数据永远排成同一个样子', () => {
    const a = sortRows(rows, NOW).map((r) => r.session)
    const b = sortRows([...rows].reverse(), NOW).map((r) => r.session)
    expect(a).toEqual(b)
  })
})

describe('过滤', () => {
  const rows = [
    row({ session: 'a', label: 'ttmux 优化', dir: '~/codes/ttmux', guard: guard() }),
    row({ session: 'b', label: '随手开的', dir: '~', agent: '' }),
    row({ session: 'c', label: '小慧优化', dir: '~/codes/xh', agent: 'codex' }),
  ]
  it('三档各自的口径', () => {
    expect(filterRows(rows, 'guarded', '').map((r) => r.session)).toEqual(['a'])
    expect(filterRows(rows, 'agent', '').map((r) => r.session)).toEqual(['a', 'c'])
    expect(filterRows(rows, 'all', '').length).toBe(3)
  })
  it('搜名字也搜目录：名字重名是常态，目录才认得出人', () => {
    expect(filterRows(rows, 'all', 'codes/xh').map((r) => r.session)).toEqual(['c'])
    expect(filterRows(rows, 'all', '优化').length).toBe(2)
  })
  it('计数给在分段上——没有计数的筛选器，点进去才知道是空的', () => {
    expect(counts(rows)).toEqual({ all: 3, guarded: 1, agent: 2 })
  })
})

describe('「全部守护」先说清会动几行', () => {
  const rows = [
    row({ session: 'a', guard: guard() }),          // 已经守着
    row({ session: 'b', agent: 'codex' }),          // 会被开
    row({ session: 'c', agent: '' }),               // 非 Agent
    row({ session: 'd', guard: guard({ enabled: false, stoppedAt: 1 }) }), // 停手的，也会被重开
  ]
  it('默认只挑 Agent：往裸 shell 打字换来的是 command not found', () => {
    expect(bulkPreview(rows, true)).toEqual({ willGuard: 2, skipped: 1 })
  })
  it('显式要连 shell 一起守', () => {
    expect(bulkPreview(rows, false)).toEqual({ willGuard: 3, skipped: 0 })
  })
})

describe('规则表：兜底那条钉死在最后', () => {
  const r = (p: Partial<KaRule>): KaRule => ({ match: '', atNth: 0, prompt: 'p', enabled: true, fallback: false, ...p })
  it('整表提交前把兜底摆回最后，且只留一条', () => {
    const out = normalizeRules([
      r({ fallback: true, prompt: '兜底' }),
      r({ match: 'x', prompt: '断了' }),
    ])
    expect(out.map((x) => x.prompt)).toEqual(['断了', '兜底'])
    expect(out.filter((x) => x.fallback).length).toBe(1)
  })
  it('既不匹配屏幕也不挂次数的规则等于没有，丢掉', () => {
    const out = normalizeRules([r({ match: '  ', atNth: 0, prompt: '说不上话' }), r({ fallback: true, prompt: '兜底' })])
    expect(out.map((x) => x.prompt)).toEqual(['兜底'])
  })
  it('兜底条永远是开着的：关了就等于「有时候一句话都不说」', () => {
    const out = normalizeRules([r({ fallback: true, enabled: false, prompt: '兜底' })])
    expect(out[out.length - 1].enabled).toBe(true)
  })
  it('拖不动兜底条，也拖不到它后面去', () => {
    const rules = [r({ match: 'a', prompt: 'A' }), r({ match: 'b', prompt: 'B' }), r({ fallback: true, prompt: 'F' })]
    expect(moveRule(rules, 0, 1).map((x) => x.prompt)).toEqual(['B', 'A', 'F'])
    expect(moveRule(rules, 2, 0)).toBe(rules)   // 拖兜底
    expect(moveRule(rules, 0, 2)).toBe(rules)   // 把普通规则拖到兜底之后
    expect(moveRule(rules, 0, 9)).toBe(rules)   // 越界
  })
})
