// @vitest-environment jsdom
import { useRef, useState } from 'react'
import { act, cleanup, fireEvent, render, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api, openEventStream } from '../../api'
import { clearAgentDataCache } from './agent-data-cache'
import { usePagedAgentData } from './usePagedAgentData'
import { useBoundaryLoad } from './useBoundaryLoad'
import { useAgentThread } from './useAgentThread'
import { projectAgentEvent } from './agent-protocol'
vi.mock('../../api', () => ({ api: vi.fn(), openEventStream: vi.fn() }))
afterEach(() => { cleanup(); clearAgentDataCache(); vi.resetAllMocks(); vi.restoreAllMocks() })

it('reads one page, deduplicates concurrent next-page requests and does not drain a short page', async () => {
  let finish!: (value: any) => void
  const next = new Promise(resolve => { finish = resolve })
  vi.mocked(api).mockImplementation(async (_method, path) => path.includes('before=') ? next : { data: { items: [{ id: 'first' }], nextCursor: 'next' } })
  const hook = renderHook(() => usePagedAgentData<{ id: string }>('/items?limit=20'))
  await waitFor(() => expect(hook.result.current.items).toHaveLength(1))
  expect(api).toHaveBeenCalledTimes(1)
  let pending!: Promise<void>
  act(() => { pending = hook.result.current.loadMore(); void hook.result.current.loadMore() })
  expect(api).toHaveBeenCalledTimes(2)
  await act(async () => { finish({ data: { items: [{ id: 'first' }, { id: 'second' }], nextCursor: 'later' } }); await pending })
  expect(hook.result.current.items.map(item => item.id)).toEqual(['first', 'second'])
  expect(hook.result.current.hasMore).toBe(true)
  expect(api).toHaveBeenCalledTimes(2)
})

it('rejects a late page after switching filters, even when transport ignores cancellation', async () => {
  let finish!: (value: any) => void
  const next = new Promise(resolve => { finish = resolve })
  vi.mocked(api).mockImplementation(async (_method, path) => path.includes('before=') ? next : { data: { items: [{ id: path }], nextCursor: 'cursor' } })
  const hook = renderHook(({ path }) => usePagedAgentData<{ id: string }>(path), { initialProps: { path: '/old' } })
  await waitFor(() => expect(hook.result.current.items[0]?.id).toBe('/old'))
  let pending!: Promise<void>
  act(() => { pending = hook.result.current.loadMore() })
  hook.rerender({ path: '/new' })
  await waitFor(() => expect(hook.result.current.items[0]?.id).toBe('/new'))
  await act(async () => { finish({ data: { items: [{ id: 'private-old' }], nextCursor: null } }); await pending })
  expect(hook.result.current.items.map(item => item.id)).toEqual(['/new'])
})

it('offers retry after a page times out and clears appended rows on explicit refresh', async () => {
  let slow = true
  vi.mocked(api).mockImplementation(async (_method, path, _body, options) => {
    if (!path.includes('before=')) return { data: { items: [{ id: 'first' }], nextCursor: 'cursor' } }
    if (!slow) return { data: { items: [{ id: 'older' }], nextCursor: null } }
    return new Promise((_resolve, reject) => options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
  })
  const hook = renderHook(() => usePagedAgentData<{ id: string }>('/items'))
  await waitFor(() => expect(hook.result.current.items).toHaveLength(1))
  vi.useFakeTimers()
  let pending!: Promise<void>
  act(() => { pending = hook.result.current.loadMore() })
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); await pending })
  expect(hook.result.current.loadingMore).toBe(false)
  expect(hook.result.current.moreFailed).toBe(true)
  vi.useRealTimers(); slow = false
  await act(async () => { await hook.result.current.loadMore() })
  expect(hook.result.current.items.map(item => item.id)).toEqual(['first', 'older'])
  await act(async () => { hook.result.current.refresh() })
  expect(hook.result.current.items.map(item => item.id)).toEqual(['first'])
})

