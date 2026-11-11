// @vitest-environment jsdom
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useSessionDirectory } from './useSessionDirectory'

const snapshot = vi.hoisted(() => ({ value: [], closingNames: new Set<string>() }))
vi.mock('../session-overview', () => ({ useSessionOverview: () => snapshot }))
vi.mock('../components/sessions/native-session-list', () => ({ useNativeSessionList: () => ({ value: [], loaded: true }) }))
vi.mock('../api', () => ({ api: vi.fn(async () => [{ id: '$1', name: 'closing' }, { id: '$2', name: 'remaining' }]) }))
afterEach(cleanup)
it('removes closing sessions from stale CLI lists and workspace identities', async () => {
  snapshot.closingNames = new Set()
  const view = renderHook(() => useSessionDirectory())
  await waitFor(() => expect(view.result.current.sessListLoaded).toBe(true))
  expect(view.result.current.sessList.map(session => session.name)).toEqual(['closing', 'remaining'])
  snapshot.closingNames = new Set(['closing'])
  view.rerender()
  expect(view.result.current.sessList.map(session => session.name)).toEqual(['remaining'])
  expect(view.result.current.sessIds).toEqual({ byId: { '$2': 'remaining' }, byName: { remaining: '$2' } })
})
