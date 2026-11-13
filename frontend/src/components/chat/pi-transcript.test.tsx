// @vitest-environment jsdom
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useTranscript } from './useTranscript'

const state = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => state.api(...args) }))
afterEach(cleanup)

it('replaces a Pi branch window and retains it on an unchanged poll', async () => {
  const file = '/pi/original.jsonl'
  const message = (id: string) => ({ id, role: 'assistant', blocks: [{ kind: 'text', text: id }] })
  state.api.mockReset()
    .mockResolvedValueOnce({ data: { file, nextOffset: 100, replace: true, messages: [message('original-branch')] } })
    .mockResolvedValueOnce({ data: { file, nextOffset: 200, replace: true, messages: [message('current-branch')] } })
    .mockResolvedValue({ data: { file, nextOffset: 200, messages: [] } })
  const hook = renderHook(() => useTranscript('original-session', file, 'pi-transcript', 20))
  await waitFor(() => expect(hook.result.current.msgs.map(m => m.id)).toEqual(['current-branch']))
  await waitFor(() => expect(state.api.mock.calls.length).toBeGreaterThanOrEqual(3))
  expect(hook.result.current.msgs.map(m => m.id)).toEqual(['current-branch'])
  const query = new URL('http://fixture' + state.api.mock.calls[1][1]).searchParams
  expect(query.get('offset')).toBe('100')
  expect(query.get('tail')).toBe('50')
})
