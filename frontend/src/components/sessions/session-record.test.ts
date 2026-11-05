import { expect, it } from 'vitest'
import { nativeSessionId, nativeSessionRecord } from './session-record'
import { buildSessionProjects } from './session-project'
import { buildTaskTree } from '../shell/task-tree'
import { mergeWorktreeSessions } from '../projects/project-list/project-sessions'

it('places Roami beside Codex in the same worktree with the same session state', () => {
  const project = { key: 'project', name: 'Project', dir: '/work', git: true }
  const native = { nativeSessionId: 'one', taskId: 'task', title: 'Follow-up', projectId: 'project', directory: '/work/.worktrees/change', branch: 'fix/change', taskState: 'waiting_user', lastActivity: 100 }
  const record = nativeSessionRecord(native)
  expect(record).toMatchObject({ name: 'roami:one', label: 'Follow-up', agent: 'native', running: false, waiting: false })
  expect(nativeSessionId(record.name)).toBe('one')
  const placement = buildSessionProjects([project], {}, [native])
  const tree = buildTaskTree({ projects: [project], worktrees: { project: [{ path: native.directory, branch: native.branch, isMain: false, sessions: [{ session: 'codex' }] }] }, placement, sessions: [{ name: 'codex', agent: 'codex' }, record] })
  expect(tree.projects[0].tasks[0].sessions.map(session => session.name).sort()).toEqual(['codex', 'roami:one'])
  expect(tree.loose).toHaveLength(0)
})

it('keeps a worktree with a Roami session out of orphan cleanup candidates', () => {
  const native = { nativeSessionId: 'one', taskId: 'task', title: 'Chat', taskState: 'running', directory: '/work/change' }
  const worktrees = [{ path: '/work/change', sessions: null }, { path: '/work/empty', sessions: [] }]
  const merged = mergeWorktreeSessions(worktrees, [native])
  expect(merged.filter(worktree => !worktree.sessions?.length).map(worktree => worktree.path)).toEqual(['/work/empty'])
  expect(worktrees[0].sessions).toBeNull()
  expect(mergeWorktreeSessions(merged, [native])[0].sessions).toEqual([{ session: 'roami:one' }])
})
