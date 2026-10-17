// 把一个会话拖到另一个会话上（21 设计）。
//
// 落下之后只做一件事：**往当前会话里注一段话**，告诉它旁边那个是谁、怎么跟它说话。
// 通信能力本来就有——`roami session send <会话> <消息>` 走 SendPromptSubmit，对面 pane 里
// 出现这行并自动回车。缺的只是 Agent 不知道有这条命令、也不知道对面是谁。
//
// 这里全是纯函数：接不接得住、那段话长什么样。文案是纯函数，喂固定输入断言就够，
// 不必开浏览器看。

/** 拖拽载荷。自定义 MIME，别用 text/plain——那条会被文件拖放接走（见 isPathDrag） */
export const SESSION_MIME = 'application/x-tt-session'

export type SessionDrag = {
  /** 会话名（= tmux 会话名 = id）。命令里用它，不用展示名 */
  id: string
  label: string
  project?: string
  dir?: string
  agent?: string
  /** 机器 id；单机为空。跨机不给落点 */
  node?: string
}

export type DropTarget = {
  id: string
  node?: string
  /** 这个会话里有没有 Agent 在跑。没有就不给落点，见 canDrop */
  hasAgent?: boolean
}

/** `why` 只在 ok=false 时有意义 */
export type Verdict = { ok: boolean; why?: 'self' | 'cross' | 'noagent' }

/**
 * 这次拖拽该不该接。
 *
 * 两处必须拦：
 *
 * **跨机** —— `roami session send` 走的是本机 tmux，两个会话在不同机器上时它找不到对方，
 * 而 Agent 会拿到一句「会话不存在」然后开始瞎猜。明确拒绝好过让它撞一堵看不见的墙。
 *
 * **目标不是 Agent** —— 这条是真机上撞出来的，比想象的严重。投递是「粘一段文本 +
 * 按回车」：落进 Agent 的输入框，整段是**一条消息**；落进普通 shell，**每一行都被
 * 当成命令执行**——包括介绍词里那两行示例命令，于是它真的替你发了一条消息出去。
 * 所以没有 Agent 在跑的会话不给落点。
 */
export function canDrop(src: SessionDrag | null, target: DropTarget): Verdict {
  if (!src?.id || src.id === target.id) return { ok: false, why: 'self' }
  if ((src.node || '') !== (target.node || '')) return { ok: false, why: 'cross' }
  if (target.hasAgent === false) return { ok: false, why: 'noagent' }
  return { ok: true }
}

/** 从 dataTransfer 里读载荷；不是会话拖拽就返回 null */
export function readDrag(dt: DataTransfer | null): SessionDrag | null {
  const raw = dt?.getData(SESSION_MIME)
  if (!raw) return null
  try {
    const v = JSON.parse(raw)
    return v && typeof v.id === 'string' && v.id ? (v as SessionDrag) : null
  } catch { return null }
}

/**
 * 介绍词的开头标记。**注入端与渲染端共用同一个常量**——对话页靠它把这段话认出来，
 * 渲染成一条通知而不是「你说的话」。改文案时两边不会漂开。
 *
 * 中英两份文案里它都是字面量（见 pair.intro.head），所以拿它当判据是稳的。
 */
export const ROAM_NOTICE_PREFIX = '[Roami] '
/**
 * 改名前注入的那些还躺在转录里（标记是 `[Roam] `）。翻回去看的时候，
 * 它们照样该折叠成一条通知，而不是突然变回一段没头没尾的裸文本。
 */
export const LEGACY_NOTICE_PREFIXES = ['[Roam] ']

/** 这条文本是不是 Roami 的注入；返回命中的那个前缀（好把它从正文里剥掉） */
export function noticePrefixOf(text: string | undefined): string | null {
  for (const p of [ROAM_NOTICE_PREFIX, ...LEGACY_NOTICE_PREFIXES]) {
    if (text?.startsWith(p)) return p
  }
  return null
}

type T = (key: string, vars?: Record<string, unknown>) => string

/**
 * 注进当前会话的那段话。**本文件唯一真正的设计物**，所以每一行都有理由：
 *
 * - 展示名 + 项目 + Agent 种类：人读的那半，Agent 也靠它判断这活该不该找它
 * - 工作目录：缺了它，第一句话多半要花在问路上
 * - **会话 id 而不是展示名**：Resolve 认展示名，但展示名可以重复（同名取排序第一个），
 *   命令里用 id 才不会发错人
 * - **自己的会话名**：否则对面收到消息没有回信地址，只能干瞪眼
 * - 「和人敲进去没区别」：这条通道唯一反直觉的性质——不是发到收件箱，是直接替对方
 *   按下回车。知道了它才会斟酌第一句怎么写
 * - **对面是不是 Agent**：没有 Agent 在跑的会话，收到的每一行都会被 shell 当命令执行。
 *   这条是真用起来才发现的：Roam 告诉我「可以跟它说话」，而那头跑的是 bash
 */
export function buildIntro(src: SessionDrag, selfId: string, t: T): string {
  const who = [src.project, src.label || src.id].filter(Boolean).join(' · ')
  const kind = src.agent ? `（${src.agent}）` : ''
  // 对面没有 Agent 在跑 = 那是个普通 shell，发过去的**是一条命令**，会被直接执行。
  // 不拦（给 shell 发命令本来就是 roami session send 的正当用法），但必须说清楚——
  // 否则收到介绍的那一方会照着写一句人话过去，然后在那头变成 command not found。
  const peerNote = src.agent ? 'pair.intro.note' : 'pair.intro.noteShell'
  const lines = [
    t('pair.intro.head'),
    '',
    '  ' + t('pair.intro.who', { who: who + kind }),
  ]
  if (src.dir) lines.push('  ' + t('pair.intro.dir', { dir: src.dir }))
  lines.push(
    '  ' + t('pair.intro.id', { id: src.id }),
    '',
    '  ' + t('pair.intro.sendHead'),
    `    roami session send ${src.id} "…"`,
    '',
    '  ' + t('pair.intro.replyHead'),
    `    roami session send ${selfId} "…"`,
    '',
    '  ' + t(peerNote),
  )
  return lines.join('\n')
}
