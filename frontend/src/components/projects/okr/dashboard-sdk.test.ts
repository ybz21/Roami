// @vitest-environment jsdom
import sdk from '../../../../../backend/okr/dashboard-sdk.js?raw'
import { afterEach, expect, it, vi } from 'vitest'

// The same server-embedded SDK runs here, without a second client implementation.
afterEach(() => { window.dispatchEvent(new Event('pagehide')); vi.restoreAllMocks() })
it('accepts only its parent handshake, copies declared data and supports updates and unsubscribe', async () => {
 const frame = document.createElement('iframe'); document.body.append(frame)
 const child = frame.contentWindow!
 new Function('window', 'document', 'parent', 'structuredClone', '(' + sdk + ')({nonce:"nonce",digest:"digest",metricIds:["allowed"]})')(child, child.document, window, structuredClone)
 type Dataset = { latest: { value: number | null } }
 const api = (child as unknown as { okr: { ready: () => Promise<unknown>; data: { read: (id: string) => Promise<Dataset>; subscribe: (id: string, callback: (data: Dataset) => void) => () => void; ids: string[] } } }).okr
 const port = { onmessage: null as null | ((event: { data: object }) => void), start: vi.fn(), postMessage: vi.fn(), close: vi.fn() }
 const handshake = (nonce: string, source: Window) => child.dispatchEvent(new MessageEvent('message', { source, data: { type: 'okr:init', nonce, digest: 'digest' }, ports: [port as unknown as MessagePort] }))
 handshake('bad', window); expect(port.start).not.toHaveBeenCalled()
 handshake('nonce', child); expect(port.start).not.toHaveBeenCalled()
 handshake('nonce', window); expect(port.start).toHaveBeenCalledOnce()
 const render = vi.fn(), stop = api.data.subscribe('allowed', render)
 const value = { latest: { value: 0 } }
 const snapshot = { type: 'okr:snapshot', digest: 'digest', context: { locale: 'en-US', theme: 'light', tokens: { '--accent': 'blue' } }, datasets: { allowed: value, forbidden: { secret: true } } }
 port.onmessage!({ data: snapshot }); await api.ready()
 expect(child.document.documentElement.lang).toBe('en-US')
 expect(api.data.ids).toEqual(['allowed'])
 const first = await api.data.read('allowed')
 expect(first.latest.value).toBe(0)
 first.latest.value = 99
 expect((await api.data.read('allowed')).latest.value).toBe(0)
 await expect(api.data.read('forbidden')).rejects.toThrow('DATASET_NOT_ALLOWED')
 expect(render).toHaveBeenCalledOnce()
 stop(); port.onmessage!({ data: { ...snapshot, datasets: { allowed: { latest: { value: 5 } } } } })
 expect(render).toHaveBeenCalledOnce()
 expect((await api.data.read('allowed')).latest.value).toBe(5)
 port.onmessage!({ data: { ...snapshot, digest: 'wrong' } })
 expect((await api.data.read('allowed')).latest.value).toBe(5)
 child.dispatchEvent(new Event('pagehide')); expect(port.close).toHaveBeenCalledOnce()
 frame.remove()
})
it('reports a user-script error that happened before the parent transferred the port', () => {
 const frame = document.createElement('iframe'); document.body.append(frame)
 const child = frame.contentWindow!
 new Function('window', 'document', 'parent', 'structuredClone', '(' + sdk + ')({nonce:"n",digest:"d",metricIds:["allowed"]})')(child, child.document, window, structuredClone)
 child.dispatchEvent(new ErrorEvent('error', { message: 'Broken custom script' }))
 const port = { onmessage: null as null | ((event: { data: object }) => void), start: vi.fn(), postMessage: vi.fn(), close: vi.fn() }
 child.dispatchEvent(new MessageEvent('message', { source: window, data: { type: 'okr:init', nonce: 'n', digest: 'd' }, ports: [port as unknown as MessagePort] }))
 port.onmessage!({ data: { type: 'okr:snapshot', digest: 'd', datasets: { allowed: { latest: { value: 1 } } } } })
 expect(port.postMessage).toHaveBeenCalledWith({ type: 'okr:error', digest: 'd' })
 expect(port.postMessage).not.toHaveBeenCalledWith({ type: 'okr:ready', digest: 'd' })
 child.dispatchEvent(new Event('pagehide')); frame.remove()
})
