// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import MobileProjectDetail from './MobileProjectDetail'

const ui = vi.hoisted(() => ({ confirm: vi.fn(), error: vi.fn(), success: vi.fn(), warning: vi.fn() }))
vi.mock('antd', () => ({ App: { useApp: () => ({ message: ui, modal: { confirm: ui.confirm, warning: ui.warning } }) }, Spin: () => null }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../shell/AdaptivePanel', () => ({ default: () => null }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => ({ value: [] }) }))
vi.mock('../sessions/native-session-list', () => ({ useNativeSessionList: () => ({ value: [
  { nativeSessionId: 'parent', taskId: 'p', title: 'Parent', projectId: 'project', directory: '/repo', branch: 'main', taskState: 'succeeded', lastActivity: Date.now() / 1000 },
  { nativeSessionId: 'child', parentNativeSessionId: 'parent', taskId: 'c', title: 'Elsewhere', projectId: 'project', directory: '/notes', taskState: 'succeeded', lastActivity: Date.now() / 1000 },
  { nativeSessionId: 'loose', taskId: 'l', title: 'No workspace', projectId: 'project', taskState: 'succeeded', lastActivity: Date.now() / 1000 },
] }) }))
const main = { path: '/repo', branch: 'main', isMain: true, dirty: 0, untracked: 0, committedAhead: 0, behind: 0, sessions: [] }
const worktree = { ...main, path: '/repo/.worktrees/topic', branch: 'topic', isMain: false, sessions: null }
const mount = (open = vi.fn()) => render(<MobileProjectDetail projectId="project" dir="/repo" onOpenSession={open} onNewInWorktree={vi.fn()} />)

beforeEach(() => {
  vi.resetAllMocks()
  ui.confirm.mockReturnValue({ destroy: vi.fn(), update: vi.fn() })
  vi.mocked(api).mockResolvedValue({ data: [main] })
})
afterEach(cleanup)

it('keeps unbound sessions outside the main checkout and retains activity and navigation', async () => {
  const open = vi.fn()
  mount(open)
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

it.each([0, 2])('confirms removal, preserves the branch and updates the list (untracked=%s)', async untracked => {
  vi.mocked(api).mockImplementation(async method => {
    if (method === 'POST') {
      vi.mocked(api).mockResolvedValue({ data: [main] })
      return { data: { ok: true } }
    }
    return { data: [main, { ...worktree, untracked, mergedInto: 'main' }] }
  })
  mount()
  await screen.findByText('session.wt.mainRepo')
  if (!untracked) fireEvent.click(screen.getByRole('button', { name: 'mobile.proj.showQuiet' }))
  fireEvent.click(screen.getByRole('button', { name: 'project.wt.delete' }))
  const dialog = ui.confirm.mock.calls[0][0]
  expect(dialog.okButtonProps).toEqual({ danger: true })
  expect(dialog.content).toBe(untracked > 0 ? 'mobile.wt.deleteDirtyDesc' : 'mobile.wt.deleteDesc')
  expect(api).not.toHaveBeenCalledWith('POST', expect.any(String), expect.anything())
  await act(async () => { await dialog.onOk() })
  expect(api).toHaveBeenCalledWith('POST', '/git/worktree/remove', { path: worktree.path, forceWorktree: untracked > 0 })
  expect(ui.success).toHaveBeenCalledWith('project.wt.deleted')
  await waitFor(() => expect(screen.queryByText('topic')).toBeNull())
})

it('keeps protected worktrees off the deletion path', async () => {
  vi.mocked(api).mockResolvedValue({ data: [main,
    { ...worktree, path: '/repo/.worktrees/active', branch: 'active', sessions: [{ session: 'active' }] },
    { ...worktree, path: '/repo/.worktrees/locked', branch: 'locked', locked: true },
    { ...worktree, path: '/repo/.worktrees/prunable', branch: 'prunable', prunable: true },
    { ...worktree, path: '/repo/.worktrees/detached', branch: '' },
  ] })
  mount()
  await screen.findByRole('button', { name: 'mobile.proj.showQuiet' })
  fireEvent.click(screen.getByRole('button', { name: 'mobile.proj.showQuiet' }))
  expect(screen.getByText('locked')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'project.wt.delete' })).toBeNull()
})

it.each([['WORKTREE_DIRTY', 'mobile.wt.deleteChanged'], ['SESSIONS_INSIDE', 'worktree.sessionsInsideDesc']])('keeps the card when removal is rejected with %s', async (code, message) => {
  vi.mocked(api).mockImplementation(async method => {
    if (method === 'POST') throw Object.assign(new Error(code), { apiError: { code } })
    return { data: [main, { ...worktree, committedAhead: 1 }] }
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'project.wt.delete' }))
  await act(async () => { await ui.confirm.mock.calls[0][0].onOk() })
  expect(ui.error).toHaveBeenCalledWith(message)
  expect(screen.getByText('topic')).toBeTruthy()
})

it('cleans only the confirmed merged worktrees and continues after an item changes', async () => {
  const changed = { ...worktree, head: 'old-head', mergedInto: 'main' }
  const landed = { ...changed, path: '/repo/.worktrees/landed', branch: 'landed', head: 'landed-head' }
  const external = { ...changed, path: '/repo/.worktrees/external', branch: 'external', external: true }
  let current = [main, changed, landed, external]
  vi.mocked(api).mockImplementation(async (method, _url, body) => {
    if (method === 'GET') return { data: current }
    if (body.path === changed.path) {
      current = current.map(w => w.path === changed.path ? { ...w, untracked: 1 } : w)
      throw Object.assign(new Error('dirty'), { apiError: { code: 'WORKTREE_DIRTY' } })
    }
    current = current.filter(w => w.path !== body.path)
    return { data: { ok: true } }
  })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'project.cleanupAll' }))
  expect(api).not.toHaveBeenCalledWith('POST', expect.any(String), expect.anything())
  await act(async () => { await ui.confirm.mock.calls[0][0].onOk() })
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'POST')).toEqual([
    ['POST', '/git/worktree/cleanup-merged', { path: changed.path, branch: changed.branch, head: changed.head }],
    ['POST', '/git/worktree/cleanup-merged', { path: landed.path, branch: landed.branch, head: landed.head }],
  ])
  expect(ui.warning).toHaveBeenCalledWith(expect.objectContaining({ title: 'project.cleanupIncomplete' }))
  await waitFor(() => expect(screen.getByText('topic')).toBeTruthy())
  expect(screen.queryByRole('button', { name: 'project.cleanupAll' })).toBeNull()
})