it('loads only after user intent and once per touch gesture, including re-renders after completion', async () => {
  function List() {
    const root = useRef<HTMLDivElement>(null), [pages, setPages] = useState(1)
    useBoundaryLoad(root, () => setPages(value => value + 1), true)
    return <div data-testid="pane" ref={root} style={{ overflowY: 'auto' }}>{pages}</div>
  }
  const page = render(<List />), pane = page.getByTestId('pane')
  expect(pane.textContent).toBe('1')
  fireEvent.scroll(pane)
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(pane.textContent).toBe('1')
  fireEvent.touchStart(pane, { touches: [{ clientX: 0, clientY: 100 }] })
  fireEvent.touchMove(pane, { touches: [{ clientX: 0, clientY: 50 }] })
  await waitFor(() => expect(pane.textContent).toBe('2'))
  fireEvent.touchMove(pane, { touches: [{ clientX: 0, clientY: 10 }] })
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(pane.textContent).toBe('2')
  fireEvent.touchStart(pane, { touches: [{ clientX: 0, clientY: 100 }] })
  fireEvent.touchMove(pane, { touches: [{ clientX: 0, clientY: 50 }] })
  await waitFor(() => expect(pane.textContent).toBe('3'))
})

it('does not carry scroll intent from an in-flight page into programmatic layout changes', async () => {
  const load = vi.fn()
  function List({ enabled }: { enabled: boolean }) {
    const root = useRef<HTMLDivElement>(null)
    useBoundaryLoad(root, load, enabled)
    return <div data-testid="pane" ref={root} style={{ overflowY: 'auto' }} />
  }
  const page = render(<List enabled={false} />), pane = page.getByTestId('pane')
  fireEvent.wheel(pane, { deltaY: 100 })
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)) })
  page.rerender(<List enabled />)
  fireEvent.scroll(pane)
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)) })
  expect(load).not.toHaveBeenCalled()
  fireEvent.wheel(pane, { deltaY: 100 })
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1))
})

it('prepends an older history page without discarding concurrent live messages or moving the stream cursor backwards', async () => {
  let finish!: (value: any) => void, stream!: ReadableStreamDefaultController<Uint8Array>
  const next = new Promise(resolve => { finish = resolve })
  const snapshot = { conversation: { id: 'main', active_branch_id: 'branch' }, branchId: 'branch', messages: [{ id: 'recent', branch_id: 'branch', seq: 2, role: 'user', status: 'completed', content: { text: 'recent' } }], turns: [], snapshotCursor: 10, page: { hasMore: true, olderCursor: 'recent' } }
  vi.mocked(api).mockImplementation(async (_method, path) => path.includes('before=') ? next : { data: snapshot })
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => new Response(new ReadableStream({ start(controller) { stream = controller; signal.addEventListener('abort', () => controller.close(), { once: true }) } })))
  const hook = renderHook(() => useAgentThread('main'))
  await waitFor(() => expect(hook.result.current.connected).toBe(true))
  let pending!: Promise<void>
  act(() => { pending = hook.result.current.loadOlder(); void hook.result.current.loadOlder() })
  await act(async () => stream.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ id: 11, kind: 'message.started', payload: { messageId: 'live', turnId: 'turn' } }) + '\n\n')))
  await act(async () => { finish({ data: { ...snapshot, messages: [{ ...snapshot.messages[0], id: 'old', seq: 1 }], snapshotCursor: 3, page: { hasMore: false, olderCursor: null } } }); await pending })
  expect(hook.result.current.view?.messages.map(m => m.id)).toEqual(['old', 'recent', 'live'])
  expect(hook.result.current.view?.snapshotCursor).toBe(11)
  expect(vi.mocked(api).mock.calls.filter(call => call[1].includes('before='))).toHaveLength(1)
  expect(hook.result.current.view?.page?.hasMore).toBe(false)
  snapshot.snapshotCursor = 12
  await act(async () => stream.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ id: 12, kind: 'memory.forgotten', payload: { memoryId: 'forgotten' } }) + '\n\n')))
  await waitFor(() => expect(hook.result.current.view?.messages.map(m => m.id)).toEqual(['recent']))
})

it('tracks live offsets after a compact long message without reloading the full history for every delta', () => {
  const view: any = { branchId: 'b', snapshotCursor: 1, turns: [], messages: [{ id: 'm', contentTruncated: true, contentOffset: 10000, content: { text: 'preview' } }] }
  const projected = projectAgentEvent(view, { id: 2, kind: 'message.delta', payload: { messageId: 'm', offset: 10000, text: 'next' } })
  expect(projected.reload).toBe(false)
  expect(projected.view.messages[0].content.text).toBe('preview')
  expect(projected.view.messages[0].contentOffset).toBe(10004)
})
