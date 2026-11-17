import { afterEach, expect, it, vi } from 'vitest'
import { setUnauthorizedHandler, streamMarketPreview } from './api'

afterEach(() => { vi.unstubAllGlobals(); setUnauthorizedHandler(() => {}) })
const payload = { source: 'skills-sh', id: 'owner/repo/workflow', version: '' }

it('decodes fragmented UTF-8 modules and accepts the final receipt only at ready', async () => {
  const events = [{ type: 'document', entry: { text: '说明' } }, { type: 'files', entry: { files: {} } }, { type: 'ready', data: { previewId: 'pinned' } }]
  const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event)).join('\n'))
  const stream = new ReadableStream({ start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close() } })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, { headers: { 'Content-Type': 'application/x-ndjson' } })))
  const received: any[] = []
  await streamMarketPreview(payload, event => received.push(event), new AbortController().signal)
  expect(received).toEqual(events)
})

it('preserves already delivered modules when the stream ends with an error', async () => {
  const document = { type: 'document', entry: { text: 'Instructions' } }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(document) + '\n' + JSON.stringify({ type: 'error', error: { code: 'MARKET_UNAVAILABLE' } }) + '\n', { headers: { 'Content-Type': 'application/x-ndjson' } })))
  const received: any[] = []
  await expect(streamMarketPreview(payload, event => received.push(event), new AbortController().signal)).rejects.toMatchObject({ apiError: { code: 'MARKET_UNAVAILABLE' } })
  expect(received).toEqual([document])
})

it('rejects an interrupted stream without an installation receipt', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"type":"loading"}\n', { headers: { 'Content-Type': 'application/x-ndjson' } })))
  await expect(streamMarketPreview(payload, () => {}, new AbortController().signal)).rejects.toThrow('MARKET_UNAVAILABLE')
})

it('accepts complete multi-megabyte file and receipt frames in one network chunk', async () => {
  const entry = { files: { 'data/catalog.csv': 'eA=='.repeat(2_600_000) } }
  const events = [{ type: 'files', entry }, { type: 'ready', data: { previewId: 'large', options: [{ entry }] } }]
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(events.map(event => JSON.stringify(event)).join('\n') + '\n', { headers: { 'Content-Type': 'application/x-ndjson' } })))
  const received: any[] = []
  await streamMarketPreview(payload, event => received.push(event), new AbortController().signal)
  expect(received).toEqual(events)
})

it.each([true, false])('rejects an oversized frame with or without a newline (%s)', async newline => {
  const frame = JSON.stringify({ type: 'files', entry: { files: { 'data.csv': 'x'.repeat(12_000_001) } } })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(frame + (newline ? '\n' : ''), { headers: { 'Content-Type': 'application/x-ndjson' } })))
  await expect(streamMarketPreview(payload, () => {}, new AbortController().signal)).rejects.toThrow('MARKET_PACKAGE_TOO_LARGE')
})

it('supports JSON responses from an older node and preserves login handling', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ data: { previewId: 'compatible' } }), { headers: { 'Content-Type': 'application/json' } })).mockResolvedValueOnce(new Response('', { status: 401 }))
  vi.stubGlobal('fetch', fetch)
  const event = vi.fn(), unauthorized = vi.fn()
  await streamMarketPreview(payload, event, new AbortController().signal)
  expect(event).toHaveBeenCalledWith({ type: 'ready', data: { previewId: 'compatible' } })
  setUnauthorizedHandler(unauthorized)
  await expect(streamMarketPreview(payload, event, new AbortController().signal)).rejects.toThrow('UNAUTHORIZED')
  expect(unauthorized).toHaveBeenCalledOnce()
})
