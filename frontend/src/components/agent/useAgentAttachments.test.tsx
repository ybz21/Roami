// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentAttachments } from './useAgentAttachments'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => '/api' + path }))
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const response = (name: string) => ({ ok: true, json: async () => ({ data: { id: name, name, sizeBytes: 3, mimeType: 'text/plain', metadata: { preview: { state: 'text' } } } }) })

it('keeps late uploads with their original conversation under StrictMode', async () => {
  let finish!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
  const view = renderHook(({ scope }) => useAgentAttachments(scope), { initialProps: { scope: 'first' }, wrapper: StrictMode })
  let pending!: Promise<boolean>
  act(() => { pending = view.result.current.add([new File(['one'], 'one.txt')]) })
  expect(view.result.current.blocked).toBe(true)
  view.rerender({ scope: 'second' })
  await act(async () => { finish(response('one.txt')); await pending })
  expect(view.result.current.items).toHaveLength(0)
  view.rerender({ scope: 'first' })
  expect(view.result.current.ids).toEqual(['one.txt'])
  expect(view.result.current.blocked).toBe(false)
  expect(view.result.current.items[0].file).toBeUndefined()
  expect(JSON.parse(localStorage.getItem('roami.agent.attachments.first')!)[0].reference.id).toBe('one.txt')
})

it('reserves slots before concurrent batches finish and rejects oversize files', async () => {
  const fetch = vi.fn(async (_url: string, options: { body: File }) => response(options.body.name))
  vi.stubGlobal('fetch', fetch)
  const view = renderHook(() => useAgentAttachments('limits'))
  let first!: Promise<boolean>, second!: Promise<boolean>
  act(() => {
    first = view.result.current.add(Array.from({ length: 4 }, (_, i) => new File(['x'], i + '.txt')))
    second = view.result.current.add(Array.from({ length: 3 }, (_, i) => new File(['x'], 'next-' + i + '.txt')))
  })
  await act(async () => { expect(await first).toBe(true); expect(await second).toBe(false) })
  expect(fetch).toHaveBeenCalledTimes(4)
  expect(view.result.current.items).toHaveLength(4)
  await act(async () => { expect(await view.result.current.add([new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'large.bin')])).toBe(false) })
  expect(fetch).toHaveBeenCalledTimes(4)
})

it('retries a failed upload with the same request key without submitting a message', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(Error('offline')).mockResolvedValueOnce(response('retry.txt'))
  vi.stubGlobal('fetch', fetch)
  const view = renderHook(() => useAgentAttachments('retry'))
  await act(async () => { await view.result.current.add([new File(['abc'], 'retry.txt')]) })
  expect(view.result.current.items[0].state).toBe('failed')
  expect(localStorage.getItem('roami.agent.attachments.retry')).toBeNull()
  await act(async () => { await view.result.current.retry(view.result.current.items[0]) })
  await waitFor(() => expect(view.result.current.items[0].state).toBe('ready'))
  expect(fetch.mock.calls[0][0]).toEqual(fetch.mock.calls[1][0])
  expect(String(fetch.mock.calls[0][0])).toContain('/agent/attachments?')
})


it('moves an unfinished new-chat upload into its created conversation', async () => {
  let finish!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
  const view = renderHook(({ scope }) => useAgentAttachments(scope), { initialProps: { scope: 'new' } })
  let pending!: Promise<boolean>
  act(() => { pending = view.result.current.add([new File(['one'], 'one.txt')]) })
  act(() => { view.result.current.transfer('created') })
  view.rerender({ scope: 'created' })
  expect(view.result.current.items[0].state).toBe('uploading')
  await act(async () => { finish(response('one.txt')); await pending })
  expect(view.result.current.ids).toEqual(['one.txt'])
  view.rerender({ scope: 'new' })
  expect(view.result.current.items).toHaveLength(0)
})
