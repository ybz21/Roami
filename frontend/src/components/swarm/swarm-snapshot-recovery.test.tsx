// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useSwarmSnapshot } from './useSwarmSnapshot'

const test = vi.hoisted(() => ({ api: vi.fn(), stream: vi.fn() }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => test.api(...args), openEventStream: (...args: unknown[]) => test.stream(...args), agentEvents: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path }))
const id = 'sw-' + 'a'.repeat(32)
beforeEach(() => { test.api.mockReset(); test.stream.mockReset(); Object.defineProperty(document, 'hidden', { configurable: true, value: false }); vi.useFakeTimers() })
afterEach(() => { cleanup(); vi.useRealTimers() })
it('does not query or reconnect a legacy team name', async () => {
  const { result } = renderHook(() => useSwarmSnapshot('old-team-name'))
  await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
  expect(result.current.missing).toBe(true)
  expect(test.api).not.toHaveBeenCalled()
  expect(test.stream).not.toHaveBeenCalled()
})
it('stops automatic retries for a missing managed team and permits explicit recovery', async () => {
  test.api.mockRejectedValueOnce(Object.assign(new Error('SWARM_NOT_FOUND'), { status: 404 }))
  const { result } = renderHook(() => useSwarmSnapshot(id))
  await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
  expect(result.current.missing).toBe(true)
  expect(test.api).toHaveBeenCalledTimes(1)
  expect(test.stream).not.toHaveBeenCalled()
  test.api.mockResolvedValueOnce({ data: { id, sequence: 1 } })
  await act(async () => { await result.current.refresh() })
  expect(result.current.missing).toBe(false)
  expect(result.current.data?.id).toBe(id)
})
