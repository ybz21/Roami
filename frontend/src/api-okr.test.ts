import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
vi.mock('./components/cluster/node-url', () => ({ nodeApi: (path: string) => '/api' + path }))
afterEach(() => vi.unstubAllGlobals())
it('exposes HTTP conflict status for retained OKR drafts with existing string errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'OKR_CONFLICT' }), { status: 409, headers: { 'Content-Type': 'application/json' } })))
  await expect(api('PUT', '/projects/p/okr', { revision: 2 })).rejects.toMatchObject({ status: 409, message: 'OKR_CONFLICT' })
})
it('retains structured API errors for existing consumers', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'FAILED', message: 'Original message' } }), { status: 400, headers: { 'Content-Type': 'application/json' } })))
  await expect(api('GET', '/projects/p/okr')).rejects.toMatchObject({ status: 400, message: 'Original message', apiError: { code: 'FAILED' } })
})
