// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ManagedSwarm from './ManagedSwarm'
import type { SwarmSnapshot } from './swarm-protocol'

const test = vi.hoisted(() => ({ nativeSessions: [] as { taskId: string; revision: number; lifecycle: string }[], phone: false, api: vi.fn(), refresh: vi.fn(), openTask: vi.fn(), error: vi.fn(), data: null as SwarmSnapshot | null }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => ({ value: [{ name: 'real-session', dormant: false }], failed: false }) }))
vi.mock('../agent/useAgentData', () => ({ useAgentData: () => ({ value: test.nativeSessions, failed: false }) }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => test.api(...args) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: test.phone }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('./useSwarmSnapshot', () => ({ useSwarmSnapshot: () => ({ data: test.data, error: false, refresh: test.refresh }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path, currentNodeId: () => null }))
vi.mock('../agent/agent-page-route', () => ({ openAgentPage: (...args: unknown[]) => test.openTask(...args) }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: { children: ReactNode }) => <div>{children}</div> }))
vi.mock('../MobileSubPage', () => ({ default: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div> }))
vi.mock('./SwarmStudio', () => ({ default: ({ selected, active = true, nodes }: { selected: string; active?: boolean; nodes: { id: string }[] }) => <div data-testid="studio-selection" data-active={active} data-nodes={nodes.map(node => node.id).join(',')}>{selected}</div> }))
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
beforeEach(() => { test.nativeSessions = []; localStorage.clear(); test.phone = false; test.data = snapshot(); test.api.mockReset().mockResolvedValue({ data: {} }); test.refresh.mockReset().mockResolvedValue(undefined); test.error.mockReset(); test.openTask.mockReset() })
afterEach(cleanup)
it('embeds the same managed workspace without an extra page return action', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'common.back' })).toBeNull()
  expect(screen.getAllByRole('combobox')).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'swarm.managed.tab.board' })).toBeTruthy()
})
it('keeps Main discussion separate from undispatched members with no task identity', () => {
  test.data = { ...test.data!, posts: [{ id: 1, author: 'human', text: 'Discuss with Main', taskId: null, createdMs: 5 }], work: test.data!.work.map(item => ({ ...item, task_id: null, revision: null, attempt: null })) }
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'group' } })
  expect(screen.getByText('Discuss with Main')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'swarm.managed.replyMember' })).toBeNull()
})
it('keeps a reported task in review and opens the original task outputs', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'group' } })
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
  fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'group' } })
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'Keep this draft' } }); fireEvent.keyDown(input, { key: 'Enter' })
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.tab.board' }))
  fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'group' } })
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep this draft')
  expect(test.api).not.toHaveBeenCalled()
})
it('retries unconfirmed member steering with its original key and revision', async () => {
  test.api.mockRejectedValueOnce(new Error('unknown'))
  const view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
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
  fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
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
it('shows Main coordination in the default collaboration view and opens its existing chat', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.getByRole('region', { name: 'swarm.relations.title' })).toBeTruthy()
  expect(screen.getByText('Build page', { selector: '.swarm-relation-duty' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /Roami Main.*swarm.relations.coordinates/ }))
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('main')
  expect(screen.getByRole('textbox')).toBeTruthy()
  expect(test.api).not.toHaveBeenCalled()
})
it('keeps the real five kanban states rather than rendering a synthetic member list', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.tab.board' }))
  for (const column of ['backlog', 'doing', 'blocked', 'review', 'done']) expect(screen.getByRole('heading', { name: 'swarm.board.col.' + column })).toBeTruthy()
  const card = screen.getByRole('button', { name: /Build page/ })
  expect(card.closest('section')?.querySelector('h3')?.textContent).toBe('swarm.board.col.review')
})

