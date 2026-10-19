// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentOutbox } from './useAgentOutbox'
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })
it('persists ordered messages and attachments, waits for idle and sends one at a time', async () => {
  let finish!: () => void
  const send = vi.fn().mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve })).mockResolvedValue(undefined)
  const hook = renderHook(({ idle }) => useAgentOutbox('first', true, idle, send), { initialProps: { idle: false } })
  act(() => { hook.result.current.enqueue('one', [{ id: 'file', name: 'report.txt', sizeBytes: 4, mimeType: 'text/plain' }]); hook.result.current.enqueue('two', []) })
  const firstId = hook.result.current.items[0].id
  expect(send).not.toHaveBeenCalled(); hook.unmount()
  const restored = renderHook(({ idle }) => useAgentOutbox('first', true, idle, send), { initialProps: { idle: true } })
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
  expect(send.mock.calls[0][0]).toMatchObject({ id: firstId, text: 'one', attachments: [{ id: 'file' }] })
  restored.rerender({ idle: false }); await act(async () => { finish() })
  expect(restored.result.current.items.map(item => item.text)).toEqual(['two'])
  expect(send).toHaveBeenCalledTimes(1)
  restored.rerender({ idle: true }); await waitFor(() => expect(restored.result.current.items).toHaveLength(0))
  expect(send.mock.calls.map(([item]) => item.text)).toEqual(['one', 'two'])
})
it('does not silently retry an unknown receipt and reuses the exact request on explicit retry', async () => {
  const send = vi.fn().mockRejectedValueOnce(Error('lost receipt')).mockResolvedValue(undefined)
  const hook = renderHook(() => useAgentOutbox('lost', true, true, send))
  act(() => { hook.result.current.enqueue('original', []) })
  await waitFor(() => expect(hook.result.current.items[0]?.state).toBe('unconfirmed'))
  const id = hook.result.current.items[0].id
  act(() => { hook.result.current.edit(id, 'changed') })
  expect(hook.result.current.items[0].text).toBe('original'); expect(send).toHaveBeenCalledTimes(1)
  hook.unmount()
  const restored = renderHook(() => useAgentOutbox('lost', true, true, send))
  expect(restored.result.current.items[0].state).toBe('unconfirmed')
  act(() => { restored.result.current.retry(id) })
  await waitFor(() => expect(restored.result.current.items).toHaveLength(0))
  expect(send.mock.calls[1][0]).toEqual(send.mock.calls[0][0])
})
it('keeps scopes isolated when an old send completes after switching conversations', async () => {
  let finish!: () => void
  const send = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
  const hook = renderHook(({ scope, ready }) => useAgentOutbox(scope, ready, true, send), { initialProps: { scope: 'old', ready: true } })
  act(() => { hook.result.current.enqueue('old', []) }); await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
  hook.rerender({ scope: 'new', ready: false })
  act(() => { hook.result.current.enqueue('new', []); hook.result.current.pause(true) })
  await act(async () => { finish() })
  expect(hook.result.current.items.map(item => item.text)).toEqual(['new']); expect(hook.result.current.paused).toBe(true)
  expect(localStorage.getItem('roami.agent.outbox.old')).toBeNull()
})
it('allows waiting-message edits and cancellation, and refuses to enqueue when storage fails', () => {
  const hook = renderHook(() => useAgentOutbox('edit', false, false, vi.fn()))
  act(() => { hook.result.current.enqueue('draft', []) }); const id = hook.result.current.items[0].id
  act(() => { hook.result.current.edit(id, 'revised') }); expect(hook.result.current.items[0].text).toBe('revised')
  act(() => { hook.result.current.remove(id) }); expect(hook.result.current.items).toHaveLength(0)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('quota') })
  act(() => { expect(hook.result.current.enqueue('keep draft', [])).toBe(false) })
  expect(hook.result.current.items).toHaveLength(0); expect(hook.result.current.storageFailed).toBe(true)
})
it('shows a reported service failure separately from a missing receipt and blocks automatic retries', async () => {
  const send = vi.fn().mockRejectedValue({ apiError: { code: 'MODEL_NOT_CONFIGURED' } })
  const hook = renderHook(() => useAgentOutbox('rejected', true, true, send))
  act(() => { hook.result.current.enqueue('retry after configuration', []) })
  await waitFor(() => expect(hook.result.current.items[0]?.state).toBe('failed'))
  expect(send).toHaveBeenCalledTimes(1)
})

it('sends only the selected queued intent immediately while Main is busy, retaining other drafts', async () => {
  const send = vi.fn().mockResolvedValue(undefined)
  const hook = renderHook(() => useAgentOutbox('priority', true, false, send))
  act(() => { hook.result.current.enqueue('wait first', []); hook.result.current.enqueue('urgent second', []) })
  const urgent = hook.result.current.items[1]
  expect(send).not.toHaveBeenCalled()
  act(() => hook.result.current.sendNow(urgent.id))
  await waitFor(() => expect(hook.result.current.items.map(item => item.text)).toEqual(['wait first']))
  expect(send).toHaveBeenCalledTimes(1)
  expect(send).toHaveBeenCalledWith(urgent)
})

it('keeps a lost priority-send receipt unconfirmed and never releases the remaining queue automatically', async () => {
  const send = vi.fn().mockRejectedValue(Error('receipt lost'))
  const hook = renderHook(() => useAgentOutbox('priority-lost', true, false, send))
  act(() => { hook.result.current.enqueue('urgent', []); hook.result.current.enqueue('later', []) })
  const id = hook.result.current.items[0].id
  act(() => hook.result.current.sendNow(id))
  await waitFor(() => expect(hook.result.current.items[0].state).toBe('unconfirmed'))
  expect(hook.result.current.items[1].state).toBe('waiting')
  expect(send).toHaveBeenCalledTimes(1)
})
