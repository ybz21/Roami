// 输入行「+」面板的内容：哪几行、每行右端那截**当前值**是什么。
//
// 这一层单独抽出来，是因为面板的价值全在「值」上：一条写着「切换权限模式」的菜单项
// 是盲的——点下去会变成什么、现在又是哪一档，都得回终端看。带上当前模式、当前模型、
// 当前上下文占用之后，它才是「更多设置」，而不是三个说不清后果的按钮。
//
// 渲染（图标、文案、点击）留在 ComposerPlus.tsx：这里只回答「显示什么」。
import { CTX_FULL, CTX_TIGHT, MODE_COLOR, modeKey, type AgentStatus } from './status'

/**
 * 从 TUI 页脚那枚模式片里读**当前**权限档。
 *
 * 转录里的 permissionMode 挂在消息行上，一条不发就不更新——按下 Shift+Tab 之后
 * 它要等到下一轮才变。而「我刚按完，现在到底是哪一档」正是那一秒最想知道的事，
 * 所以这里改从终端画面读（/sessions/:name/capture 本来就在轮询实时回显）。
 *
 * 认两种锚：那句 `(shift+tab to cycle)` 提示（Codex 的片、Claude 多数档都带），
 * 以及 Claude 画在片最左的 `⏸ / ⏵⏵`——它的「每步都问」那一档偏偏不带提示。
 * 光看「plan mode」四个字不行：Claude 自己写的一句「切到 plan mode 再看」
 * 也会被当成当前档。
 *
 * **不能只看最后几行**：Codex 把整块界面画在备用屏上半部，抓下来的末尾是十几行空白，
 * 按行数截窗口会把页脚整条截掉（这一条正是它第一版不生效的原因）。取最后一次匹配即可。
 */
export function modeFromPane(text: string): string | undefined {
  let hit: string | undefined
  for (const line of String(text).replace(/\r/g, '').split('\n')) {
    if (!/shift[+-]tab to cycle/i.test(line) && !/[⏸⏵]/.test(line)) continue
    const s = line.toLowerCase()
    if (/bypass(ing)? permissions/.test(s)) hit = 'bypassPermissions'
    else if (/plan mode/.test(s)) hit = 'plan'
    else if (/accept edits/.test(s)) hit = 'acceptEdits'
    else if (/auto mode/.test(s)) hit = 'auto'
    else if (/manual mode/.test(s)) hit = 'manual'
  }
  return hit
}

/**
 * 画面里的当前档，按端归一。
 *
 * Codex 的**默认档不画那枚片**——读到了画面、上面没有片，那就是默认档本身，
 * 而不是「没读到」。Claude 每一档都画，读不出就是真读不出（页脚正在重画），
 * 这时候宁可交回转录那份，也不要猜。
 */
export function paneMode(text: string, agent?: 'claude' | 'codex' | 'opencode'): string | undefined {
  if (!String(text).trim()) return undefined
  return modeFromPane(text) || (agent === 'codex' ? 'default' : undefined)
}

/** Codex 长跑目标的状态：页脚会写 `Goal paused (/goal resume)` 这类提示 */
export type GoalState = 'achieved' | 'paused' | 'stalled' | 'budget'

export function goalFromPane(text: string): GoalState | undefined {
  const s = String(text).toLowerCase()
  if (/goal achieved/.test(s)) return 'achieved'
  if (/goal stalled/.test(s)) return 'stalled'
  if (/goal paused/.test(s)) return 'paused'
  if (/goal (budget reached|hit usage limits)/.test(s)) return 'budget'
  return undefined
}

/**
 * 这个端能选哪几档权限。
 *
 * 顺序不照抄 CLI 的轮换顺序（Claude 实测是 每步都问 → 自动接受编辑 → 计划 → 自动，
 * 谁也记不住），而是按**它能自己动多少**从少到多排：计划（只看不动）→ 每步都问 →
 * 自动 → 自动接受编辑。bypassPermissions 不列——它要启动时开，轮换里到不了；
 * 真在那一档时由下面「当前这档必须在列」补进来。
 *
 * Codex 的 Shift+Tab 只在「计划 ↔ 默认」之间倒，沙箱与审批策略是另一件事，走 /approvals。
 */
