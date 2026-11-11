// @vitest-environment jsdom
import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useNativeSessionList } from './native-session-list'

const records = vi.hoisted(() => [
  { nativeSessionId: 'active', lifecycle: 'running' },
  { nativeSessionId: 'closing', lifecycle: 'closing' },
  { nativeSessionId: 'closed', lifecycle: 'closed' },
])
vi.mock('../../session-poll', () => ({ createSessionPoll: () => () => ({ value: records, loaded: true }) }))
afterEach(cleanup)
it('hides closing native sessions while retaining records for explicit recovery views', () => {
  const visible = renderHook(() => useNativeSessionList())
  expect(visible.result.current.value.map(session => session.nativeSessionId)).toEqual(['active'])
  const recovery = renderHook(() => useNativeSessionList(true, true))
  expect(recovery.result.current.value).toBe(records)
})
