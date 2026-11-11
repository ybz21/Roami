// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import MobileSessions from './MobileSessions'
import { api } from '../../api'
import { closeSession, renameSession, stopSession } from '../sessions/session-actions'
import { refreshSessionLists } from '../sessions/native-session-list'
import { setSessionLabels } from '../sessions/session-label'

const scope = vi.hoisted(() => ({ node: 0 }))
vi.mock('../cluster/node-url', () => ({ currentNodeId: () => String(scope.node), useCurrentNodeId: () => String(scope.node), nodeApi: (path: string) => '/test-node-' + scope.node + path }))
beforeEach(() => { scope.node++; ui.loading.mockImplementation(() => vi.fn()) })

const ui = vi.hoisted(() => ({ confirm: vi.fn(), error: vi.fn(), success: vi.fn(), loading: vi.fn(() => vi.fn()) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../sessions/SessionLifecyclePanel', () => ({ SessionLifecycleInbox: () => null }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../sessions/session-actions', () => ({ closeSession: vi.fn(), renameSession: vi.fn(), stopSession: vi.fn() }))
vi.mock('../sessions/native-session-list', () => ({ refreshSessionLists: vi.fn(), useNativeSessionList: () => ({ failed: false, value: [{ nativeSessionId: 'native', taskId: 'task', title: 'Roami chat', taskState: 'running', lastActivity: 200, projectId: 'project' }] }) }))
vi.mock('../swarm/swarm-directory', () => ({ loadSwarmDirectory: async () => [] }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: ui, modal: { confirm: ui.confirm } }) },
  Input: ({ onPressEnter: _enter, ...props }: any) => <input {...props} />,
  Checkbox: ({ children, ...props }: any) => <label><input type="checkbox" {...props} />{children}</label>,
  Radio: Object.assign(({ children, ...props }: any) => <label><input type="radio" name="close-mode" {...props} />{children}</label>, {
    Group: ({ children, onChange }: any) => <div onChange={onChange}>{children}</div>,
  }),
  Select: () => null,
  Spin: () => null,
  Modal: ({ open, title, children, onOk, okText }: any) => open ? <div role="dialog">{title}{children}<button onClick={onOk}>{okText}</button></div> : null,
}))
afterEach(() => { cleanup(); setSessionLabels({}); localStorage.clear(); vi.resetAllMocks(); vi.useRealTimers() })

const mount = (worktreeStatus?: Record<string, unknown>) => {
  setSessionLabels({ codex: 'Codex chat' })
  vi.mocked(api).mockImplementation(async (_method, path, body) => ({ data: path === '/session-lifecycle/operations' ? (_method === 'POST' ? { operationId: crypto.randomUUID(), resourceId: 'codex', kind: 'close', state: 'queued', receipts: {}, intent: body.intent } : []) : path.endsWith('/worktree-status') ? worktreeStatus : path === '/projects' ? { projects: [{ key: 'project', name: 'Project', dir: '/work', unfinished: 0 }] } : { items: [{ name: 'codex', label: 'Codex chat', agent: 'codex', lastActivity: 100, running: true, waiting: false, dormant: false, projectKey: 'project', project: 'Project', projectDir: '/work' }] } }))
  return render(<MobileSessions onOpen={vi.fn()} onNewTask={vi.fn()} onNewInWorktree={vi.fn()} />)
}

it('uses the same rows, ordering, navigation and menu for Roami and Codex', async () => {
  const view = mount()
  const codex = await screen.findByRole('button', { name: /Codex chat/ })
  const native = screen.getByRole('button', { name: /Roami chat/ })
  expect(native.className).toBe(codex.className)
  expect([...view.container.querySelectorAll('.tt-msess-row b')].map(row => row.textContent)).toEqual(['Roami chat', 'Codex chat'])
  expect(view.container.querySelector('[class*="native-project"]')).toBeNull()
  expect(native.querySelectorAll('button')).toHaveLength(0)
  for (const row of [native, codex]) {
    fireEvent.contextMenu(row)
    const menu = within(screen.getByRole('dialog'))
    expect(menu.getByRole('button', { name: 'session.rename' })).toBeTruthy()
    expect(menu.getByRole('button', { name: /mobile.interrupt/ })).toBeTruthy()
    fireEvent.click(menu.getByRole('button', { name: 'session.close' }))
    await waitFor(() => expect(ui.confirm).toHaveBeenCalledTimes(row === native ? 1 : 2))
    await ui.confirm.mock.calls[ui.confirm.mock.calls.length - 1][0].onOk()
  }
  expect(closeSession).toHaveBeenCalledWith('roami:native')
  expect(closeSession).toHaveBeenCalledWith('codex')
})

