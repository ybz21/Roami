// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkspaceStateProvider } from '../../view-state'
import { hasNativeFinal, useTranscript } from './useTranscript'

const state = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => state.api(...args) }))
afterEach(() => { cleanup(); vi.useRealTimers(); state.api.mockReset() })

const message = (id: string) => ({ id, role: 'assistant', blocks: [{ kind: 'text', text: id }] })

it.each(['transcript', 'codex-transcript', 'pi-transcript', 'opencode-transcript'])(
  'renders a discovered %s first page without another poll', async (path) => {
    state.api.mockResolvedValue({ data: {
      file: '/history/conversation.jsonl', nextOffset: 120, messages: [message('existing-history')],
      status: { model: 'fixture' }, truncated: true,
    } })
    const hook = renderHook(() => useTranscript('session', undefined, path, 60_000))
    await waitFor(() => expect(hook.result.current.msgs.map(m => m.id)).toEqual(['existing-history']))
    expect(hook.result.current.status.model).toBe('fixture')
    expect(hook.result.current.hasEarlier).toBe(true)
    expect(state.api).toHaveBeenCalledTimes(1)
  },
)

it('uses the discovered cursor on the next poll without duplicating history', async () => {
  vi.useFakeTimers()
  state.api.mockResolvedValueOnce({ data: {
    file: '/history/conversation.jsonl', nextOffset: 120, messages: [message('first')],
  } }).mockResolvedValue({ data: {
    file: '/history/conversation.jsonl', nextOffset: 180, messages: [message('next')],
  } })
  const hook = renderHook(() => useTranscript('session', undefined, 'transcript'))
  await act(async () => {})
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['first'])
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  const query = new URL('http://fixture' + state.api.mock.calls[1][1]).searchParams
  expect(query.get('offset')).toBe('120')
  expect(query.get('file')).toBe('/history/conversation.jsonl')
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['first', 'next'])
})

it('refetches a replacement file without applying the previous file cursor', async () => {
  vi.useFakeTimers()
  state.api.mockResolvedValueOnce({ data: {
    file: '/history/old.jsonl', nextOffset: 120, messages: [message('old')],
  } }).mockResolvedValueOnce({ data: {
    file: '/history/new.jsonl', nextOffset: 180, messages: [message('partial-new')],
  } }).mockResolvedValue({ data: {
    file: '/history/new.jsonl', nextOffset: 240, messages: [message('complete-new')],
  } })
  const hook = renderHook(() => useTranscript('session', '/history/old.jsonl', 'transcript'))
  await act(async () => {})
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  expect(hook.result.current.msgs).toEqual([])
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  const query = new URL('http://fixture' + state.api.mock.calls[2][1]).searchParams
  expect(query.get('offset')).toBe('0')
  expect(query.get('file')).toBe('/history/new.jsonl')
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['complete-new'])
})

it('prepends fixed older pages while retaining the newest incremental cursor', async () => {
  vi.useFakeTimers()
  const file = '/history/conversation.jsonl'
  state.api.mockResolvedValueOnce({ data: {
    file, nextOffset: 1000, before: 500, truncated: true, messages: [message('latest')],
  } }).mockResolvedValueOnce({ data: {
    file, nextOffset: 500, before: 0, truncated: false, messages: [message('older')],
  } }).mockResolvedValue({ data: {
    file, nextOffset: 1100, before: 1000, truncated: false, messages: [message('new')],
  } })
  const hook = renderHook(() => useTranscript('session', undefined, 'transcript'))
  await act(async () => {})
  const first = new URL('http://fixture' + state.api.mock.calls[0][1]).searchParams
  expect(first.get('tail')).toBe('50')
  await act(async () => { hook.result.current.loadEarlier() })
  const older = new URL('http://fixture' + state.api.mock.calls[1][1]).searchParams
  expect(older.get('before')).toBe('500')
  expect(older.get('tail')).toBe('50')
  expect(older.has('offset')).toBe(false)
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['older', 'latest'])
  expect(hook.result.current.hasEarlier).toBe(false)
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  const incremental = new URL('http://fixture' + state.api.mock.calls[2][1]).searchParams
  expect(incremental.get('offset')).toBe('1000')
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['older', 'latest', 'new'])
})

