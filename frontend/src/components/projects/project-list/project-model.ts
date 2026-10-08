import type { AgentKind } from '../../../agent-kind'
// 项目列表页的读模型 —— 全部来自 GET /projects 一条接口（18 设计 §9）。
// 会话的 running/waiting/agent/tail 由后端一趟进程树扫描算好，前端不再逐会话探测。

// name 是会话名(= 会话 id，打开终端的 handle)，label 是展示名(@roam_name)
export type ProjSession = {
  name: string; label?: string; attached: boolean
  running?: boolean; waiting?: boolean
  // dormant：机器重启带走了 tmux 那一半，台账还认得它，点开即恢复（懒恢复，见 R2 设计稿）。
  state?: 'live' | 'dormant'
  // 只有逼近内存上限时后端才带这一段——平时不占位置。
  mem?: { cur: number; peak?: number; limit?: number }
  agent?: AgentKind  // 品牌标；后端进程树扫描分得出，不再前端逐会话问
  tail?: string               // 仅 waiting 时非空：那一屏最后一行，给行动卡当摘要
  lastActivity: number; branch?: string; linked?: boolean
}

export type Proj = {
  key: string; name: string; dir: string; git: boolean; pinned: boolean
  sessions: number; attached: number; worktrees: number; unfinished: number; cleanable: number; races: number
  lastActivity: number; firstSeen: number
  /** 归档时刻（秒，0/缺省 = 在册）。「不活跃」那节靠它排序并显示空了多久——
      少了它，5 分钟前空下来的和三个月没动的长得一模一样。 */
  archivedAt?: number
  /** 卡片「进行中」三行——**被后端截断过，不能拿它数数**。计数用 running/waiting，队列用 needs。 */
  top: ProjSession[] | null
  running?: number
  waiting?: number
  /** 全部等待输入的会话（不截断）。「需要你」队列要的是它——第 4 个以后的等待不能凭空消失。 */
  needs?: ProjSession[] | null
}

// 蜂群在项目上的投影（/swarms + 逐群详情，10s）
export type ProjSwarm = {
  name: string; projKey: string; projName: string
  total: number; inProj: number; pending: number
}

/** 一个项目「需要你」的件数：等待输入 + 待收尾 + 蜂群待解锁。排序与筛选都用它。 */
export function projNeeds(p: Proj, swarms: ProjSwarm[]): number {
  return waitingCount(p)
    + (p.unfinished || 0)
    + swarms.filter((sw) => sw.projKey === p.key && sw.pending > 0).length
}

/** 等待输入的会话数。**别从 top 数**——它只有三行，第 4 个以后的等待会被漏掉，
 *  「需要你」的计数和默认排序都会跟着失真。老后端没有这个字段时才回落到 top。 */
export function waitingCount(p: Proj): number {
  return p.waiting ?? (p.top || []).filter((s) => s.waiting).length
}

export function runningCount(p: Proj): number {
  return p.running ?? (p.top || []).filter((s) => s.running).length
}

/** 「需要你」队列要的全部等待会话；老后端回落到 top 里的那几个。 */
export function waitingSessions(p: Proj): ProjSession[] {
  return p.needs || (p.top || []).filter((s) => s.waiting)
}

// 项目图标底色：按 key 取一个稳定色，卡片多了才能一眼分辨是哪个项目
const ICO = [
  ['#9ccaff', 'rgba(31,111,235,.13)'], ['#c7a5ff', 'rgba(163,113,247,.13)'],
  ['#76d18a', 'rgba(63,185,80,.13)'], ['#f0ba5d', 'rgba(210,153,34,.13)'],
  ['#72d5de', 'rgba(57,197,207,.13)'], ['#f29089', 'rgba(248,81,73,.11)'],
] as const

export function icoOf(name: string): readonly [string, string] {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return ICO[h % ICO.length]
}
