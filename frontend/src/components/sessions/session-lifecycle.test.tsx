// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { lifecycleLaunchIntent, submitLifecycle, useSessionLifecycle, type LifecycleOperation } from './session-lifecycle'
import type { Preferences } from '../../preferences'
import { setSessionLabels } from './session-label'

vi.mock('../../api', () => ({ api: vi.fn() }))
const node = vi.hoisted(() => ({ prefix: '/api' }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => node.prefix + path, currentNodeId: () => node.prefix, useCurrentNodeId: () => node.prefix }))
class Events {
  static instances: Events[] = []
  onopen?: () => void
  onmessage?: () => void
  close = vi.fn()
  constructor() { Events.instances.push(this) }
}
const operation = (id = 'test'): LifecycleOperation => ({ operationId: id, resourceId: 'resource-' + id, requestKey: 'request-key', kind: 'create', intent: {}, state: 'queued', stage: 'accepted', revision: 1, cancelRequested: false, receipts: {}, acceptedAt: 1, updatedAt: 1 })
beforeEach(() => { localStorage.clear(); vi.mocked(api).mockReset(); node.prefix = '/api'; Events.instances = []; vi.stubGlobal('EventSource', Events) })
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })

it('deduplicates simultaneous submissions and leaves launch ownership on the server', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api).mockImplementation(() => new Promise(r => { resolve = r }))
  const first = submitLifecycle('create', { dir: '/repo', name: 'one' })
  const second = submitLifecycle('create', { dir: '/repo', name: 'one' })
  expect(first).toBe(second)
  await waitFor(() => expect(api).toHaveBeenCalledOnce())
  resolve({ data: operation('dedup') })
  expect((await first).resourceId).toBe('resource-dedup')
  expect(vi.mocked(api).mock.calls[0][2].requestKey).toMatch(/^[a-f0-9]{32}$/)
  expect(vi.mocked(api).mock.calls.some(([, path]) => path.includes('/send'))).toBe(false)
})

it('looks up a lost acknowledgement using the same request key', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('connection lost')).mockResolvedValueOnce({ data: operation('lost-ack') })
  expect((await submitLifecycle('create', { dir: '/repo', name: 'lost' })).operationId).toBe('lost-ack')
  const key = vi.mocked(api).mock.calls[0][2].requestKey
  expect(vi.mocked(api).mock.calls[1]).toEqual(['GET', '/session-lifecycle/operations?requestKey=' + key])
  expect(localStorage.length).toBe(0)
})

it('preserves request keys across failed acknowledgements without losing concurrent requests', async () => {
  const intent = { dir: '/repo', name: 'offline' }
  vi.mocked(api).mockRejectedValue(new Error('offline'))
  await expect(submitLifecycle('create', intent)).rejects.toThrow('offline')
  const original = vi.mocked(api).mock.calls[0][2].requestKey
  vi.mocked(api).mockResolvedValue({ data: operation('other') })
  await submitLifecycle('create', { dir: '/other', name: 'other' })
  vi.mocked(api).mockResolvedValue({ data: operation('retry') })
  await submitLifecycle('create', intent)
  expect(vi.mocked(api).mock.calls[vi.mocked(api).mock.calls.length - 1]?.[2].requestKey).toBe(original)
  expect(localStorage.length).toBe(0)
})

it('does not open a resource on another node after the response arrives', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api).mockImplementation(() => new Promise(r => { resolve = r }))
  const request = submitLifecycle('create', { dir: '/repo', name: 'node-change' })
  await waitFor(() => expect(api).toHaveBeenCalledOnce())
  node.prefix = '/n/other/api'; resolve({ data: operation('old-node') })
  await expect(request).rejects.toThrow('LIFECYCLE_NODE_CHANGED')
})

it('retains exact user input and explicit permission preferences in the durable launch intent', () => {
  const launch = lifecycleLaunchIntent('codex', { codexCommand: 'codex --sandbox workspace-write' } as Preferences, "keep 'quotes' and $(literal)", 'new', false, (key, vars) => key + JSON.stringify(vars))!
  expect(launch.command).toBe('codex --sandbox workspace-write')
  expect(launch.task).toBe("keep 'quotes' and $(literal)")
  expect(launch.preamble).toContain('{{PATH}}')
  expect(launch.preamble).toContain('{{SESSION}}')
})

it('stops fallback requests for ended operations and resumes from journal events', async () => {
  const ended = { ...operation('ended'), state: 'succeeded' }
  vi.mocked(api).mockResolvedValue({ data: [ended] })
  const view = renderHook(() => useSessionLifecycle())
  await waitFor(() => expect(view.result.current.loaded).toBe(true))
  const before = vi.mocked(api).mock.calls.length
  vi.useFakeTimers()
  await act(async () => { await vi.advanceTimersByTimeAsync(9000) })
  expect(vi.mocked(api).mock.calls).toHaveLength(before)
  await act(async () => { Events.instances[Events.instances.length - 1]?.onmessage?.() })
  expect(vi.mocked(api).mock.calls.length).toBeGreaterThan(before)
})

it('keeps the display name in the durable close record after the live session disappears', async () => {
  setSessionLabels({ 'resource-close': 'Cleanup topic' })
  vi.mocked(api).mockResolvedValue({ data: { ...operation('close'), kind: 'close' } })
  await submitLifecycle('close', { mode: 'keep', sessionIdentity: 'original' }, 'resource-close')
  expect(vi.mocked(api).mock.calls[0][2].intent.name).toBe('Cleanup topic')
  setSessionLabels({})
})
