// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentThread } from './useAgentThread'
import { agentDataKey, clearAgentDataCache, peekAgentData, storeAgentData } from './agent-data-cache'
import { api, openEventStream } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn(), openEventStream: vi.fn() }))
afterEach(() => { clearAgentDataCache(); vi.restoreAllMocks(); vi.resetAllMocks() })
const snapshot = (id: string) => ({ conversation: { id, title: id, active_branch_id: id }, branchId: id, messages: [], turns: [], snapshotCursor: 1 })

it('ignores a late snapshot from the previously selected conversation and aborts its stream', async () => {
  let finishOld: (v: any) => void
  const old = new Promise((resolve) => { finishOld = resolve })
  vi.mocked(api).mockImplementation(async (_method, path) => path.includes('/old/') ? old : { data: snapshot('new') })
  const signals: AbortSignal[] = []
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => {
    signals.push(signal)
    return new Response(new ReadableStream({ start(controller) { signal.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true }) } }))
  })
  const hook = renderHook(({ cid }) => useAgentThread(cid), { initialProps: { cid: 'old' } })
  hook.rerender({ cid: 'new' })
  await waitFor(() => expect(hook.result.current.view?.conversation.id).toBe('new'))
  await act(async () => { finishOld!({ data: snapshot('old') }); await old })
  expect(hook.result.current.view?.conversation.id).toBe('new')
  hook.unmount()
  expect(signals.every((signal) => signal.aborted)).toBe(true)
})

it('publishes live tool transitions without waiting for another history response', async () => {
  let stream!: ReadableStreamDefaultController<Uint8Array>
  vi.mocked(api).mockResolvedValue({ data: snapshot('live') })
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => new Response(new ReadableStream({
    start(controller) { stream = controller; signal.addEventListener('abort', () => controller.close(), { once: true }) },
  })))
  const hook = renderHook(() => useAgentThread('live'))
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  const reads = vi.mocked(api).mock.calls.length
  const item = { id: 'tool:one', kind: 'tool', name: 'shell', anchorMessageId: 'm', state: 'running', startedMs: 1000, updatedMs: 1000 }
  const send = async (id: number, state: string) => {
    await act(async () => stream.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ id, branchId: 'live', kind: 'tool.' + (state === 'running' ? 'started' : 'completed'), payload: { activity: { ...item, state } } }) + '\n\n')))
    await waitFor(() => expect(hook.result.current.view?.activities?.[0].state).toBe(state))
  }
  await send(2, 'running')
  await send(3, 'failed')
  expect(hook.result.current.view?.activities).toHaveLength(1)
  expect(vi.mocked(api).mock.calls.length).toBe(reads)
  hook.unmount()
})

it('renders warm history immediately and replays missed stream events from its cursor', async () => {
  storeAgentData(agentDataKey('/agent/conversations/warm/messages'), snapshot('warm'))
  let stream!: ReadableStreamDefaultController<Uint8Array>
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => new Response(new ReadableStream({
    start(controller) { stream = controller; signal.addEventListener('abort', () => controller.close(), { once: true }) },
  })))
  const hook = renderHook(() => useAgentThread('warm'))
  expect(hook.result.current.view?.conversation.id).toBe('warm')
  expect(hook.result.current.loading).toBe(false)
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  expect(openEventStream).toHaveBeenLastCalledWith('/agent/conversations/warm/events?after=1', expect.anything())
  expect(api).not.toHaveBeenCalled()
  await act(async () => stream.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ id: 2, branchId: 'warm', kind: 'message.started', payload: { messageId: 'new-message', turnId: 'turn' } }) + '\n\n')))
  await waitFor(() => expect(hook.result.current.view?.messages[0].id).toBe('new-message'))
  hook.unmount()
  expect(peekAgentData<any>(agentDataKey('/agent/conversations/warm/messages'))?.snapshotCursor).toBe(2)
})