it('opens an assigned member through its existing task page without sending or launching', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.relations.openWork' }))
  expect(test.openTask).toHaveBeenCalledWith('tasks', 'task')
  expect(test.api).not.toHaveBeenCalled()
})
it.each(['entry', 'dropdown', 'reply'])('selects a member via %s consistently with an existing Main mention while preserving the body', async source => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  const input = screen.getByRole('textbox') as HTMLTextAreaElement
  fireEvent.change(input, { target: { value: '@leader Keep this body\nAnd its second line' } })
  if (source === 'entry') fireEvent.click(screen.getByRole('button', { name: 'swarm.relations.chat' }))
  else if (source === 'dropdown') fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
  else { fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'group' } }); fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.replyMember' })) }
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('work')
  expect(input.value).toBe('@frontend Keep this body\nAnd its second line')
  expect(test.api).not.toHaveBeenCalled()
  if (source === 'entry') {
    expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('work')
    expect(document.activeElement).toBe(input)
  }
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledOnce())
  expect(test.api.mock.calls[0][2]).toMatchObject({ workId: 'work', taskRevision: 1, text: '@frontend Keep this body\nAnd its second line' })
})
it('explicitly selects Main after a member chat and keeps a plain or mentioned draft intact', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  const input = screen.getByRole('textbox') as HTMLTextAreaElement
  fireEvent.change(input, { target: { value: '@frontend Keep the requirements' } })
  fireEvent.click(screen.getByRole('button', { name: /Roami Main.*swarm.relations.coordinates/ }))
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('main')
  expect(input.value).toBe('@leader Keep the requirements')
  fireEvent.change(input, { target: { value: 'Plain body\nWith details' } })
  fireEvent.click(screen.getByRole('button', { name: 'swarm.relations.chat' }))
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('work')
  fireEvent.click(screen.getByRole('button', { name: /Roami Main.*swarm.relations.coordinates/ }))
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('main')
  expect(input.value).toBe('Plain body\nWith details')
  expect(test.api).not.toHaveBeenCalled()
})
it.each([false, true])('keeps undispatched plans local and routes adjustments to Main (phone=%s)', phone => {
  test.phone = phone
  test.data = { ...test.data!, work: test.data!.work.map(item => ({ ...item, task_id: null, revision: null, attempt: null })) }
  const term = vi.fn()
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={term} />)
  expect(screen.queryByRole('button', { name: 'swarm.relations.openWork' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'swarm.relations.chat' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'swarm.relations.viewPlan' }))
  const detail = phone ? within(screen.getByRole('dialog')) : within(document.querySelector('.swarm-work-detail') as HTMLElement)
  expect(detail.getByText('Full instructions').closest('details')?.open).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.relations.adjustMain' }))
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('main')
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('main')
  expect(test.openTask).not.toHaveBeenCalled()
  expect(term).not.toHaveBeenCalled()
  expect(test.api).not.toHaveBeenCalled()
})
it('keeps an explicitly typed recognized mention and the recipient label in agreement', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.relations.chat' }))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@MAIN This is for Main' } })
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('main')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@frontend This is for the member' } })
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('work')
  expect(test.api).not.toHaveBeenCalled()
})

it('keeps the team and shared chat in one workspace and scopes real task posts by member', () => {
 test.data = { ...test.data!, posts: [{id:1,author:'frontend',text:'Member evidence',taskId:'task',createdMs:20},{id:2,author:'old-member',text:'Archived task post',taskId:'old-task',createdMs:15}] }
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
 const workspace = screen.getByRole('navigation',{name:'swarm.managed.workspace'})
 expect(within(workspace).queryByRole('button',{name:'swarm.managed.tab.chat'})).toBeNull()
 expect(screen.getByRole('region',{name:'swarm.relations.title'})).toBeTruthy()
 expect(screen.getByText('Member evidence')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
 expect(screen.getByText('Member evidence')).toBeTruthy()
 expect(screen.queryByText('Main response')).toBeNull()
 expect(screen.queryByText('Archived task post')).toBeNull()
 fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'main' } })
 expect(screen.getByText('Main response')).toBeTruthy()
 expect(screen.queryByText('Archived task post')).toBeNull()
 fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'group' } })
 expect(screen.getByText('Archived task post')).toBeTruthy()
 expect(test.api).not.toHaveBeenCalled()
})
it('opens the phone team in place and releases its scene when collapsed', () => {
 test.phone=true
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
 expect(screen.getByTestId('studio-selection').getAttribute('data-active')).toBe('false')
 fireEvent.click(screen.getByRole('button',{name:'swarm.chat.team'}))
 expect(screen.getByTestId('studio-selection').getAttribute('data-active')).toBe('true')
 fireEvent.click(screen.getByRole('button',{name:'swarm.relations.chat'}))
 expect(screen.getByTestId('studio-selection').getAttribute('data-active')).toBe('false')
 expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('work')
})
it('opens a concrete current conversation only after reading its real task identity', async () => {
 const session = vi.fn()
 test.api.mockResolvedValueOnce({data:{task:{id:'task',revision:1},attempts:[{id:'run',revision:1,state:'succeeded',sessionId:'real-session'}]}})
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
 fireEvent.click(screen.getByRole('button',{name:'swarm.managed.openSession'}))
 await waitFor(()=>expect(session).toHaveBeenCalledWith('real-session'))
 expect(test.api).toHaveBeenCalledOnce()
 expect(test.api).toHaveBeenCalledWith('GET','/agent/tasks/task')
 expect(test.openTask).not.toHaveBeenCalled()
})
it.each(['closed','changed','revision'])('keeps a %s conversation on its real task detail instead of opening an obsolete session', async kind => {
 const session = vi.fn()
 test.api.mockResolvedValueOnce({data:{task:{id:'task',revision:1},sessionClosure:kind==='closed'?{state:'closed'}:null,attempts:[{id:kind==='changed'?'new-run':'run',revision:kind==='revision'?0:1,sessionId:'obsolete'}]}})
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
 fireEvent.click(screen.getByRole('button',{name:'swarm.managed.openSession'}))
 await waitFor(()=>expect(test.openTask).toHaveBeenCalledWith('tasks','task'))
 expect(session).not.toHaveBeenCalled()
 expect(test.api).toHaveBeenCalledOnce()
})

