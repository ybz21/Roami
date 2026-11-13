// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PageActivityProvider } from '../../page-activity'
import type { ReactNode } from 'react'
import { useAgentThread } from './useAgentThread'
import { agentTimeline } from './agent-timeline'
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

it('publishes live task transitions without waiting for another history response', async () => {
  let stream!: ReadableStreamDefaultController<Uint8Array>
  vi.mocked(api).mockResolvedValue({ data: snapshot('live') })
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => new Response(new ReadableStream({
    start(controller) { stream = controller; signal.addEventListener('abort', () => controller.close(), { once: true }) },
  })))
  const hook = renderHook(() => useAgentThread('live'))
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  const reads = vi.mocked(api).mock.calls.length
  const item = { id: 'task:one', taskId: 'one', kind: 'task', name: 'native', anchorMessageId: 'm', state: 'running', startedMs: 1000, updatedMs: 1000 }
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
  storeAgentData(agentDataKey('/agent/conversations/warm/messages?limit=50'), snapshot('warm'))
  let stream!: ReadableStreamDefaultController<Uint8Array>
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => new Response(new ReadableStream({
    start(controller) { stream = controller; signal.addEventListener('abort', () => controller.close(), { once: true }) },
  })))
  const hook = renderHook(() => useAgentThread('warm'))
  expect(hook.result.current.view?.conversation.id).toBe('warm')
  expect(hook.result.current.loading).toBe(false)
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  expect(openEventStream).toHaveBeenLastCalledWith('/agent/conversations/warm/events?after=1&summaries=true', expect.anything())
  expect(api).not.toHaveBeenCalled()
  await act(async () => stream.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ id: 2, branchId: 'warm', kind: 'message.started', payload: { messageId: 'new-message', turnId: 'turn' } }) + '\n\n')))
  await waitFor(() => expect(hook.result.current.view?.messages[0].id).toBe('new-message'))
  hook.unmount()
  expect(peekAgentData<any>(agentDataKey('/agent/conversations/warm/messages?limit=50'))?.snapshotCursor).toBe(2)
})

it.each([true, false])('keeps an immediate failure visible with a late receipt and failed history GET (assistant started: %s)', async started => {
  let stream!: ReadableStreamDefaultController<Uint8Array>
  vi.mocked(api).mockResolvedValueOnce({ data: snapshot('failed') }).mockRejectedValue(new Error('offline'))
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => new Response(new ReadableStream({
    start(controller) { stream = controller; signal.addEventListener('abort', () => controller.close(), { once: true }) },
  })))
  const hook = renderHook(() => useAgentThread('failed'))
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  await act(async () => {
    for (const event of [
      ...(started ? [{ id: 2, created_ms: 110, kind: 'message.started', payload: { messageId: 'empty', turnId: 'turn' } }] : []),
      { id: 3, created_ms: 120, kind: 'turn.failed', payload: { turnId: 'turn', error: 'MODEL_PROXY_USAGE_UNKNOWN' } },
    ]) stream.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n'))
  })
  await waitFor(() => expect(hook.result.current.view?.activities?.[0]).toMatchObject({ state: 'failed', errorCode: 'MODEL_PROXY_USAGE_UNKNOWN' }))
  act(() => hook.result.current.accepted({ messageId: 'late-user', turnId: 'turn' }, 'Try again', { version: 1, revision: 3, draft: { objective: 'Private editor draft' } }))
  expect(hook.result.current.view?.messages.find(message => message.id === 'late-user')?.content).toEqual({ text: 'Try again', okrContext: { version: 1, revision: 3 } })
  expect(hook.result.current.view?.turns).toEqual([{ id: 'turn', state: 'failed' }])
  expect(hook.result.current.view?.messages.map(message => message.id)).toEqual(started ? ['late-user', 'empty'] : ['late-user'])
  expect(hook.result.current.view?.messages.map(message => message.seq)).toEqual(started ? [1, 2] : [1])
  const view = hook.result.current.view!
  expect(agentTimeline(view.messages, view.activities || []).map(entry => entry.id)).toEqual(['late-user', 'turn:turn'])
  await waitFor(() => expect(vi.mocked(api).mock.calls.length).toBeGreaterThan(1))
  expect(hook.result.current.view?.activities).toHaveLength(1)
  hook.unmount()
})

it('recovers a completed reply after a suspended stream returns to the foreground', async () => {
  let hidden = false
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  const signals: AbortSignal[] = []
  vi.mocked(api).mockResolvedValue({ data: snapshot('resume') })
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => {
    signals.push(signal)
    return new Response(new ReadableStream({ start(controller) { signal.addEventListener('abort', () => controller.close(), { once: true }) } }))
  })
  const hook = renderHook(() => useAgentThread('resume'))
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  hidden = true
  act(() => document.dispatchEvent(new Event('visibilitychange')))
  const completed = { ...snapshot('resume'), snapshotCursor: 4, messages: [{ id: 'answer', branch_id: 'resume', role: 'assistant', status: 'completed', seq: 1, content: { text: 'Delivered while suspended' } }] }
  vi.mocked(api).mockResolvedValue({ data: completed })
  hidden = false
  act(() => document.dispatchEvent(new Event('visibilitychange')))
  await waitFor(() => expect(hook.result.current.view?.messages[0].content.text).toBe('Delivered while suspended'))
  expect(signals[0].aborted).toBe(true)
  await waitFor(() => expect(signals).toHaveLength(2), { timeout: 3500 })
  expect(openEventStream).toHaveBeenLastCalledWith('/agent/conversations/resume/events?after=4&summaries=true', expect.anything())
  hook.unmount()
})

it('keeps loaded history when a retained conversation suspends and resumes its stream', async () => {
  const message = (id: string, seq: number) => ({ id, branch_id: 'retained', role: 'user', status: 'completed', seq, content: { text: id } })
  storeAgentData(agentDataKey('/agent/conversations/retained/messages?limit=50'), { ...snapshot('retained'), messages: [message('latest', 2)], page: { hasMore: true, olderCursor: 'cursor' } })
  vi.mocked(api).mockResolvedValue({ data: { messages: [message('older', 1)], activities: [], page: { hasMore: false, olderCursor: null } } })
  const signals: AbortSignal[] = []
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => {
    signals.push(signal)
    return new Response(new ReadableStream({ start(controller) { signal.addEventListener('abort', () => controller.close(), { once: true }) } }))
  })
  let active = true
  const wrapper = ({ children }: { children: ReactNode }) => <PageActivityProvider active={active}>{children}</PageActivityProvider>
  const hook = renderHook(() => useAgentThread('retained'), { wrapper })
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  await act(async () => hook.result.current.loadOlder())
  expect(hook.result.current.view?.messages.map(item => item.id)).toEqual(['older', 'latest'])
  active = false; hook.rerender()
  expect(signals[0].aborted).toBe(true)
  active = true; hook.rerender()
  await waitFor(() => expect(signals).toHaveLength(2))
  expect(hook.result.current.view?.messages.map(item => item.id)).toEqual(['older', 'latest'])
  expect(hook.result.current.view?.page?.hasMore).toBe(false)
  hook.unmount()
})
