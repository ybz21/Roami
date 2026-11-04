// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { useAppRoute } from './useAppRoute'
import { usePageTabs } from './usePageTabs'

function useNavigation(node: string | null = null, terms: string[] = []) {
  const routing = useAppRoute()
  return { ...routing, ...usePageTabs(routing.route, terms, routing.go, node) }
}
beforeEach(() => { localStorage.clear(); history.replaceState(null, '', '#/okr/project%20one?node=remote') })
afterEach(cleanup)

it('restores full routes through tab switches, sidebar selection and remounts', async () => {
  const first = renderHook(() => useNavigation('remote'))
  act(() => first.result.current.selectPage('settings'))
  await waitFor(() => expect(first.result.current.route).toBe('settings'))
  act(() => first.result.current.go('settings/ui/keys'))
  await waitFor(() => expect(first.result.current.route).toBe('settings/ui/keys'))
  act(() => first.result.current.selectPage('okr'))
  await waitFor(() => expect(first.result.current.route).toBe('okr/project%20one'))
  expect(location.hash).toBe('#/okr/project%20one?node=remote')
  first.unmount()
  const second = renderHook(() => useNavigation('remote'))
  act(() => second.result.current.selectPage('settings'))
  await waitFor(() => expect(second.result.current.route).toBe('settings/ui/keys'))
})

it('honors explicit list navigation and updates the remembered location', async () => {
  const { result } = renderHook(() => useNavigation())
  act(() => result.current.go('okr'))
  await waitFor(() => expect(result.current.route).toBe('okr'))
  act(() => result.current.selectPage('phone'))
  await waitFor(() => expect(result.current.route).toBe('phone'))
  act(() => result.current.selectPage('okr'))
  await waitFor(() => expect(result.current.route).toBe('okr'))
})

it('restores the neighboring page when closing the active tab and forgets closed pages', async () => {
  const { result } = renderHook(() => useNavigation())
  act(() => result.current.go('settings/node/browser'))
  await waitFor(() => expect(result.current.route).toBe('settings/node/browser'))
  act(() => result.current.closePageTab('settings'))
  await waitFor(() => expect(result.current.route).toBe('okr/project%20one'))
  act(() => result.current.selectPage('settings'))
  await waitFor(() => expect(result.current.route).toBe('settings'))
})

it('keeps task navigation exact and isolates remembered pages by node', async () => {
  const first = renderHook(() => useNavigation('remote', ['session']))
  act(() => first.result.current.go('w'))
  await waitFor(() => expect(first.result.current.route).toBe('w'))
  first.unmount()
  const second = renderHook(() => useNavigation('another-node'))
  act(() => second.result.current.selectPage('okr'))
  await waitFor(() => expect(second.result.current.route).toBe('okr'))
})

it('ignores invalid stored routes without sending the user to another tab', async () => {
  localStorage.setItem('roam.pageTabs.routes:null', JSON.stringify({ okr: 'settings/node', settings: 42 }))
  history.replaceState(null, '', '#/phone')
  const { result } = renderHook(() => useNavigation())
  act(() => result.current.selectPage('okr'))
  await waitFor(() => expect(result.current.route).toBe('okr'))
})
