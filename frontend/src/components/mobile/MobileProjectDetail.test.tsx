// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import MobileProjectDetail from './MobileProjectDetail'

vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../shell/AdaptivePanel', () => ({ default: () => null }))
vi.mock('../../api', () => ({ api: async () => ({ data: [{ path: '/repo', branch: 'main', isMain: true, dirty: 0, untracked: 0, committedAhead: 0, behind: 0, sessions: [] }] }) }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => ({ value: [] }) }))
vi.mock('../sessions/native-session-list', () => ({ useNativeSessionList: () => ({ value: [
  { nativeSessionId: 'parent', taskId: 'p', title: 'Parent', projectId: 'project', directory: '/repo', branch: 'main', taskState: 'succeeded', lastActivity: Date.now() / 1000 },
  { nativeSessionId: 'child', parentNativeSessionId: 'parent', taskId: 'c', title: 'Elsewhere', projectId: 'project', directory: '/notes', taskState: 'succeeded', lastActivity: Date.now() / 1000 },
  { nativeSessionId: 'loose', taskId: 'l', title: 'No workspace', projectId: 'project', taskState: 'succeeded', lastActivity: Date.now() / 1000 },
] }) }))
afterEach(cleanup)

it('keeps unbound sessions outside the main checkout and retains activity and navigation', async () => {
  const open = vi.fn()
  render(<MobileProjectDetail projectId="project" dir="/repo" onOpenSession={open} onNewInWorktree={vi.fn()} />)
  await screen.findByText('session.wt.mainRepo')
  const unbound = screen.getByRole('button', { name: /No workspace/ })
  expect(unbound.closest('.tt-mproj-wt')?.querySelector('.wn')?.textContent).toBe('tree.loose')
  expect(unbound.closest('.tt-mproj-wt')?.querySelector('.acts')).toBeNull()
  expect(unbound.querySelector('em')?.textContent).toBe('time.justNow')
  const elsewhere = screen.getByRole('button', { name: /Elsewhere/ })
  expect(elsewhere.closest('.tt-mproj-wt')?.querySelector('.directory')?.getAttribute('title')).toBe('/notes')
  expect(elsewhere.closest('.tt-mproj-wt')?.querySelector('.tt-session-parent')).toBeTruthy()
  fireEvent.click(unbound)
  fireEvent.click(elsewhere)
  expect(open.mock.calls).toEqual([['roami:loose'], ['roami:child']])
})
