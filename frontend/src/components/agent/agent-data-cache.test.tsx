// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { agentCacheEpoch, agentDataKey, clearAgentDataCache, invalidateAgentData, loadAgentData, peekAgentData, storeAgentData } from './agent-data-cache'
import { useAgentData } from './useAgentData'
import { useAgentInbox } from './useAgentInbox'

let node = 'one'
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => '/n/' + node + '/api' + path }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('./AgentChat', () => ({ default: () => null }))
vi.mock('./AgentHomePage', () => ({ default: () => null }))
afterEach(() => { cleanup(); clearAgentDataCache(); vi.restoreAllMocks(); vi.resetAllMocks(); node = 'one' })
const deferred = () => { let resolve!: (value: any) => void; const promise = new Promise(resolveValue => { resolve = resolveValue }); return { promise, resolve } }

it('shares an in-flight prefetch with mounted readers and reuses a fresh response', async () => {
  const response = deferred()
  vi.mocked(api).mockReturnValue(response.promise)
  const preload = loadAgentData('/messages', 5000)
  const hook = renderHook(() => useAgentData<string[]>('/messages', 5000))
  expect(api).toHaveBeenCalledTimes(1)
  await act(async () => { response.resolve({ data: ['history'] }); await preload })
  await waitFor(() => expect(hook.result.current.value).toEqual(['history']))
  expect(await loadAgentData('/messages', 5000)).toEqual(['history'])
  expect(api).toHaveBeenCalledTimes(1)
})

it('shows warm data on the first render while a stale response refreshes in the background', async () => {
  const response = deferred(), key = agentDataKey('/tasks')
  storeAgentData(key, ['old'])
  vi.mocked(api).mockReturnValue(response.promise)
  const hook = renderHook(() => useAgentData<string[]>('/tasks', 0))
  expect(hook.result.current.value).toEqual(['old'])
  expect(hook.result.current.loading).toBe(false)
  await act(async () => { response.resolve({ data: ['new'] }); await response.promise })
  await waitFor(() => expect(hook.result.current.value).toEqual(['new']))
})

it('keeps the last successful data on a failed background refresh', async () => {
  storeAgentData(agentDataKey('/tasks'), ['saved'])
  vi.mocked(api).mockRejectedValue(new Error('offline'))
  const hook = renderHook(() => useAgentData<string[]>('/tasks', 0))
  await waitFor(() => expect(hook.result.current.failed).toBe(true))
  expect(hook.result.current.value).toEqual(['saved'])
})

it('isolates identical conversation IDs across nodes and branches, including the switching frame', async () => {
  storeAgentData(agentDataKey('/messages?branch=main'), ['node one'])
  storeAgentData(agentDataKey('/messages?branch=history'), ['old branch'])
  vi.mocked(api).mockReturnValue(new Promise(() => {}))
  const hook = renderHook(() => useAgentData<string[]>('/messages?branch=main', 5000))
  expect(hook.result.current.value).toEqual(['node one'])
  node = 'two'; hook.rerender()
  expect(hook.result.current.value).toBeUndefined()
  node = 'one'; hook.rerender()
  expect(hook.result.current.value).toEqual(['node one'])
  expect(peekAgentData(agentDataKey('/messages?branch=history'))).toEqual(['old branch'])
})

it('rejects a pre-mutation response even when transport ignores abort', async () => {
  const old = deferred(), fresh = deferred(), key = agentDataKey('/tasks')
  vi.mocked(api).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise)
  const first = loadAgentData('/tasks').catch(() => 'aborted')
  invalidateAgentData(key)
  const second = loadAgentData('/tasks')
  fresh.resolve({ data: ['after mutation'] }); await second
  old.resolve({ data: ['before mutation'] })
  expect(await first).toBe('aborted')
  expect(peekAgentData(key)).toEqual(['after mutation'])
})

it('clears private snapshots on logout and blocks late fetches and stream cleanup from restoring them', async () => {
  const response = deferred(), key = agentDataKey('/messages'), owner = agentCacheEpoch()
  storeAgentData(key, ['private'])
  vi.mocked(api).mockReturnValue(response.promise)
  const pending = loadAgentData('/messages').catch(() => 'aborted')
  clearAgentDataCache()
  response.resolve({ data: ['late private'] })
  expect(await pending).toBe('aborted')
  storeAgentData(key, ['old stream cleanup'], owner)
  expect(peekAgentData(key)).toBeUndefined()
})

it('bounds retained conversations by count and payload size without truncating active results', async () => {
  for (let i = 0; i < 60; i++) storeAgentData('conversation-' + i, { id: i })
  expect(peekAgentData('conversation-0')).toBeUndefined()
  expect(peekAgentData('conversation-59')).toEqual({ id: 59 })
  const large = 'x'.repeat(6 * 1024 * 1024)
  vi.mocked(api).mockResolvedValue({ data: large })
  expect((await loadAgentData<string>('/large')).length).toBe(large.length)
  expect(peekAgentData(agentDataKey('/large'))).toBeUndefined()
  expect(peekAgentData('conversation-59')).toEqual({ id: 59 })
})

it('expires cold snapshots after ten minutes', () => {
  storeAgentData('old', ['history'])
  const now = Date.now()
  vi.spyOn(Date, 'now').mockReturnValue(now + 10 * 60_000 + 1)
  expect(peekAgentData('old')).toBeUndefined()
})

it('removes memory snapshots when authentication becomes unavailable', async () => {
  vi.mocked(api).mockResolvedValue({ data: {} })
  const hook = renderHook(({ enabled }) => useAgentInbox(enabled, 'one'), { initialProps: { enabled: true } })
  await act(async () => {})
  storeAgentData('private-history', ['private'])
  hook.rerender({ enabled: false })
  expect(peekAgentData('private-history')).toBeUndefined()
  expect(hook.result.current.conversations).toEqual([])
  expect(hook.result.current.notices).toEqual([])
})

it('publishes the main conversation and preloads messages/tasks before slow notifications finish', async () => {
  const notices = deferred()
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('/notifications')) return notices.promise
    if (path === '/agent/main-conversation') return { data: { id: 'main', active_branch_id: 'branch' } }
    return { data: [] }
  })
  const hook = renderHook(() => useAgentInbox(true, 'one'))
  await waitFor(() => expect(hook.result.current.conversations[0]?.id).toBe('main'))
  await waitFor(() => expect(api).toHaveBeenCalledWith('GET', '/agent/conversations/main/messages', undefined, expect.anything()))
  expect(api).toHaveBeenCalledWith('GET', '/agent/tasks?conversationId=main', undefined, expect.anything())
  expect(hook.result.current.notices).toEqual([])
  await act(async () => { notices.resolve({ data: { items: [{ id: 1 }], unread: 1 } }); await notices.promise })
  await waitFor(() => expect(hook.result.current.unread).toBe(1))
  act(() => hook.result.current.refresh())
  await waitFor(() => expect(vi.mocked(api).mock.calls.filter(call => call[1].includes('/notifications'))).toHaveLength(2))
  expect(vi.mocked(api).mock.calls.filter(call => call[1] === '/agent/main-conversation')).toHaveLength(1)
})
