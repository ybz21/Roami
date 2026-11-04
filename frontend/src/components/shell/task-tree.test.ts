import { describe, it, expect } from 'vitest'
import { buildTaskTree } from './task-tree'
import { LOOSE_PREFIX } from '../sessions/task-key'

const roam = { key: 'roam', name: 'Roam', dir: '/w/Roam', git: true, waiting: 1, unfinished: 1,
  top: [{ name: 'roam-cc', label: '三栏重做', running: true, agent: 'claude' as const }],
  needs: [{ name: 'roam-cx', label: '接回对话', waiting: true, agent: 'codex' as const }] }
const wts = {
  roam: [
    { path: '/w/Roam', branch: 'main', isMain: true, sessions: [{ session: 'in-main' }] },
    { path: '/w/Roam/.worktrees/a', branch: 'chore/a', isMain: false, committedAhead: 2, sessions: [{ session: 'roam-cc' }, { session: 'roam-sh' }] },
    { path: '/w/Roam/.worktrees/b', branch: 'fix/b', isMain: false, sessions: [{ session: 'roam-cx' }] },
    { path: '/w/Roam/.worktrees/c', branch: 'feat/c', isMain: false, committedAhead: 3, sessions: [] },
  ],
}
const sessions = [
  { name: 'roam-cc', label: '三栏重做' }, { name: 'roam-sh' }, { name: 'roam-cx', label: '接回对话' },
  { name: 'in-main', label: '主仓库里开的' }, { name: 'htop' },
]

