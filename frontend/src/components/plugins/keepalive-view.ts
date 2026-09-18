// 会话守护面板的取数与排序——纯函数，和 React 无关，单测直接喂数据。
//
// 设计稿：docs/design/plugin/keepalive-panel.html（§03 六种行状态、§04 排序与过滤）。

export type KaGuard = {
  session: string
  label: string
  enabled: boolean
  /** 逐会话覆盖（空/0 = 跟随全局） */
  prompt?: string
  idleMin?: number
  everyMin?: number
  /** 实际生效值（Go 侧已把覆盖并进全局） */
  effPrompt: string
  effIdleMin: number
  effEveryMin: number
  sends: number
  lastSent: number
  quietSince: number
  streak: number
  maxQuiet: number
  stoppedAt: number
}

export type KaRow = {
  session: string
  label: string
  /** claude | codex | ''（认不出） */
  agent: string
  dir: string
  attached: boolean
  /** tmux 活动时间算出来的安静时长，只用于**没被守护**的行 */
  idleSec: number
  created: number
  guard?: KaGuard
}

export type KaSettings = {
  prompt: string
  idleMin: number
  everyMin: number
  maxQuiet: number
  defaultPrompt: string
  maxPromptLen: number
}

export type KaRule = { match: string; atNth: number; prompt: string; enabled: boolean; fallback: boolean }

/** 一行此刻处在哪一档。颜色、首要动作、排序全看它。 */
export type RowState = 'stopped' | 'guarded' | 'off'

export function rowState(r: KaRow): RowState {
  if (!r.guard) return 'off'
  if (r.guard.enabled) return 'guarded'
  return r.guard.stoppedAt > 0 ? 'stopped' : 'off'
}

/**
 * 这一行的「安静了」该显示哪个数。
 *
 * 守护中的行用 `quietSince`——**那才是阈值真正比对的那个数**（屏幕指纹没变起算）；
 * 没被守护的行没有指纹可比，只能退回 tmux 的活动时间。两者口径不同，
 * 但同一行显示的永远是「对这一行有意义」的那个。
 */
export function quietSec(r: KaRow, nowSec: number): number {
  const g = r.guard
  if (g?.enabled && g.quietSince > 0) return Math.max(0, nowSec - g.quietSince)
  return Math.max(0, r.idleSec || 0)
}

/**
 * 安静时长：一列要纵向扫的数字，所以短到能对齐。
 *
 * 0 秒给 `0s` 而不是 `—`：刚打开守护的那一行确实「安静了 0 秒」，那是一个真数字；
 * 破折号留给「没有这个数」（读不到、还没算出来），两件事不能长得一样。
 */
export function fmtIdle(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '—'
  if (sec < 60) return `${Math.floor(sec)}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`
  return `${Math.floor(sec / 86400)}d`
}

/** 安静超过阈值 = 下一轮就会被催，数字转暖色。没守护的行按全局阈值算。 */
export function idleIsLong(r: KaRow, nowSec: number, globalIdleMin: number): boolean {
  const min = r.guard?.effIdleMin || globalIdleMin
  return quietSec(r, nowSec) >= min * 60
}

/** 「刚刚催过」只亮 5 分钟：一直绿着就等于没有重点。 */
export const RECENT_SEC = 300

export function nudgedRecently(g: KaGuard | undefined, nowSec: number): boolean {
  return !!g && g.lastSent > 0 && nowSec - g.lastSent < RECENT_SEC
}

/**
 * 默认排序不是按名字，是按**该管谁**：
 * 出事的置顶 → 守护中（按安静时长倒序）→ 未守护（Agent 在前，再按安静倒序）。
 * 最该被看一眼的那行永远在第一行。
 */
const GROUP: Record<RowState, number> = { stopped: 0, guarded: 1, off: 2 }

export function sortRows(rows: KaRow[], nowSec: number): KaRow[] {
  return [...rows].sort((a, b) => {
    const ga = GROUP[rowState(a)]
    const gb = GROUP[rowState(b)]
    if (ga !== gb) return ga - gb
    // 未守护那一档里，认得出是 Agent 的排前面——下一个可能要开的就在这一档顶上
    if (ga === GROUP.off) {
      const aa = a.agent ? 0 : 1
      const ab = b.agent ? 0 : 1
      if (aa !== ab) return aa - ab
    }
    const qa = quietSec(a, nowSec)
    const qb = quietSec(b, nowSec)
    if (qa !== qb) return qb - qa
    // 兜底按会话 id（= 创建时刻）倒序，保证同数据永远排成同一个样子
    return a.session < b.session ? 1 : a.session > b.session ? -1 : 0
  })
}

export type FilterMode = 'all' | 'guarded' | 'agent'

/** 过滤条只在会话多到扫不过来时才出现；少于这个数，它纯属占地方。 */
export const FILTER_FROM = 8

export function filterRows(rows: KaRow[], mode: FilterMode, q: string): KaRow[] {
  const kw = q.trim().toLowerCase()
  return rows.filter((r) => {
    if (mode === 'guarded' && rowState(r) !== 'guarded') return false
    if (mode === 'agent' && !r.agent) return false
    if (!kw) return true
    return `${r.label} ${r.dir} ${r.session}`.toLowerCase().includes(kw)
  })
}

export function counts(rows: KaRow[]): Record<FilterMode, number> {
  return {
    all: rows.length,
    guarded: rows.filter((r) => rowState(r) === 'guarded').length,
    agent: rows.filter((r) => !!r.agent).length,
  }
}

/**
 * 「全部守护」要先说清楚会动几行、跳过几行——一次动很多行，且每一行都会开始花钱。
 * agentOnly 时认不出是 Agent 的会话不碰（往裸 shell 打字换来的是 command not found）。
 */
export function bulkPreview(rows: KaRow[], agentOnly: boolean): { willGuard: number; skipped: number } {
  let willGuard = 0
  let skipped = 0
  for (const r of rows) {
    if (agentOnly && !r.agent) { skipped++; continue }
    if (rowState(r) !== 'guarded') willGuard++
  }
  return { willGuard, skipped }
}

/** 规则表整表提交前的形状检查：兜底那条永远在最后、删不掉、不许关。 */
export function normalizeRules(rules: KaRule[]): KaRule[] {
  const normal = rules.filter((r) => !r.fallback && (r.match.trim() !== '' || r.atNth > 0))
  const fb = rules.find((r) => r.fallback)
  return [...normal, { match: '', atNth: 0, prompt: fb?.prompt || '', enabled: true, fallback: true }]
}

/** 上下拖一格。兜底条钉在最后，拖不动也拖不到它后面去。 */
export function moveRule(rules: KaRule[], from: number, to: number): KaRule[] {
  const last = rules.length - 1
  if (from === last || to === last || from < 0 || to < 0 || from >= rules.length || to >= rules.length) return rules
  const next = [...rules]
  const [it] = next.splice(from, 1)
  next.splice(to, 0, it)
  return next
}
