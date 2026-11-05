// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { closeSession, renameSession, sendSessionPrompt, stopSession } from './session-actions'

const node = vi.hoisted(() => ({ id: 'one' }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => node.id + path }))
vi.mock('../agent/agent-task-events', () => ({ refreshTask: vi.fn() }))
afterEach(() => { vi.resetAllMocks(); node.id = 'one' })

const detail = (revision = 3, id = 'native-one') => ({ task: { id: 'task-one', revision, nativeSession: { id } }, attempts: [{ id: 'run-' + revision }] })
const reads = (revision = 3) => vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path === '/agent/native-sessions/native-one' ? { taskId: 'task-one' } : detail(revision) }))

it('preserves ordinary session operations', async () => {
  vi.mocked(api).mockResolvedValue({ data: {} })
  await renameSession('codex-one', 'Follow-up')
  await stopSession('codex-one')
  await closeSession('codex-one')
  expect(vi.mocked(api).mock.calls).toEqual([
    ['PATCH', '/sessions/codex-one', { name: 'Follow-up' }],
    ['POST', '/sessions/codex-one/keys', { keys: ['Escape'] }],
    ['DELETE', '/sessions/codex-one'],
  ])
})

it('renames only the Roami session and closes its current run without accepting the task', async () => {
  reads()
  await renameSession('roami:native-one', 'Follow-up')
  await closeSession('roami:native-one')
  expect(api).toHaveBeenCalledWith('PATCH', '/agent/native-sessions/native-one', { name: 'Follow-up' })
  expect(api).toHaveBeenLastCalledWith('POST', '/agent/tasks/task-one/close-session', { revision: 3, runId: 'run-3' })
  expect(vi.mocked(api).mock.calls.some(([, path]) => path.includes('/verify') || path.startsWith('/sessions/'))).toBe(false)
})

it('rereads task identity after a failed close and stops the current revision', async () => {
  reads()
  vi.mocked(api).mockImplementationOnce(async () => { throw new Error('offline') })
  await expect(closeSession('roami:native-one')).rejects.toThrow('offline')
  reads(4)
  await closeSession('roami:native-one')
  expect(api).toHaveBeenLastCalledWith('POST', '/agent/tasks/task-one/close-session', { revision: 4, runId: 'run-4' })
  await stopSession('roami:native-one')
  expect(api).toHaveBeenLastCalledWith('POST', '/agent/tasks/task-one/cancel', { revision: 4 })
})

it.each(['node', 'binding'])('rejects a changed %s before sending a destructive action', async change => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/native-sessions/native-one') { if (change === 'node') node.id = 'two'; return { data: { taskId: 'task-one' } } }
    return { data: detail(3, 'different') }
  })
  await expect(closeSession('roami:native-one')).rejects.toMatchObject({ apiError: { code: 'TASK_REVISION_CHANGED' } })
  expect(vi.mocked(api).mock.calls.every(([method]) => method === 'GET')).toBe(true)
})

it('delivers a peer introduction to a Roami chat through its current task binding', async () => {
  reads(4)
  await sendSessionPrompt('roami:native-one', 'Peer introduction')
  expect(api).toHaveBeenLastCalledWith('POST', '/agent/tasks/task-one/steer', { text: 'Peer introduction', revision: 4, requestKey: expect.any(String) })
})