describe('项目树读模型', () => {
  const tree = buildTaskTree({ projects: [roam], worktrees: wts, sessions })

  it('worktree 是任务；主仓库里有会话也立一张标 main 的卡', () => {
    expect(tree.projects[0].tasks.map((t) => t.branch)).toEqual(['main', 'chore/a', 'fix/b', 'feat/c'])
    expect(tree.projects[0].tasks[0].main).toBe(true)
    expect(tree.projects[0].tasks[0].sessions.map((s) => s.name)).toEqual(['in-main'])
    expect(tree.projects[0].tasks[1].key).toBe('/w/Roam/.worktrees/a')
  })

  it('主仓库没会话就不立卡，也不算待收尾', () => {
    const t2 = buildTaskTree({ projects: [roam], worktrees: { roam: [{ path: '/w/Roam', branch: 'main', isMain: true, committedAhead: 5, sessions: [] }] }, sessions: [] })
    expect(t2.projects[0].tasks).toEqual([])
  })

  it('任务名取第一个会话的展示名，没有会话就用分支名', () => {
    const [, a, , c] = tree.projects[0].tasks
    expect(a.name).toBe('三栏重做')
    expect(c.name).toBe('feat/c')
  })

  it('会话都关了还有未合并提交 = 待收尾', () => {
    const [, a, b, c] = tree.projects[0].tasks
    expect(c.unfinished).toBe(true)
    expect(a.unfinished).toBe(false) // 有会话，ahead 再多也不算待收尾
    expect(b.unfinished).toBe(false)
  })

  it('agent / running / waiting 从 /projects 的 top 与 needs 里来', () => {
    const [, a, b] = tree.projects[0].tasks
    expect(a.sessions[0]).toMatchObject({ name: 'roam-cc', agent: 'claude', running: true })
    expect(a.sessions[1]).toMatchObject({ name: 'roam-sh', label: 'roam-sh' })
    expect(b.sessions[0]).toMatchObject({ agent: 'codex', waiting: true })
  })

  it('只有不在任何项目里的会话才是散会话；主仓库里的挂在项目下', () => {
    expect(tree.loose.map((s) => s.name)).toEqual(['htop'])
    expect(tree.projects[0].tasks[0].sessions[0].label).toBe('主仓库里开的')
  })

  it('项目行的计数 = 等待 + 待收尾', () => {
    expect(tree.projects[0].needs).toBe(2)
  })

  it('已打开会话探测到的 agent 优先于 top 名单', () => {
    const t2 = buildTaskTree({ projects: [roam], worktrees: wts, sessions, agentOf: (n) => (n === 'roam-sh' ? 'codex' : undefined) })
    expect(t2.projects[0].tasks[1].sessions[1].agent).toBe('codex')
  })

  it('散会话的 key 带前缀，不会和路径撞', () => {
    expect(LOOSE_PREFIX + 'htop').not.toMatch(/^\//)
  })
})

describe('buildTaskTree placement', () => {
  it('moves business sessions out of a stale worktree snapshot before the next repository scan', () => {
    const tree = buildTaskTree({
      projects: [{ key: 'code', name: 'Roami', dir: '/code', git: true }, { key: 'promotion', name: 'Promotion', dir: '/promotion', git: false }],
      worktrees: { code: [{ path: '/code/.worktrees/dev', branch: 'dev', isMain: false, sessions: [{ session: 'data' }, { session: 'developer' }] }] },
      sessions: [{ name: 'data' }, { name: 'developer' }],
      placement: { data: { key: 'promotion' }, developer: { key: 'code', worktree: '/code/.worktrees/dev' } },
    })
    expect(tree.projects[0].tasks.flatMap(task => task.sessions.map(s => s.name))).toEqual(['developer'])
    expect(tree.projects[1].tasks.flatMap(task => task.sessions.map(s => s.name))).toEqual(['data'])
    expect(tree.loose).toEqual([])
  })
  const proj = { key: 'x', name: 'X', dir: '/x', git: true }
  it('annotation 里已知 worktree 的新会话立刻挂到任务位，不等 worktree 轮询', () => {
    const tree = buildTaskTree({
      projects: [proj], worktrees: { x: [{ path: '/x', branch: 'main', isMain: true }] },
      sessions: [{ name: 'new-cc', label: '检查项目' }],
      placement: { 'new-cc': { key: 'x', worktree: '/x/.worktrees/a', branch: 'a' } },
    })
    expect(tree.loose).toEqual([])
    expect(tree.projects[0].tasks.map((t) => [t.path, t.name, t.sessions.map((s) => s.name)])).toEqual([['/x/.worktrees/a', '检查项目', ['new-cc']]])
  })
  it('worktree 轮询已经有这个 worktree 但会话名单还旧：补进去、任务名换成会话名', () => {
    const tree = buildTaskTree({
      projects: [proj], worktrees: { x: [{ path: '/x/.worktrees/a/', branch: 'a', isMain: false, committedAhead: 2 }] },
      sessions: [{ name: 'new-cc', label: '检查项目' }],
      placement: { 'new-cc': { key: 'x', worktree: '/x/.worktrees/a' } },
    })
    const task = tree.projects[0].tasks[0]
    expect(task.name).toBe('检查项目')
    expect(task.unfinished).toBe(false)
    expect(task.sessions.map((s) => s.name)).toEqual(['new-cc'])
  })
  it('annotation 指向主仓库的会话：挂到项目下一张标 main 的卡，不进散会话', () => {
    const tree = buildTaskTree({ projects: [proj], worktrees: {}, sessions: [{ name: 's' }], placement: { s: { key: 'x', worktree: '/x', branch: 'main' } } })
    expect(tree.loose).toEqual([])
    expect(tree.projects[0].tasks.map((t) => [t.path, t.main, t.sessions.map((s) => s.name)])).toEqual([['/x', true, ['s']]])
  })
})

// worktree 名单（60s 一轮，刷新时还先顶本地快照）比 /sessions 旧：会话关掉后它还挂着人名，
// 树上就留一行点进去不存在的会话。/sessions 一回来就以它为准。
describe('已经关掉的会话不留在树上', () => {
  const wt = { roam: [{ path: '/w/Roam/.worktrees/a', branch: 'chore/a', isMain: false, committedAhead: 2, sessions: [{ session: 'roam-cc' }, { session: 'gone' }] }] }
  it('会话表还没回来时照旧全画（第一帧不能把快照清空）', () => {
    const t = buildTaskTree({ projects: [roam], worktrees: wt, sessions: [] })
    expect(t.projects[0].tasks[0].sessions.map((s) => s.name)).toEqual(['roam-cc', 'gone'])
  })
  it('会话表回来了就滤掉不在里面的名字，任务照旧留着', () => {
    const t = buildTaskTree({ projects: [roam], worktrees: wt, sessions: [{ name: 'roam-cc' }], sessionsLoaded: true })
    expect(t.projects[0].tasks[0].sessions.map((s) => s.name)).toEqual(['roam-cc'])
    expect(t.projects[0].tasks[0].unfinished).toBe(false)
  })
  it('休眠会话不滤：点开即恢复的唯一入口不能因为两边错开一次就没了', () => {
    const dw = { roam: [{ path: '/w/Roam/.worktrees/d', branch: 'fix/d', isMain: false, sessions: [{ session: 'napping', dormant: true }, { session: 'gone' }] }] }
    const t = buildTaskTree({ projects: [roam], worktrees: dw, sessions: [], sessionsLoaded: true })
    expect(t.projects[0].tasks[0].sessions.map((s) => s.name)).toEqual(['napping'])
    expect(t.projects[0].tasks[0].sessions[0].dormant).toBe(true)
  })
  it('会话全没了的 worktree 变回待收尾', () => {
    const t = buildTaskTree({ projects: [roam], worktrees: wt, sessions: [], sessionsLoaded: true })
    expect(t.projects[0].tasks[0].sessions).toEqual([])
    expect(t.projects[0].tasks[0].unfinished).toBe(true)
  })
})

// _ttmux- 是基础设施会话的命名空间（插件守护进程、IM 监听）。它们跑在真 tmux 会话里，
// 于是会顺着 /sessions 混进项目树，挂在某个任务下面——既不属于那个任务，人也不该点进去。
describe('基础设施会话不进树', () => {
  it('_ttmux-plugind 既不进任务，也不进散会话', async () => {
    const { isInfraSession } = await import('../sessions/infra-session')
    expect(isInfraSession('_ttmux-plugind')).toBe(true)
    expect(isInfraSession('_ttmux-im')).toBe(true)
    expect(isInfraSession('roam优化')).toBe(false)
    expect(isInfraSession('2026-0904-2359-abcd')).toBe(false)
  })
})

// 互审陪跑（reviewmesh 起的 `<被审会话id>-review`）：它按自己的 cwd 落进 worktree，
// 常常挂到别人的任务下面，而那一行印的又是一串 id——两件事都得治。
describe('互审陪跑归位', () => {
  const proj = { key: 'x', name: 'X', dir: '/x', git: true }
  const wts = { x: [
    { path: '/x', branch: 'main', isMain: true, sessions: [{ session: 'roam优化' }, { session: '2026-0001-review' }] },
    { path: '/x/.worktrees/a', branch: 'wt-a', isMain: false, sessions: [{ session: '提速' }] },
  ] }

  it('挪到被审会话那张卡，并紧跟在它后面', () => {
    const tree = buildTaskTree({
      projects: [proj], worktrees: wts,
      sessions: [{ name: 'roam优化' }, { name: '提速' }, { name: '2026-0001-review' }],
      nameOfId: (id) => (id === '2026-0001' ? '提速' : undefined),
    })
    const main = tree.projects[0].tasks.find((t) => t.path === '/x')!
    const wt = tree.projects[0].tasks.find((t) => t.path === '/x/.worktrees/a')!
    expect(main.sessions.map((s) => s.name)).toEqual(['roam优化'])
    expect(wt.sessions.map((s) => s.name)).toEqual(['提速', '2026-0001-review'])
    expect(wt.sessions[1].reviewOf).toBe('提速')
  })

  it('被审会话找不到时不乱挪，但仍标出它审的是谁', () => {
    const tree = buildTaskTree({
      projects: [proj], worktrees: { x: [{ path: '/x', branch: 'main', isMain: true, sessions: [{ session: 'ghost-review' }] }] },
      sessions: [{ name: 'ghost-review' }],
    })
    const main = tree.projects[0].tasks[0]
    expect(main.sessions.map((s) => s.name)).toEqual(['ghost-review'])
    expect(main.sessions[0].reviewOf).toBe('ghost')
  })
})

// 非 git 目录建的项目（比如 /home/ai/codes 这种放着一堆仓库的目录）：没有 worktree，
// 会话的归属只能来自 /projects 的 top/needs。原来这一层只认 worktree 与 annotation，
// 于是项目页把会话列在项目下、左树却扔进「散会话」——同一件事两处不一致。
it('项目页说它属于这个项目，左树就得挂在这个项目下（非 git 项目也是）', () => {
  const tree = buildTaskTree({
    projects: [{
      key: 'p-codes', name: 'codes', dir: '/home/ai/codes', git: false,
      top: [{ name: 's-plan', label: 'ai-combat-planner' }, { name: 's-cc', label: '排查CC连接中断' }],
    }],
    worktrees: {},
    sessions: [{ name: 's-plan', label: 'ai-combat-planner' }, { name: 's-cc', label: '排查CC连接中断' }],
    sessionsLoaded: true,
  })

  expect(tree.loose).toEqual([])
  const [proj] = tree.projects
  expect(proj.tasks).toHaveLength(1)
  expect(proj.tasks[0].path).toBe('/home/ai/codes')
  expect(proj.tasks[0].sessions.map((s) => s.label)).toEqual(['ai-combat-planner', '排查CC连接中断'])
})

it('worktree 已经安置过的不重复挂一遍', () => {
  const tree = buildTaskTree({
    projects: [{
      key: 'p', name: 'repo', dir: '/repo', git: true,
      top: [{ name: 's1', label: '活儿' }],
    }],
    worktrees: { p: [{ path: '/repo/.worktrees/a', branch: 'feat/a', isMain: false, sessions: [{ session: 's1' }] }] },
    sessions: [{ name: 's1', label: '活儿' }],
    sessionsLoaded: true,
  })
  const [proj] = tree.projects
  expect(proj.tasks).toHaveLength(1)
  expect(proj.tasks[0].path).toBe('/repo/.worktrees/a')
  expect(proj.tasks[0].sessions).toHaveLength(1)
})
