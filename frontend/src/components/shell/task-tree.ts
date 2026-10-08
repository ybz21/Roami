import type { AgentKind } from '../../agent-kind'
// 左栏项目树的读模型：项目 → 任务（worktree）→ 会话（22 设计 §3.2）。
//
// 三条现成接口合成，没有新接口：
//   /projects            项目、每项目「需要你」的会话（needs）与最近会话（top）
//   /git/worktrees?dir=  每个 git 项目的 worktree 与挂在上面的会话
//   /sessions            全部会话（散会话从这里来：不在任何 worktree 上的）
// 纯函数：App 把三份数据拿到手后 useMemo 一次，数据没变就不重算。
import { isInfraSession } from '../sessions/infra-session'
import { taskKeyOf, type TaskKey } from '../sessions/task-key'

export type TreeSession = {
  name: string
  label: string
  /** 最近活动（unix 秒），行尾的「1d」 */
  at?: number
  /** 休眠：被重启带走、台账还认得，点开即在原目录重开 */
  dormant?: boolean
  agent?: AgentKind
  running?: boolean
  waiting?: boolean
  /** 互审陪跑会话（<被审会话>-review）：审谁写在这儿，树上挂到被审那条下面 */
  reviewOf?: string
}

export type TreeTask = {
  key: TaskKey
  /** 任务名：第一个会话的展示名，没有会话就用分支名 */
  name: string
  branch: string
  /** 主仓库检出：只在有会话时立一张卡（标「主仓库」），没会话不算空闲 worktree，也不能收尾 */
  main?: boolean
  path: string
  /** 领先 base 的提交数；会话都关了还有未合并提交 = 待收尾 */
  ahead: number
  /** worktree 状态（卡片第二行的小字）：未提交改动数、落后 base、已合入 base、已推送 */
  dirty?: number
  behind?: number
  merged?: boolean
  pushed?: boolean
  unfinished: boolean
  sessions: TreeSession[]
}

export type TreeProject = { key: string; name: string; dir: string; needs: number; tasks: TreeTask[] }

export type TaskTree = { projects: TreeProject[]; loose: TreeSession[] }

type ProjIn = {
  key: string; name: string; dir: string; git: boolean
  waiting?: number; unfinished?: number
  top?: { name: string; label?: string; running?: boolean; waiting?: boolean; agent?: AgentKind; state?: string }[] | null
  needs?: { name: string; label?: string; running?: boolean; waiting?: boolean; agent?: AgentKind; state?: string }[] | null
}
type WtIn = { path: string; branch: string; isMain: boolean; committedAhead?: number; dirty?: number; untracked?: number; behind?: number; mergedInto?: string; pushed?: boolean; sessions?: { session: string; dormant?: boolean }[] | null }
type SessIn = { name: string; label?: string; lastActivity?: number; agent?: AgentKind }

