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
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path, currentNodeId: () => null }))
vi.mock('../agent/agent-page-route', () => ({ openAgentPage: (...args: unknown[]) => test.openTask(...args) }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: { children: ReactNode }) => <div>{children}</div> }))
vi.mock('../MobileSubPage', () => ({ default: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div> }))
vi.mock('./SwarmStudio', () => ({ default: ({ selected, active = true }: { selected: string; active?: boolean }) => <div data-testid="studio-selection" data-active={active}>{selected}</div> }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: test.error }, modal: { confirm: vi.fn() } }) },
  Spin: () => <span>loading</span>,
  Button: ({ children, onClick, disabled, loading }: { children: ReactNode; onClick?: () => void; disabled?: boolean; loading?: boolean }) => <button disabled={disabled || loading} onClick={onClick}>{children}</button>,
  Input: Object.assign((props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />, { TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> }),
  Select: ({ value, onChange, options, ...props }: { value: string; onChange: (value: string) => void; options: { value: string; label: string }[]; 'aria-label'?: string }) => <select aria-label={props['aria-label'] || "recipient"} value={value} onChange={event => onChange(event.target.value)}>{options.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>,
}))
function snapshot(): SwarmSnapshot {
  return { id: 'sw-one', name: 'Team', goal: 'Goal', mainConversationId: 'main', revision: 2, sequence: 10, paused: false, archived: false, state: 'review', target: {}, posts: [], mainMessages: [{ id: 'reply', role: 'assistant', text: 'Main response', createdMs: 10 }], work: [{ id: 'work', member_name: 'frontend', executor: 'codex', title: 'Build page', goal: 'Full instructions', acceptance: 'Verify results', integration: 0, task_id: 'task', revision: 1, state: 'waiting_user', dispatch_error: null, dependencies: [], attempt: { runId: 'run', state: 'verifying', summary: 'Reported outcome' } }] }
}
beforeEach(() => { localStorage.clear(); test.phone = false; test.data = snapshot(); test.api.mockReset().mockResolvedValue({ data: {} }); test.refresh.mockReset().mockResolvedValue(undefined); test.error.mockReset(); test.openTask.mockReset() })
afterEach(cleanup)
it('embeds the same managed workspace without an extra page return action', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'common.back' })).toBeNull()
  expect(screen.getByRole('button', { name: /swarm.managed.tab.chat/ })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'swarm.managed.tab.board' })).toBeTruthy()
})
it('keeps Main discussion separate from undispatched members with no task identity', () => {
  test.data = { ...test.data!, posts: [{ id: 1, author: 'human', text: 'Discuss with Main', taskId: null, createdMs: 5 }], work: test.data!.work.map(item => ({ ...item, task_id: null, revision: null, attempt: null })) }
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /swarm.managed.tab.chat/ }))
  expect(screen.getByText('Discuss with Main')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'swarm.managed.replyMember' })).toBeNull()
})
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
it('routes typed @leader to Main even after selecting a member', async () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('recipient'), { target: { value: 'work' } })
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@leader Keep the goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledTimes(1))
  expect(test.api.mock.calls[0][2]).toMatchObject({ text: '@leader Keep the goal' })
  expect(test.api.mock.calls[0][2]).not.toHaveProperty('workId')
})
it('offers leader mention completion and preserves a failed memory edit', async () => {
  test.data = { ...test.data!, teamMemory: { available: true, content: 'Existing decision', sha256: 'a'.repeat(64), source: '.roami/okr/memory/team.md' } }
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@lea' } })
  fireEvent.click(screen.getByRole('button', { name: '@leader' }))
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('@leader ')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memory' }))
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'swarm.managed.memory' })).toBeTruthy())
  fireEvent.change(screen.getByRole('textbox', { name: 'swarm.managed.memory' }), { target: { value: 'Decision with source' } })
  test.api.mockRejectedValueOnce(new Error('conflict'))
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memorySave' }))
  await waitFor(() => expect(test.error).toHaveBeenCalledWith('swarm.managed.memoryFailed'))
  expect(test.api.mock.calls[0]).toEqual(['PUT', '/agent/swarms/sw-one/memory', { content: 'Decision with source', expectedSha256: 'a'.repeat(64) }])
  expect((screen.getByRole('textbox', { name: 'swarm.managed.memory' }) as HTMLTextAreaElement).value).toBe('Decision with source')
})
it('opens mobile team memory as a secondary page and keeps reports collapsed', async () => {
  test.phone = true
  test.data = { ...test.data!, teamMemory: { available: true, content: '', sha256: 'a'.repeat(64), source: 'swarm:sw-one/memory' } }
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  const report = screen.getByText('swarm.managed.report').closest('details')
  expect(report?.open).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memory' }))
  await waitFor(() => expect(screen.getByRole('dialog').querySelector('.swarm-memory')).toBeTruthy())
})
it('requires a stored receipt and confirmed target before explicit external acceptance', async () => {
  test.data = { ...test.data!, work: test.data!.work.map(item => ({ ...item, deliverables: [{ kind: 'external_action', description: 'Confirm publication' }], evidence: { artifacts: [{ id: 'receipt', name: 'Publication receipt', mimeType: 'image/png', sizeBytes: 10, sha256: 'a'.repeat(64), downloadUrl: '/api/agent/artifacts/receipt/content' }], verification: { kind: 'declared_deliverables', state: 'awaiting_acceptance', externalAction: 'unconfirmed' } } })) }
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /Build page/ }))
  const accept = screen.getByRole('button', { name: 'agent.task.accept' }) as HTMLButtonElement
  expect(accept.disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('swarm.managed.externalTarget'), { target: { value: 'https://example.test/published' } })
  expect(accept.disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('swarm.managed.receipt'), { target: { value: 'receipt' } })
  fireEvent.click(accept)
  await waitFor(() => expect(test.api).toHaveBeenCalledWith('POST', '/agent/tasks/task/verify', { accepted: true, revision: 1, runId: 'run', evidence: { artifactId: 'receipt', target: 'https://example.test/published', state: 'confirmed' } }))
})
it('keeps a reopened memory draft tied to its original version until explicit merge', async () => {
  test.data = { ...test.data!, teamMemory: { available: true, content: 'Original decision', sha256: 'a'.repeat(64), source: '.roami/okr/memory/team.md' } }
  const view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memory' }))
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'swarm.managed.memory' })).toBeTruthy())
  fireEvent.change(screen.getByRole('textbox', { name: 'swarm.managed.memory' }), { target: { value: 'My revised decision' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.close' }))
  test.data = { ...test.data!, teamMemory: { available: true, content: 'New remote decision', sha256: 'b'.repeat(64), source: '.roami/okr/memory/team.md' } }
  view.rerender(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memory' }))
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'swarm.managed.memory' })).toBeTruthy())
  expect((screen.getByRole('textbox', { name: 'swarm.managed.memory' }) as HTMLTextAreaElement).value).toBe('My revised decision')
  expect(screen.getByTestId('studio-selection').getAttribute('data-active')).toBe('false')
  expect((screen.getByRole('button', { name: 'swarm.managed.memorySave' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText('New remote decision')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memoryMerged' }))
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memorySave' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledWith('PUT', '/agent/swarms/sw-one/memory', { content: 'My revised decision', expectedSha256: 'b'.repeat(64) }))
})
it('hydrates memory after its source recovers without seeding an empty draft', async () => {
  test.data = { ...test.data!, teamMemory: { available: false, source: '.roami/okr/memory/team.md' } }
  const view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memory' }))
  await waitFor(() => expect(screen.getByText('swarm.managed.memoryUnavailable')).toBeTruthy())
  test.data = { ...test.data!, teamMemory: { available: true, content: 'Recovered source', sha256: 'a'.repeat(64), source: '.roami/okr/memory/team.md' } }
  view.rerender(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  expect((screen.getByRole('textbox', { name: 'swarm.managed.memory' }) as HTMLTextAreaElement).value).toBe('Recovered source')
})