it('enters a bound native conversation instead of creating a new agent', async () => {
 const session = vi.fn()
 test.api.mockResolvedValueOnce({data:{task:{id:'task',revision:1,nativeSession:{id:'native-session',conversationId:'native-conversation'}},attempts:[{id:'run',revision:1,state:'succeeded'}]}})
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
 fireEvent.click(screen.getByRole('button',{name:'swarm.managed.openSession'}))
 await waitFor(()=>expect(test.openTask).toHaveBeenCalledWith('session','native-session'))
 expect(session).not.toHaveBeenCalled()
 expect(test.api).toHaveBeenCalledWith('GET','/agent/tasks/task')
 expect(test.api).toHaveBeenCalledOnce()
})

it('does not open an obsolete session when the same member advances while its identity read is pending', async () => {
 let resolve!: (value: unknown) => void
 test.api.mockReturnValueOnce(new Promise(value => { resolve = value }))
 const session = vi.fn()
 const view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
 fireEvent.click(screen.getByRole('button', {name:'swarm.managed.openSession'}))
 expect(test.api).toHaveBeenCalledWith('GET','/agent/tasks/task')
 test.data = {...test.data!,work:test.data!.work.map(work=>({...work,revision:2,attempt:{...work.attempt!,runId:'run-new'}}))}
 view.rerender(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 resolve({data:{task:{id:'task',revision:1},attempts:[{id:'run',revision:1,sessionId:'obsolete-session'}]}})
 await waitFor(()=>expect(test.openTask).toHaveBeenCalledWith('tasks','task'))
 expect(session).not.toHaveBeenCalled()
 expect(test.api).toHaveBeenCalledOnce()
})


it('opens the phone team preview as its own page and returns to the same member thread', async () => {
  test.phone = true
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.chat.team' }))
  const preview = screen.getByRole('dialog')
  expect(within(preview).getByTestId('studio-selection').getAttribute('data-active')).toBe('true')
  expect(screen.getAllByTestId('studio-selection')).toHaveLength(1)
  fireEvent.click(within(preview).getByRole('button', { name: 'frontend', pressed: false }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect((screen.getByLabelText('swarm.chat.conversations') as HTMLSelectElement).value).toBe('work')
  expect(document.activeElement?.tagName).not.toBe('TEXTAREA')
})

it('does not open a recorded CLI session missing from the shared live-session overview', async () => {
  const session = vi.fn()
  test.api.mockResolvedValueOnce({ data: { task: { id: 'task', revision: 1 }, attempts: [{ id: 'run', revision: 1, sessionId: 'gone-session' }] } })
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
  fireEvent.change(screen.getByLabelText('swarm.chat.conversations'), { target: { value: 'work' } })
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.openSession' }))
  await waitFor(() => expect(test.openTask).toHaveBeenCalledWith('tasks', 'task'))
  expect(session).not.toHaveBeenCalled()
})


it('shows only confirmed live instances in the scene and keeps historical and planned work in the roster', () => {
  test.data!.work[0].attempt!.sessionId = 'real-session'
  test.data!.work.push({ ...test.data!.work[0], id: 'gone', member_name: 'old-role', attempt: { ...test.data!.work[0].attempt!, sessionId: 'gone-session' } }, { ...test.data!.work[0], id: 'planned', member_name: 'future-role', task_id: null, attempt: null })
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.getByTestId('studio-selection').getAttribute('data-nodes')).toBe('main,work')
  expect(screen.getByRole('button', { name: 'old-role', pressed: false })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'future-role', pressed: false })).toBeTruthy()
  expect(screen.getAllByRole('combobox')).toHaveLength(1)
})


it.each([
  ['open', 1, 'main,work'],
  ['closed', 1, 'main'],
  ['closing', 1, 'main'],
  ['open', 0, 'main'],
] as const)('requires an open native instance at the current revision (%s, %s)', (lifecycle, revision, nodes) => {
  test.data!.work[0].executor = 'native'
  test.nativeSessions = [{ taskId: 'task', revision, lifecycle }]
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.getByTestId('studio-selection').getAttribute('data-nodes')).toBe(nodes)
})
