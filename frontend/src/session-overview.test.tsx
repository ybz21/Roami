// @vitest-environment jsdom
import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useSessionOverview } from './session-overview'
import type { LifecycleOperation } from './components/sessions/session-lifecycle'

const state = vi.hoisted(() => ({ items: [] as any[], operations: [] as LifecycleOperation[] }))
vi.mock('./session-poll', () => ({ createSessionPoll: () => () => ({ value: state.items, loaded: true }) }))
vi.mock('./components/sessions/session-lifecycle', () => ({
  useSessionLifecycle: () => ({ value: state.operations }),
  lifecycleEnded: (op: LifecycleOperation) => ['succeeded', 'cancelled'].includes(op.state),
}))
afterEach(cleanup)

it('hides an accepted closure before stop receipts arrive and keeps it hidden after completion', () => {
  state.items = [{ name: 'closing', label: 'Closing' }, { name: 'remaining', label: 'Remaining' }]
  const op: LifecycleOperation = { operationId: 'close', resourceId: 'closing', requestKey: 'key', kind: 'close', intent: {}, state: 'queued', stage: 'accepted', revision: 1, cancelRequested: false, receipts: {}, acceptedAt: 1, updatedAt: 1 }
  state.operations = [op]
  const view = renderHook(() => useSessionOverview())
  expect(view.result.current.value.map(item => item.name)).toEqual(['remaining'])
  expect(view.result.current.closingNames.has('closing')).toBe(true)
  state.operations = [{ ...op, state: 'succeeded' }]
  view.rerender()
  expect(view.result.current.value.map(item => item.name)).toEqual(['remaining'])
  state.operations = [{ ...op, state: 'cancelled' }]
  view.rerender()
  expect(view.result.current.closingNames.size).toBe(0)
  expect(view.result.current.value.map(item => item.name)).toEqual(['closing', 'remaining'])
})
