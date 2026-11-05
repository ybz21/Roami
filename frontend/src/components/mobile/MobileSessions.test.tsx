// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import MobileSessions from './MobileSessions'
import { api } from '../../api'
import { closeSession, renameSession, stopSession } from '../sessions/session-actions'

const ui = vi.hoisted(() => ({ confirm: vi.fn(), error: vi.fn(), success: vi.fn() }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../sessions/session-actions', () => ({ closeSession: vi.fn(), renameSession: vi.fn(), stopSession: vi.fn() }))
vi.mock('../sessions/native-session-list', () => ({ useNativeSessionList: () => ({ failed: false, value: [{ nativeSessionId: 'native', taskId: 'task', title: 'Roami chat', taskState: 'running', lastActivity: 200, projectId: 'project' }] }) }))
vi.mock('../swarm/swarm-directory', () => ({ loadSwarmDirectory: async () => [] }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: ui, modal: { confirm: ui.confirm } }) },
  Input: ({ onPressEnter: _enter, ...props }: any) => <input {...props} />,
  Spin: () => null,
  Modal: ({ open, title, children, onOk, okText }: any) => open ? <div role="dialog">{title}{children}<button onClick={onOk}>{okText}</button></div> : null,
}))
afterEach(() => { cleanup(); localStorage.clear(); vi.resetAllMocks() })

const mount = () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path === '/projects' ? { projects: [{ key: 'project', name: 'Project', dir: '/work', unfinished: 0 }] } : { items: [{ name: 'codex', label: 'Codex chat', agent: 'codex', lastActivity: 100, running: true, waiting: false, dormant: false, projectKey: 'project', project: 'Project', projectDir: '/work' }] } }))
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
    await ui.confirm.mock.calls[ui.confirm.mock.calls.length - 1][0].onOk()
  }
  expect(closeSession).toHaveBeenCalledWith('roami:native')
  expect(closeSession).toHaveBeenCalledWith('codex')
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
