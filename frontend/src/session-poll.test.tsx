// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { createSessionPoll } from './session-poll'

const machine = vi.hoisted(() => ({ id: null as string | null }))
vi.mock('./api', () => ({ api: vi.fn() }))
vi.mock('./components/cluster/node-url', () => ({
  currentNodeId: () => machine.id,
  useCurrentNodeId: () => machine.id,
}))

let hidden = false
beforeEach(() => {
  vi.useFakeTimers()
  hidden = false; machine.id = null
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.resetAllMocks() })

const poll = () => createSessionPoll<Record<string, string>>('/sessions/agents', 6000, {}, response => response.data)
const advance = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
const visibility = async (value: boolean) => {
  hidden = value
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
}

it('shares one polling loop across consumers and keeps unchanged snapshots stable', async () => {
  vi.mocked(api).mockResolvedValue({ data: { one: 'codex' } })
  const useKinds = poll()
  const first = renderHook(() => useKinds()), second = renderHook(() => useKinds())
  await advance(0)
  expect(api).toHaveBeenCalledTimes(1)
  expect(first.result.current.value).toBe(second.result.current.value)
  const previous = first.result.current
  first.rerender(); second.rerender()
  await advance(6000)
  expect(api).toHaveBeenCalledTimes(2)
  expect(first.result.current).toBe(previous)
  first.unmount()
  await advance(6000)
  expect(api).toHaveBeenCalledTimes(3)
  second.unmount()
  await advance(60_000)
  expect(api).toHaveBeenCalledTimes(3)
})

it('does not request session data before authentication enables the subscription', async () => {
  vi.mocked(api).mockResolvedValue({ data: { one: 'codex' } })
  const useKinds = poll()
  const hook = renderHook(({ enabled }) => useKinds(enabled), { initialProps: { enabled: false } })
  await advance(60_000)
  expect(api).not.toHaveBeenCalled()
  hook.rerender({ enabled: true })
  await advance(0)
  expect(hook.result.current.value.one).toBe('codex')
  hook.rerender({ enabled: false })
  expect(hook.result.current.value).toEqual({})
  await advance(60_000)
  expect(api).toHaveBeenCalledTimes(1)
})

it('aborts hidden requests, ignores late responses, and refreshes immediately on return', async () => {
  let finish!: (value: unknown) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValue({ data: { fresh: 'claude' } })
  const useKinds = poll(), hook = renderHook(() => useKinds())
  const signal = vi.mocked(api).mock.calls[0][3]!.signal!
  await visibility(true)
  expect(signal.aborted).toBe(true)
  await advance(30_000)
  expect(api).toHaveBeenCalledTimes(1)
  await visibility(false)
  expect(hook.result.current.value).toEqual({ fresh: 'claude' })
  await act(async () => { finish({ data: { stale: 'codex' } }) })
  expect(hook.result.current.value).toEqual({ fresh: 'claude' })
})

it('does not overlap a slow request with another polling tick', async () => {
  let finish!: (value: unknown) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValue({ data: { one: 'codex' } })
  const useKinds = poll(), hook = renderHook(() => useKinds())
  await advance(12_000)
  expect(api).toHaveBeenCalledTimes(1)
  await act(async () => { finish({ data: { one: 'codex' } }) })
  await advance(6000)
  expect(api).toHaveBeenCalledTimes(2)
  hook.unmount()
})

it('aborts timed out requests and backs off before retrying', async () => {
  vi.mocked(api).mockImplementationOnce((_method, _path, _body, options) => new Promise((_resolve, reject) => {
    options!.signal!.addEventListener('abort', () => reject(new DOMException('Timed out', 'AbortError')), { once: true })
  })).mockResolvedValue({ data: { recovered: 'codex' } })
  const useKinds = poll(), hook = renderHook(() => useKinds())
  await advance(15_000)
  expect(vi.mocked(api).mock.calls[0][3]!.signal!.aborted).toBe(true)
  await advance(6000)
  expect(api).toHaveBeenCalledTimes(1)
  await advance(6000)
  expect(hook.result.current.value).toEqual({ recovered: 'codex' })
})

it('isolates machine snapshots and cancels the old machine request', async () => {
  let finish!: (value: unknown) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValue({ data: { next: 'pi' } })
  machine.id = 'old'
  const useKinds = poll(), hook = renderHook(() => useKinds())
  const oldSignal = vi.mocked(api).mock.calls[0][3]!.signal!
  machine.id = 'new'; hook.rerender()
  await advance(0)
  expect(oldSignal.aborted).toBe(true)
  expect(hook.result.current.value).toEqual({ next: 'pi' })
  await act(async () => { finish({ data: { old: 'codex' } }) })
  expect(hook.result.current.value).toEqual({ next: 'pi' })
})

it('retains the last snapshot during errors and backs off repeated failures', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { one: 'codex' } }).mockRejectedValue(new Error('offline'))
  const useKinds = poll(), hook = renderHook(() => useKinds())
  await advance(6000)
  expect(hook.result.current.failed).toBe(true)
  expect(hook.result.current.value).toEqual({ one: 'codex' })
  expect(api).toHaveBeenCalledTimes(2)
  await advance(6000)
  expect(api).toHaveBeenCalledTimes(2)
  await advance(6000)
  expect(api).toHaveBeenCalledTimes(3)
  vi.mocked(api).mockResolvedValue({ data: { two: 'claude' } })
  await advance(24_000)
  expect(hook.result.current.failed).toBe(false)
  expect(hook.result.current.value).toEqual({ two: 'claude' })
})