export function modeChoices(agent?: 'claude' | 'codex' | 'opencode', current?: string): string[] {
  const base = agent === 'codex' ? ['plan', 'default'] : ['plan', 'manual', 'auto', 'acceptEdits']
  // 当前这档必须在列——老版本 Claude 报 default，新版本报 auto，谁都不该从列表里消失
  return current && !base.includes(current) ? [current, ...base] : base
}

export type PlusRowId = 'files' | 'mode' | 'goal' | 'model' | 'compact' | 'review' | 'git'
export type PlusGroupId = 'bring' | 'turn' | 'do' | 'goto'

export type PlusRow = {
  id: PlusRowId
  /** 右端那截当前值；没有就不画（宁可空着，也不画一个「—」占位） */
  value?: string
  /** 值前面那颗点的颜色：模式的含义靠颜色说（计划蓝 / 自动接受绿 / 越权黄） */
  dot?: string
  /** 值本身的颜色；只有上下文快满时才上色 */
  tone?: string
  /** 按键提示（同一件事在终端里怎么按） */
  kbd?: string
  disabled?: boolean
  /** 点过了、新状态还没回来：值淡一档，别让人以为没生效又点一次 */
  pending?: boolean
}

export type PlusGroup = { id: PlusGroupId; rows: PlusRow[] }

/** 上下文占用 → 值的颜色。阈值与状态条同源（CTX_TIGHT / CTX_FULL） */
function ctxColor(percent: number): string | undefined {
  if (percent >= CTX_FULL) return 'var(--danger)'
  if (percent >= CTX_TIGHT) return 'var(--warn)'
  return undefined
}

export function plusGroups(o: {
  /** 没有 agent（纯终端会话）时整组「这一轮怎么干」不出现：那几条都是发给 agent 的 */
  agent?: 'claude' | 'codex' | 'opencode'
  status?: AgentStatus
  /** 从终端画面读到的当前权限档；有就盖过转录那份（转录要下一轮才更新） */
  mode?: AgentStatus['mode']
  uploading?: boolean
  canGit?: boolean
  /** 正在等这次模式切换生效 */
  modePending?: boolean
  /** Codex 长跑目标的状态（从画面读的） */
  goal?: GoalState
  t: (key: string, vars?: Record<string, unknown>) => string
}): PlusGroup[] {
  const { status, t } = o
  const groups: PlusGroup[] = [
    { id: 'bring', rows: [{ id: 'files', disabled: !!o.uploading }] },
  ]

  if (o.agent) {
    const rows: PlusRow[] = []

    // 认不出的模式 id 原样显示：新模式先出现在 CLI 里是常态，不该把 key 画到面板上
    const mode = o.mode ?? status?.mode
    const label = mode ? t(modeKey(mode.id)) : ''
    if (o.agent !== 'opencode') rows.push({
      id: 'mode',
      value: o.modePending ? t('chat.plus.modeWaiting') : mode ? (label.startsWith('chat.mode.') ? mode.id : label) : undefined,
      dot: mode && !o.modePending ? MODE_COLOR[mode.tone] : undefined,
      kbd: 'Shift+Tab',
      pending: !!o.modePending,
    })

    // 目标是 Codex 独有的长跑装置：设一个目标，它自己盯着跑，跑不动了页脚会说
    if (o.agent === 'codex') {
      rows.push({
        id: 'goal',
        value: o.goal ? t('chat.plus.goal.' + o.goal) : undefined,
        // 卡住 / 额度用尽是「它停下来了而你不知道」，该上警戒色；已达成与暂停不是坏消息
        tone: o.goal === 'stalled' || o.goal === 'budget' ? 'var(--warn)' : undefined,
      })
    }

    rows.push({ id: 'model', value: status?.model })

    const ctx = status?.context
    rows.push({
      id: 'compact',
      value: ctx ? `${Math.round(ctx.percent)}%` : undefined,
      tone: ctx ? ctxColor(ctx.percent) : undefined,
    })

    groups.push({ id: 'turn', rows })
  }

  // 「顺手让它做」：不是设置，是当场派一件活。/review 两端都有
  if (o.agent && o.agent !== 'opencode') groups.push({ id: 'do', rows: [{ id: 'review' }] })

  if (o.canGit) groups.push({ id: 'goto', rows: [{ id: 'git' }] })
  return groups
}