it('keeps earlier history available after an empty incremental poll', async () => {
  vi.useFakeTimers()
  const file = '/history/conversation.jsonl'
  state.api.mockResolvedValueOnce({ data: {
    file, nextOffset: 1000, before: 500, truncated: true, messages: [message('latest')],
  } }).mockResolvedValue({ data: {
    file, nextOffset: 1000, before: 0, truncated: false, messages: [],
  } })
  const hook = renderHook(() => useTranscript('session', undefined, 'transcript'))
  await act(async () => {})
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  expect(hook.result.current.hasEarlier).toBe(true)
})

it('retains loaded history and retries the same older cursor after a failure', async () => {
  vi.useFakeTimers()
  const file = '/history/conversation.jsonl'
  state.api.mockResolvedValueOnce({ data: {
    file, nextOffset: 1000, before: 500, truncated: true, messages: [message('latest')],
  } }).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: {
    file, nextOffset: 500, before: 0, truncated: false, messages: [message('older')],
  } })
  const hook = renderHook(() => useTranscript('session', undefined, 'transcript'))
  await act(async () => {})
  await act(async () => { hook.result.current.loadEarlier() })
  expect(hook.result.current.err).toBe('offline')
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['latest'])
  await act(async () => { hook.result.current.loadEarlier() })
  expect(state.api.mock.calls[2][1]).toBe(state.api.mock.calls[1][1])
  expect(hook.result.current.err).toBe('')
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['older', 'latest'])
})

it('only replaces live output once the current turn has a native final reply', () => {
  const startedMs = Date.parse('2026-11-20T09:00:00Z')
  const old = { ...message('old'), final: true, ts: '2026-11-20T08:59:59Z' }
  const interim = { ...message('interim'), ts: '2026-11-20T09:00:01Z' }
  expect(hasNativeFinal([old], startedMs)).toBe(false)
  expect(hasNativeFinal([old, interim], startedMs)).toBe(false)
  const final = { ...interim, final: true }
  expect(hasNativeFinal([old, final])).toBe(false)
  expect(hasNativeFinal([old, final], startedMs)).toBe(true)
})

it('backs off and resumes the same cursor for two visible views of one conversation', async () => {
  vi.useFakeTimers()
  const file = '/history/conversation.jsonl'
  state.api.mockResolvedValueOnce({ data: { file, nextOffset: 120, messages: [message('one')] } })
    .mockResolvedValue({ data: { file, nextOffset: 120, messages: [] } })
  const hook = renderHook(({ active }) => ({
    workbench: useTranscript('session', undefined, 'transcript', { active, source: file, identity: 'current' }),
    project: useTranscript('session', undefined, 'transcript', { active, identity: 'current' }),
  }), { initialProps: { active: true }, wrapper: WorkspaceStateProvider })
  await act(async () => {})
  expect(state.api).toHaveBeenCalledTimes(1)
  expect(hook.result.current.workbench.msgs).toBe(hook.result.current.project.msgs)
  await act(async () => { await vi.advanceTimersByTimeAsync(4500) })
  expect(state.api).toHaveBeenCalledTimes(4)
  await act(async () => { await vi.advanceTimersByTimeAsync(9500) })
  expect(state.api).toHaveBeenCalledTimes(4)
  hook.rerender({ active: false })
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
  expect(state.api).toHaveBeenCalledTimes(4)
  hook.rerender({ active: true })
  await act(async () => {})
  expect(state.api).toHaveBeenCalledTimes(5)
  const query = new URL('http://fixture' + state.api.mock.calls[4][1]).searchParams
  expect(query.get('offset')).toBe('120')
  expect(query.has('file')).toBe(false)
  expect(hook.result.current.workbench.msgs.map(msg => msg.id)).toEqual(['one'])
})

it('does not show cached messages after the same session name is reused', async () => {
  vi.useFakeTimers()
  state.api.mockResolvedValueOnce({ data: { file: '/history/old.jsonl', nextOffset: 120, messages: [message('old')] } })
    .mockImplementationOnce(() => new Promise(() => {}))
  const view = renderHook(({ identity }) => useTranscript('session', undefined, 'transcript', { identity }), {
    initialProps: { identity: 'original' }, wrapper: WorkspaceStateProvider,
  })
  await act(async () => {})
  expect(view.result.current.msgs.map(msg => msg.id)).toEqual(['old'])
  view.rerender({ identity: 'replacement' })
  expect(view.result.current.msgs).toEqual([])
  expect(state.api.mock.calls[1][1]).toContain('offset=0')
})
