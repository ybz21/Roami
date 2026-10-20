// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentOutbox } from './useAgentOutbox'
import { useAgentOutboxDebug } from './agent-outbox-debug'

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })

it('observes an in-flight send without a second sender or draft contents', async () => {
  let finish!: () => void
  const send = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
  const sender = renderHook(() => useAgentOutbox('debug-flight', true, true, send))
  act(() => { sender.result.current.enqueue('private draft body', [{ id: 'private-file', name: 'private-name', sizeBytes: 4, mimeType: 'text/plain' }]) })
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
  sender.unmount()
  const write = vi.spyOn(Storage.prototype, 'setItem')
  const observer = renderHook(() => useAgentOutboxDebug('debug-flight'))
  expect(observer.result.current.items[0]).toMatchObject({ state: 'sending', attachments: 1 })
  expect(JSON.stringify(observer.result.current)).not.toMatch(/private draft|private-file|private-name/)
  expect(write).not.toHaveBeenCalled()
  expect(send).toHaveBeenCalledTimes(1)
  await act(async () => { finish() })
  await waitFor(() => expect(observer.result.current.items).toHaveLength(0))
  expect(observer.result.current.sending).toBe('')
})

it('keeps late send results on their scope and treats stored sends as unconfirmed', async () => {
  let reject!: (error: Error) => void
  const send = vi.fn(() => new Promise<void>((_, fail) => { reject = fail }))
  const sender = renderHook(() => useAgentOutbox('debug-old', true, true, send))
  act(() => { sender.result.current.enqueue('old text', []) })
  await waitFor(() => expect(send).toHaveBeenCalledOnce())
  localStorage.setItem('roami.agent.outbox.debug-new', JSON.stringify({ paused: true, items: [{ id: 'stored', state: 'sending', attachments: [], text: 'new text' }] }))
  const observer = renderHook(({ scope }) => useAgentOutboxDebug(scope), { initialProps: { scope: 'debug-old' } })
  observer.rerender({ scope: 'debug-new' })
  expect(observer.result.current.items[0].state).toBe('unconfirmed')
  expect(observer.result.current.paused).toBe(true)
  await act(async () => { reject(Error('lost receipt')) })
  expect(observer.result.current.items[0].id).toBe('stored')
  observer.rerender({ scope: 'debug-old' })
  expect(observer.result.current.items[0].state).toBe('unconfirmed')
  expect(observer.result.current.sending).toBe('')
  expect(send).toHaveBeenCalledOnce()
})
