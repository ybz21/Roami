// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentAttachments } from './useAgentAttachments'
import { prepareImageUpload } from './image-upload'
vi.mock('./image-upload', async importOriginal => ({ ...await importOriginal<typeof import('./image-upload')>(), prepareImageUpload: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path }))
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.mocked(prepareImageUpload).mockReset() })
it('retries the exact optimized file and request key after a lost upload response', async () => {
  const original = new File(['source'], 'camera.png', { type: 'image/png' }), prepared = new File(['compressed'], 'camera.jpg', { type: 'image/jpeg' })
  vi.mocked(prepareImageUpload).mockResolvedValue(prepared)
  const fetch = vi.fn().mockRejectedValueOnce(Error('network')).mockResolvedValueOnce({ ok: true, json: async () => ({ data: { id: 'fixture', name: 'camera.jpg', sizeBytes: 10, mimeType: 'image/jpeg', metadata: { preview: { state: 'image' } } } }) })
  vi.stubGlobal('fetch', fetch)
  const { result } = renderHook(() => useAgentAttachments('test'))
  await act(async () => { await result.current.add([original]) })
  expect(result.current.items[0].state).toBe('failed')
  await act(async () => { await result.current.retry(result.current.items[0]) })
  expect(result.current.items[0].state).toBe('ready')
  expect(prepareImageUpload).toHaveBeenCalledOnce()
  expect(fetch.mock.calls[0][0]).toBe(fetch.mock.calls[1][0])
  expect(fetch.mock.calls[0][1].body).toBe(prepared); expect(fetch.mock.calls[1][1].body).toBe(prepared)
})
it('serializes image decoding while uploading only prepared files', async () => {
  let running = 0, maximum = 0
  vi.mocked(prepareImageUpload).mockImplementation(async file => { running++; maximum = Math.max(maximum, running); await new Promise(resolve => setTimeout(resolve, 5)); running--; return file })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: { id: crypto.randomUUID(), name: 'fixture', sizeBytes: 1, mimeType: 'image/png', metadata: { preview: { state: 'image' } } } }) }))
  const { result } = renderHook(() => useAgentAttachments('serial'))
  await act(async () => { await result.current.add([new File(['a'], 'a.png'), new File(['b'], 'b.png')]) })
  expect(maximum).toBe(1); expect(result.current.items).toHaveLength(2); expect(result.current.items.every(item => item.state === 'ready')).toBe(true)
})