const worktree = { inWorktree: true, path: '/work/.worktrees/task', base: 'main', external: false, others: 0, snapshot: 'confirmed-snapshot', sessionIdentity: 'confirmed-session' }
const beginCodexClose = async () => {
  fireEvent.contextMenu(await screen.findByRole('button', { name: /Codex chat/ }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'session.close' }))
}

it.each([true, false])('honors the worktree deletion checkbox on mobile (delete=%s)', async remove => {
  mount(worktree)
  await beginCodexClose()
  await waitFor(() => expect(ui.confirm).toHaveBeenCalledOnce())
  const confirm = ui.confirm.mock.calls[0][0]
  const content = render(confirm.content)
  const checkbox = content.getByRole('checkbox', { name: 'worktree.close.removeWithSession' }) as HTMLInputElement
  expect(checkbox.checked).toBe(true)
  if (!remove) fireEvent.click(checkbox)
  await act(async () => { await confirm.onOk() })
  expect(api).toHaveBeenCalledWith('POST', '/session-lifecycle/operations', expect.objectContaining({ kind: 'close', resourceId: 'codex', intent: { name: 'Codex chat', mode: remove ? 'discard' : 'keep', path: worktree.path, snapshot: worktree.snapshot, sessionIdentity: worktree.sessionIdentity } }))
  expect(closeSession).not.toHaveBeenCalled()
  expect(refreshSessionLists).toHaveBeenCalled()
  await waitFor(() => expect(screen.queryByRole('button', { name: /Codex chat/ })).toBeNull())
})

it('offers unfinished worktree choices before closing a mobile session', async () => {
  mount({ ...worktree, dirty: 1 })
  await beginCodexClose()
  const dialog = within(await screen.findByRole('dialog'))
  expect(dialog.getByRole('radio', { name: 'worktree.close.keep' })).toBeTruthy()
  fireEvent.click(dialog.getByRole('radio', { name: 'worktree.close.discard' }))
  fireEvent.click(dialog.getByRole('button', { name: 'session.close' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/session-lifecycle/operations', expect.objectContaining({ kind: 'close', resourceId: 'codex', intent: { name: 'Codex chat', mode: 'discard', path: worktree.path, snapshot: worktree.snapshot, sessionIdentity: worktree.sessionIdentity } })))
  expect(closeSession).not.toHaveBeenCalled()
})

it('keeps a worktree used by another session when closing from mobile', async () => {
  mount({ ...worktree, others: 1 })
  await beginCodexClose()
  await waitFor(() => expect(ui.confirm).toHaveBeenCalledOnce())
  await act(async () => { await ui.confirm.mock.calls[0][0].onOk() })
  expect(closeSession).toHaveBeenCalledWith('codex')
  expect(vi.mocked(api).mock.calls.some(([method, path]) => method === 'POST' && path.endsWith('/close-with-worktree'))).toBe(false)
})

it('renames and stops Roami through the same menu actions', async () => {
  mount()
  const row = await screen.findByRole('button', { name: /Roami chat/ })
  fireEvent.contextMenu(row)
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /mobile.interrupt/ }))
  await waitFor(() => expect(stopSession).toHaveBeenCalledWith('roami:native'))
  fireEvent.contextMenu(row)
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'session.rename' }))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Follow-up' } })
  vi.mocked(renameSession).mockResolvedValue({ data: { label: 'Follow-up' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.confirm' }))
  await waitFor(() => expect(renameSession).toHaveBeenCalledWith('roami:native', 'Follow-up'))
})

it('advances relative activity time while an unchanged shared overview keeps its snapshot', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(149000)
  await act(async () => { mount() })
  const time = () => screen.getByRole('button', { name: /Codex chat/ }).querySelector('em')?.textContent
  expect(time()).toBe('time.justNow')
  await act(async () => { await vi.advanceTimersByTimeAsync(61000) })
  expect(time()).toBe('time.minutesAgo')
  expect(vi.mocked(api).mock.calls.filter(([, path]) => path === '/sessions/overview').length).toBeLessThan(15)
})