export function buildTaskTree(o: {
  projects: ProjIn[]
  /** 项目 key → 该项目的 worktree 列表 */
  worktrees: Record<string, WtIn[]>
  sessions: SessIn[]
  /** 已打开会话里探测到的 agent（比 /projects 的 top 名单准、也更新） */
  agentOf?: (name: string) => AgentKind | undefined
  /** 会话归属表（/sessions/annotations，15s 一轮）：会话 → 项目 key + worktree 路径 */
  placement?: Record<string, { key: string; worktree?: string; branch?: string }>
  /** 人给任务起的名（偏好 taskNames）：有就用它，会话改名不再连带任务改名 */
  nameOf?: (path: string) => string | undefined
  /** /sessions 已经回来过一轮：此后 sessions 就是「在」的全集，worktree 里多出来的名字都是已经没了的 */
  sessionsLoaded?: boolean
  /** 会话 id → 会话名。互审陪跑叫 `<被审会话id>-review`，靠它把 id 还原成人看得懂的那个 */
  nameOfId?: (id: string) => string | undefined
}): TaskTree {
  // 会话的展示信息：先从 /projects 的 top / needs 里捞（带 agent / running / waiting），再补 /sessions 的 label
  const info = new Map<string, TreeSession>()
  const put = (s: { name: string; label?: string; running?: boolean; waiting?: boolean; agent?: AgentKind; lastActivity?: number; state?: string; dormant?: boolean }) => {
    const cur = info.get(s.name) || { name: s.name, label: s.label || s.name }
    info.set(s.name, {
      ...cur,
      label: s.label || cur.label,
      at: s.lastActivity || cur.at,
      dormant: s.dormant || s.state === 'dormant' || cur.dormant,
      agent: s.agent || cur.agent,
      running: s.running ?? cur.running,
      waiting: s.waiting ?? cur.waiting,
    })
  }
  for (const p of o.projects) {
    for (const s of p.top || []) put(s)
    for (const s of p.needs || []) put(s)
  }
  for (const s of o.sessions) put(s)
  const sess = (name: string): TreeSession => {
    const s = info.get(name) || { name, label: name }
    const agent = o.agentOf?.(name) || s.agent
    return agent ? { ...s, agent } : s
  }

  // worktree 那份名单比 /sessions 旧（60s 一轮，还可能是刷新时先顶上的本地快照），
  // 会话关掉后它还挂着人名——点进去是个不存在的会话。/sessions 是「在」的全集（live +
  // dormant 都在里面：CLI 的 ls 收尾会 appendDormant），所以它一回来，就以它为准把已经
  // 没了的名字滤掉。
  //
  // **休眠会话一律不滤**：两边的 dormant 都读同一张 sessions 表、同一套条件（见
  // backend/worktree/sessionhome.go 的 dormantSQL 注释），照理不会打架；但两次查询之间
  // 隔着 60s，真要错开一次，代价是「点开即恢复」的唯一入口从树上没了——这一格的保险
  // 比那点整洁值钱。已经关掉的会话在快照里本来就是活的、不带这个标，照滤不误。
  const live = o.sessionsLoaded ? new Set(o.sessions.map((s) => s.name)) : null
  const alive = (n: string, dormant?: boolean) => !live || dormant || live.has(n)

  const placed = new Set<string>()
  const projects: TreeProject[] = o.projects.map((p) => {
    const tasks: TreeTask[] = []
    for (const wt of o.worktrees[p.key] || []) {
      // worktree 带来的会话列表是**另一条来源**（不是 /sessions），基础设施会话得在这里
      // 再滤一遍——上一版只滤了 /sessions，于是 _ttmux-plugind 照样从这条路挂进任务里。
      const names = (wt.sessions || []).filter((s) => s.session && !isInfraSession(s.session) && alive(s.session, s.dormant)).map((s) => s.session)
      // 主仓库检出：有会话才立卡（在仓库根目录开的 claude 也得归到项目下，不能丢进散会话）；
      // 没会话不立——它不是一个可收尾的任务位，每个项目都挂一张空的「main」只会碍事
      if (wt.isMain && names.length === 0) continue
      names.forEach((n) => placed.add(n))
      for (const s of wt.sessions || []) if (s.dormant && !isInfraSession(s.session)) put({ name: s.session, dormant: true })
      const sessions = names.map(sess)
      const ahead = wt.committedAhead || 0
      tasks.push({
        key: taskKeyOf('', wt.path),
        name: o.nameOf?.(wt.path) || sessions[0]?.label || wt.branch || wt.path.split('/').pop() || wt.path,
        branch: wt.branch || '',
        path: wt.path,
        ahead,
        dirty: (wt.dirty || 0) + (wt.untracked || 0), behind: wt.behind || 0, merged: !!wt.mergedInto, pushed: !!wt.pushed,
        unfinished: !wt.isMain && sessions.length === 0 && ahead > 0,
        sessions,
        ...(wt.isMain ? { main: true } : {}),
      })
    }
    // 刚建的会话：worktree 轮询 60s 一轮还没追上，但 annotation 已经知道它在哪个 worktree——
    // 先按 annotation 立一个任务位，别让它在「散会话」里闪一下、一分钟后再跳到项目下
    const root = p.dir.replace(/\/+$/, '')
    for (const s of o.sessions) {
      if (placed.has(s.name)) continue
      const pl = o.placement?.[s.name]
      const wt = pl?.worktree?.replace(/\/+$/, '')
      if (!pl || pl.key !== p.key || !wt) continue
      const isMain = wt === root
      placed.add(s.name)
      const hit = tasks.find((x) => x.path.replace(/\/+$/, '') === wt)
      if (hit) {
        hit.sessions.push(sess(s.name))
        hit.name = o.nameOf?.(hit.path) || hit.sessions[0].label
        hit.unfinished = false
        continue
      }
      const ss = [sess(s.name)]
      tasks.push({ key: taskKeyOf('', wt), name: o.nameOf?.(wt) || ss[0].label, branch: pl.branch || '', path: wt, ahead: 0, unfinished: false, sessions: ss, ...(isMain ? { main: true } : {}) })
    }

    // 兜底：/projects 自己已经把这些会话算给了这个项目（top/needs 是后端按 cwd 归属出来的，
    // **非 git 目录也算**）。上面两条路都只认 worktree —— 于是像 /home/ai/codes 这种
    // 「放着一堆仓库的普通目录」建成的项目，会话在项目页里好好列在项目下，
    // 左树却把它们扔进「散会话」，同一件事两处不一致。以项目页为准。
    const owned = new Set([...(p.top || []), ...(p.needs || [])].map((x) => x.name))
    for (const s of o.sessions) {
      if (placed.has(s.name) || !owned.has(s.name) || isInfraSession(s.name)) continue
      placed.add(s.name)
      const hit = tasks.find((x) => x.path.replace(/\/+$/, '') === root)
      if (hit) {
        // 只挂进去，**不改名**：这张卡叫项目名，再来一个会话不该把它改成那个会话的名字
        hit.sessions.push(sess(s.name))
        hit.unfinished = false
        continue
      }
      const ss = [sess(s.name)]
      // 项目根就是它的「任务位」：非 git 项目没有 worktree，也就没有别的位置可给。
      // 名字用项目名而不是第一个会话的 label——这张卡代表的是「在项目目录里干活」，
      // 不是某一个会话；跟着会话取名的话，再开一个会话它就莫名其妙改名了。
      tasks.push({ key: taskKeyOf('', root), name: o.nameOf?.(root) || p.name, branch: '', path: root, ahead: 0, unfinished: false, sessions: ss, main: true })
    }
    return { key: p.key, name: p.name, dir: p.dir, needs: (p.waiting || 0) + (p.unfinished || 0), tasks }
  })

  const loose = o.sessions.filter((s) => !placed.has(s.name)).map((s) => sess(s.name))

  // ── 互审陪跑归位 ────────────────────────────────────────────────────────
  //
  // reviewmesh 起的陪跑会话叫 `<被审会话>-review`（那个「被审会话」写的是 id）。
  // 它按自己的 cwd 落进 worktree，于是常常挂到**别人**的任务下面：截图里
  // 「2026-0905-2122-0076-review」挂在 roam优化 那张卡里，而它审的是隔壁那张卡的活。
  // 光看那一行也说不清它是什么——名字是一串 id。
  //
  // 这里按名字把它认出来，挪到被审会话所在的任务、紧跟在被审那条后面，并记下 reviewOf，
  // 让树自己决定怎么画（缩进 + 「互审 · 谁」）。
  const authorOf = (name: string): string | null => {
    if (!name.endsWith('-review')) return null
    const token = name.slice(0, -'-review'.length)
    return o.nameOfId?.(token) || token
  }
  const allTasks = projects.flatMap((p) => p.tasks)
  const homeOf = new Map<string, TreeTask>() // 会话名 → 它所在的任务
  for (const task of allTasks) for (const s of task.sessions) homeOf.set(s.name, task)

  const relocate = (s: TreeSession, from: TreeTask | null) => {
    const author = authorOf(s.name)
    if (!author) return false
    const home = homeOf.get(author)
    // reviewOf 存的是**给人看的那个名字**：树上要写「互审 · 谁」，写会话名等于又印一串 id
    s.reviewOf = home?.sessions.find((x) => x.name === author)?.label || author
    if (!home || home === from) return false
    if (from) from.sessions = from.sessions.filter((x) => x.name !== s.name)
    const at = home.sessions.findIndex((x) => x.name === author)
    home.sessions.splice(at < 0 ? home.sessions.length : at + 1, 0, s)
    homeOf.set(s.name, home)
    return true
  }
  for (const task of allTasks) for (const s of [...task.sessions]) relocate(s, task)
  const stillLoose = loose.filter((s) => !relocate(s, null))

  return { projects, loose: stillLoose }
}
