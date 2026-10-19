import { afterEach, expect, it, vi } from 'vitest'
import { hubConfiguration, waitForClusterRecovery } from './cluster-recovery'
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
it('SET-08 rejects unsuccessful hub writes', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({ error: { message: 'SAVE_FAILED' } }) }))
  await expect(hubConfiguration('PUT', { mode: 'hub' })).rejects.toThrow('SAVE_FAILED')
})
it('SET-08 waits for a successful health response', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn().mockResolvedValueOnce({ ok: false }).mockResolvedValueOnce({ ok: true })
  vi.stubGlobal('fetch', fetch)
  const result = waitForClusterRecovery(100, 10)
  await vi.advanceTimersByTimeAsync(20)
  await expect(result).resolves.toBeUndefined()
  expect(fetch).toHaveBeenCalledTimes(2)
})
it('SET-08 reports recovery timeout on repeated HTTP errors', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
  const result = expect(waitForClusterRecovery(30, 10)).rejects.toThrow('CLUSTER_RECOVERY_TIMEOUT')
  await vi.advanceTimersByTimeAsync(30)
  await result
})
