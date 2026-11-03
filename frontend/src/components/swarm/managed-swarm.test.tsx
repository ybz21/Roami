// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ManagedSwarm from './ManagedSwarm'
import type { SwarmSnapshot } from './swarm-protocol'

const test = vi.hoisted(() => ({ phone: false, api: vi.fn(), refresh: vi.fn(), openTask: vi.fn(), error: vi.fn(), data: null as SwarmSnapshot | null }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => test.api(...args) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: test.phone }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('./useSwarmSnapshot', () => ({ useSwarmSnapshot: () => ({ data: test.data, error: false, refresh: test.refresh }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path }))
vi.mock('../agent/agent-page-route', () => ({ openAgentPage: (...args: unknown[]) => test.openTask(...args) }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: { children: ReactNode }) => <div>{children}</div> }))
vi.mock('../MobileSubPage', () => ({ default: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div> }))
vi.mock('./SwarmStudio', () => ({ default: ({ selected }: { selected: string }) => <div data-testid="studio-selection">{selected}</div> }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: test.error }, modal: { confirm: vi.fn() } }) },
  Spin: () => <span>loading</span>,
  Button: ({ children, onClick, disabled, loading }: { children: ReactNode; onClick?: () => void; disabled?: boolean; loading?: boolean }) => <button disabled={disabled || loading} onClick={onClick}>{children}</button>,
  Input: { TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> },
  Select: ({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }) => <select aria-label="recipient" value={value} onChange={event => onChange(event.target.value)}>{options.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>,
}))
function snapshot(): SwarmSnapshot {
  return { id: 'sw-one', name: 'Team', goal: 'Goal', mainConversationId: 'main', revision: 2, sequence: 10, paused: false, archived: false, state: 'review', target: {}, posts: [], mainMessages: [{ id: 'reply', role: 'assistant', text: 'Main response', createdMs: 10 }], work: [{ id: 'work', member_name: 'frontend', executor: 'codex', title: 'Build page', goal: 'Full instructions', acceptance: 'Verify results', integration: 0, task_id: 'task', revision: 1, state: 'waiting_user', dispatch_error: null, dependencies: [], attempt: { runId: 'run', state: 'verifying', summary: 'Reported outcome' } }] }
}
beforeEach(() => { localStorage.clear(); test.phone = false; test.data = snapshot(); test.api.mockReset().mockResolvedValue({ data: {} }); test.refresh.mockReset().mockResolvedValue(undefined); test.error.mockReset(); test.openTask.mockReset() })
afterEach(cleanup)
it('keeps a reported task in review and opens the original task outputs', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /swarm.managed.tab.chat/ }))
  fireEvent.click(screen.getAllByRole('button', { name: 'swarm.managed.openTask' })[0])
  expect(screen.getByRole('button', { name: 'swarm.managed.tab.board' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: /Build page/ }))
  expect(screen.getByTestId('studio-selection').textContent).toBe('work')
  expect(screen.getAllByText('swarm.managed.state.waiting_user').length).toBeGreaterThan(0)
  fireEvent.click(screen.getAllByRole('button', { name: 'swarm.managed.openTask' })[0])
  expect(test.openTask).toHaveBeenCalledWith('tasks', 'task')
  expect(test.api).not.toHaveBeenCalled()
})
it('preserves draft across mobile tabs and Enter never submits a message', () => {
  test.phone = true
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /swarm.managed.tab.chat/ }))
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'Keep this draft' } }); fireEvent.keyDown(input, { key: 'Enter' })
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.tab.board' }))
  fireEvent.click(screen.getByRole('button', { name: /swarm.managed.tab.chat/ }))
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep this draft')
  expect(test.api).not.toHaveBeenCalled()
})
it('retries unconfirmed member steering with its original key and revision', async () => {
  test.api.mockRejectedValueOnce(new Error('unknown'))
  const view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('recipient'), { target: { value: 'work' } })
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Change the page' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.error).toHaveBeenCalled())
  const first = test.api.mock.calls[0][2]
  test.data = { ...test.data!, work: test.data!.work.map(item => ({ ...item, revision: 2 })) }
  view.rerender(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledTimes(2))
  expect(test.api.mock.calls[1][2]).toEqual(first)
  expect(first).toMatchObject({ workId: 'work', taskRevision: 1, text: 'Change the page' })
})
it('does not offer an action that can mark a task verified', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.queryByText('swarm.memberMarkedDone')).toBeNull()
  expect(screen.queryByRole('button', { name: /verify|done/i })).toBeNull()
})
