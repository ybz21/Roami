// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentThread } from './useAgentThread'
import { api, openEventStream } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn(), openEventStream: vi.fn() }))
afterEach(() => vi.restoreAllMocks())
const snapshot = (id: string) => ({ conversation: { id, title: id, active_branch_id: id }, branchId: id, messages: [], turns: [], snapshotCursor: 1 })

it('ignores a late snapshot from the previously selected conversation and aborts its stream', async () => {
  let finishOld: (v: any) => void
  const old = new Promise((resolve) => { finishOld = resolve })
  vi.mocked(api).mockImplementation(async (_method, path) => path.includes('/old/') ? old : { data: snapshot('new') })
  const signals: AbortSignal[] = []
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => {
    signals.push(signal)
    return new Response(new ReadableStream({ start(controller) { signal.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true }) } }))
  })
  const hook = renderHook(({ cid }) => useAgentThread(cid), { initialProps: { cid: 'old' } })
  hook.rerender({ cid: 'new' })
  await waitFor(() => expect(hook.result.current.view?.conversation.id).toBe('new'))
  await act(async () => { finishOld!({ data: snapshot('old') }); await old })
  expect(hook.result.current.view?.conversation.id).toBe('new')
  hook.unmount()
  expect(signals.every((signal) => signal.aborted)).toBe(true)
})
