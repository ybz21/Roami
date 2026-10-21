// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { clearAgentDataCache } from './agent-data-cache'
import { publishTaskEvent } from './agent-task-events'
import { useAgentTask } from './useAgentTask'

let node = 'one'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => '/n/' + node + '/api' + path }))
afterEach(() => { cleanup(); clearAgentDataCache(); vi.useRealTimers(); vi.resetAllMocks(); node = 'one' })
const reply = (state: string) => ({ task: { id: 't', state }, attempts: [], children: [] })
function serve(state: () => string, resources: any[] = []) {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.endsWith('/resources') ? { resources, actions: [] } : path.startsWith('/agent/artifacts') ? [] : reply(state()) }))
}

it.each(['succeeded', 'failed', 'cancelled', 'interrupted'])('does not poll any endpoint for an ended %s task, including unresolved resources', async state => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  serve(() => state, [{ state: 'quarantined', controlReleased: false }])
  const hook = renderHook(() => useAgentTask('t'))
  await act(async () => {})
  await waitFor(() => expect(hook.result.current.controls.value).toBeTruthy())
  expect(api).toHaveBeenCalledTimes(3)
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(api).toHaveBeenCalledTimes(3)
})

it('stops polling as soon as the active task finishes', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  let state = 'running'; serve(() => state)
  const hook = renderHook(() => useAgentTask('t'))
  await act(async () => {})
  await waitFor(() => expect(hook.result.current.detail.value?.task.state).toBe('running'))
  state = 'succeeded'
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(hook.result.current.detail.value?.task.state).toBe('succeeded')
  const calls = vi.mocked(api).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(api).toHaveBeenCalledTimes(calls)
})

it('refreshes ended tasks on scoped lifecycle events and resumes polling after a continuation', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  let state = 'succeeded'; serve(() => state)
  const hook = renderHook(() => useAgentTask('t'))
  await act(async () => {})
  await waitFor(() => expect(hook.result.current.detail.value?.task.state).toBe('succeeded'))
  await act(async () => publishTaskEvent({ id: 2, kind: 'task.steered', payload: { taskId: 'other' } }))
  expect(api).toHaveBeenCalledTimes(3)
  state = 'running'
  await act(async () => publishTaskEvent({ id: 3, kind: 'task.steered', payload: { taskId: 't' } }))
  await waitFor(() => expect(hook.result.current.detail.value?.task.state).toBe('running'))
  expect(api).toHaveBeenCalledTimes(6)
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(api).toHaveBeenCalledTimes(9)
})

it('shares reads between concurrent task consumers and skips failed refresh ticks', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  vi.mocked(api).mockRejectedValue(new Error('offline'))
  const hook = renderHook(() => [useAgentTask('t'), useAgentTask('t')])
  await act(async () => {})
  await waitFor(() => expect(hook.result.current.every(value => value.detail.failed)).toBe(true))
  expect(api).toHaveBeenCalledTimes(3)
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(api).toHaveBeenCalledTimes(3)
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(api).toHaveBeenCalledTimes(6)
  await act(async () => { await vi.advanceTimersByTimeAsync(9000) })
  expect(api).toHaveBeenCalledTimes(6)
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(api).toHaveBeenCalledTimes(9)
})

it('cannot refresh the same task ID on another node through an old scoped listener', async () => {
  serve(() => 'succeeded')
  const hook = renderHook(() => useAgentTask('t'))
  await act(async () => {})
  await waitFor(() => expect(hook.result.current.detail.value).toBeTruthy())
  node = 'two'
  await act(async () => publishTaskEvent({ id: 3, kind: 'task.steered', payload: { taskId: 't' } }))
  expect(api).toHaveBeenCalledTimes(3)
  hook.rerender()
  await waitFor(() => expect(hook.result.current.controls.version).toBe(0))
  expect(api).toHaveBeenCalledTimes(6)
})
