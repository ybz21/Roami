// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useState, type ReactNode } from 'react'
import ManagedSwarm from './ManagedSwarm'
import type { SwarmSnapshot } from './swarm-protocol'

const test = vi.hoisted(() => ({ sessions: [{ name: "real-session", agent: "codex", dormant: false }] as { name: string; agent: string; dormant: boolean; projectKey?: string }[], mainTurns: null as { state: string }[] | null, nativeSessions: [] as { taskId: string; revision: number; lifecycle: string }[], phone: false, api: vi.fn(), refresh: vi.fn(), openTask: vi.fn(), error: vi.fn(), data: null as SwarmSnapshot | null }))
vi.mock('../chat/CodexChat', () => ({ default: ({ name, onSend }: { name: string; onSend: (text: string) => Promise<void> }) => {
  const key = 'roami.session.draft::' + name, [value, edit] = useState(() => localStorage.getItem(key) || '')
  return <><textarea value={value} onChange={event => { edit(event.target.value); localStorage.setItem(key, event.target.value) }} /><button onClick={() => { void onSend(value) }}>common.send</button></>
} }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => ({ value: test.sessions, failed: false }) }))
vi.mock('../agent/useAgentThread', () => ({ useAgentThread: (cid: string) => ({ view: cid && test.mainTurns ? { turns: test.mainTurns, messages: [] } : null, refresh: test.refresh }) }))
vi.mock('../agent/useAgentData', () => ({ useAgentData: () => ({ value: test.nativeSessions, failed: false }) }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => test.api(...args) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: test.phone }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key === 'swarm.conversation.main' ? 'Main' : key, locale: 'en-US' }) }))
vi.mock('./useSwarmSnapshot', () => ({ useSwarmSnapshot: () => ({ data: test.data, error: false, refresh: test.refresh }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path, currentNodeId: () => null, useCurrentNodeId: () => null }))
vi.mock('../agent/agent-page-route', () => ({ openAgentPage: (...args: unknown[]) => test.openTask(...args) }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: { children: ReactNode }) => <div>{children}</div> }))
vi.mock('../MobileSubPage', () => ({ default: ({ children, onBack }: { children: ReactNode; onBack: () => void }) => <div role="dialog"><button type="button" aria-label="test.back" onClick={onBack}>Back</button>{children}</div> }))
vi.mock('./SwarmStudio', () => ({ default: ({ selected, active = true, nodes, onSelect }: { selected: string; active?: boolean; nodes: { id: string; state: string }[]; onSelect: (id: string) => void }) => <div data-testid="studio-selection" data-active={active} data-nodes={nodes.map(node => node.id).join(',')} data-main-state={nodes[0]?.state}>{selected}{nodes.map(node => <button key={node.id} aria-label={'scene ' + node.id} onClick={() => onSelect(node.id)}>{node.id}</button>)}</div> }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: test.error }, modal: { confirm: vi.fn() } }) },
  Spin: () => <span>loading</span>,
  Button: ({ children, onClick, disabled, loading }: { children: ReactNode; onClick?: () => void; disabled?: boolean; loading?: boolean }) => <button disabled={disabled || loading} onClick={onClick}>{children}</button>,
  Input: Object.assign((props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />, { TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> }),
  Select: ({ value, onChange, options, ...props }: { value: string; onChange: (value: string) => void; options: { value: string; label: string }[]; 'aria-label'?: string }) => <select aria-label={props['aria-label'] || "recipient"} value={value} onChange={event => onChange(event.target.value)}>{options.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>,
}))
function chooseConversation(id: string) {
  if (test.phone && !screen.queryByRole('navigation', { name: 'swarm.conversation.list' })) {
    const back = screen.queryByRole('button', { name: 'test.back' })
    if (back) fireEvent.click(back)
    fireEvent.click(screen.getByRole('button', { name: 'swarm.conversation.list' }))
  }
  const name = id === 'main' ? 'Main' : id === 'group' ? 'swarm.managed.tab.chat' : test.data?.members?.find(member => member.id === id)?.name || test.data?.work.find(work => work.id === id)?.member_name || id
  fireEvent.click(within(screen.getByRole('navigation', { name: 'swarm.conversation.list' })).getByRole('button', { name }))
}
function showScene() {
  const toggle = screen.getByRole('button', { name: 'swarm.workspace.open' })
  if (toggle.getAttribute('aria-expanded') !== 'true') fireEvent.click(toggle)
  const tab = screen.getByRole('button', { name: 'swarm.managed.tab.studio' })
  if (tab.getAttribute('aria-pressed') !== 'true') fireEvent.click(tab)
}
function showTasks() {
  const toggle = screen.getByRole('button', { name: 'swarm.workspace.open' })
  if (toggle.getAttribute('aria-expanded') !== 'true') fireEvent.click(toggle)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.tab.board' }))
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.all' }))
}
function snapshot(): SwarmSnapshot {
  return { id: 'sw-one', name: 'Team', goal: 'Goal', mainConversationId: 'main', revision: 2, sequence: 10, paused: false, archived: false, state: 'review', target: {}, posts: [{ id: 1, author: 'frontend', text: 'Task update', taskId: 'task', createdMs: 1 }], mainMessages: [{ id: 'reply', role: 'assistant', text: 'Main response', createdMs: 10 }], work: [{ id: 'work', member_name: 'frontend', executor: 'codex', title: 'Build page', goal: 'Full instructions', acceptance: 'Verify results', integration: 0, task_id: 'task', revision: 1, state: 'waiting_user', dispatch_error: null, dependencies: [], attempt: { runId: 'run', state: 'verifying', summary: 'Reported outcome' } }] }
}
beforeEach(() => { test.sessions = [{ name: "real-session", agent: "codex", dormant: false }]; test.mainTurns = null; test.nativeSessions = []; localStorage.clear(); test.phone = false; test.data = snapshot(); test.api.mockReset().mockResolvedValue({ data: {} }); test.refresh.mockReset().mockResolvedValue(undefined); test.error.mockReset(); test.openTask.mockReset() })
afterEach(cleanup)
it('embeds the same managed workspace without an extra page return action', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'common.back' })).toBeNull()
  expect(screen.queryAllByRole('combobox')).toHaveLength(0)
  expect(within(screen.getByRole('navigation', { name: 'swarm.conversation.list' })).getByRole('button', { name: 'Main' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: 'swarm.managed.tab.board' })).toBeTruthy()
})
it('keeps Main discussion separate from undispatched members with no task identity', () => {
  test.data = { ...test.data!, posts: [{ id: 1, author: 'human', text: 'Discuss with Main', taskId: null, createdMs: 5 }], work: test.data!.work.map(item => ({ ...item, task_id: null, revision: null, attempt: null })) }
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('group')
  expect(screen.getByText('Discuss with Main')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'swarm.managed.replyMember' })).toBeNull()
})
it('shows a failed group delivery and opens the same Main without retrying', () => {
  test.data = { ...test.data!, posts: [{ id: 2, author: 'human', text: 'Check this result', createdMs: 5, deliveryState: 'accepted', mainTurn: { id: 'shared-turn', conversationId: 'main', state: 'failed' } }] }
  const renderMain = vi.fn((cid: string) => <div>{'original ' + cid}</div>)
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} renderMain={renderMain} />)
  chooseConversation('group')
  expect(screen.getByRole('alert').textContent).toContain('swarm.chat.mainReplyFailed')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'swarm.chat.viewMain' }))
  expect(renderMain).toHaveBeenLastCalledWith('main')
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
  chooseConversation('group')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep my draft')
  expect(test.api).not.toHaveBeenCalled()
})
it('does not broadcast private or foreign Main failures to the group', () => {
  test.data = { ...test.data!, mainState: 'failed', posts: [{ id: 2, author: 'human', text: 'A different Main', createdMs: 5, mainTurn: { id: 'foreign-turn', conversationId: 'foreign-main', state: 'failed' } }] }
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('group')
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('button', { name: 'swarm.chat.viewMain' })).toBeNull()
})
it('keeps a reported task in review and opens the original task outputs', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  showTasks()
  fireEvent.click(screen.getByRole('button', { name: /Build page/ }))
  expect(screen.getAllByText('swarm.managed.state.waiting_user').length).toBeGreaterThan(0)
  expect(screen.getByText('Reported outcome').closest('details')?.open).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.openTask' }))
  expect(test.openTask).toHaveBeenCalledWith('tasks', 'task')
  expect(test.api).not.toHaveBeenCalled()
})

it('preserves draft across mobile tabs and Enter never submits a message', () => {
  test.phone = true
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('group')
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'Keep this draft' } }); fireEvent.keyDown(input, { key: 'Enter' })
  showTasks()
  chooseConversation('group')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep this draft')
  expect(test.api).not.toHaveBeenCalled()
})
it('retries unconfirmed member steering with its original key and revision', async () => {
  test.api.mockRejectedValueOnce(new Error('unknown'))
  const view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('work')
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
it('does not silently redirect a member message containing a Main mention', async () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('work')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@leader Keep the goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.error).toHaveBeenCalledWith('swarm.conversation.recipientConflict'))
  expect(test.api).not.toHaveBeenCalled()
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('work')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('@leader Keep the goal')
})

it('offers leader mention completion and preserves a failed memory edit', async () => {
  test.data = { ...test.data!, teamMemory: { available: true, content: 'Existing decision', sha256: 'a'.repeat(64), source: '.roami/okr/memory/team.md' } }
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('group')
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
  showTasks()
  fireEvent.click(screen.getByRole('button', { name: /Build page/ }))
  const report = screen.getByText('swarm.managed.report').closest('details')
  expect(report?.open).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.memory' }))
  await waitFor(() => expect(screen.getByRole('dialog').querySelector('.swarm-memory')).toBeTruthy())
})
it('requires a stored receipt and confirmed target before explicit external acceptance', async () => {
  test.data = { ...test.data!, work: test.data!.work.map(item => ({ ...item, deliverables: [{ kind: 'external_action', description: 'Confirm publication' }], evidence: { artifacts: [{ id: 'receipt', name: 'Publication receipt', mimeType: 'image/png', sizeBytes: 10, sha256: 'a'.repeat(64), downloadUrl: '/api/agent/artifacts/receipt/content' }], verification: { kind: 'declared_deliverables', state: 'awaiting_acceptance', externalAction: 'unconfirmed' } } })) }
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  showTasks()
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
  expect(screen.queryByTestId('studio-selection')).toBeNull()
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
it('shows Main chat and collaboration together without the duplicate duty list', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.queryByRole('region', { name: 'swarm.relations.title' })).toBeNull()
  expect(document.querySelector('.conversation-composer')).toBeTruthy()
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
  expect(screen.getByTestId('studio-selection')).toBeTruthy()
  expect(document.querySelector('.swarm-relation-duty')).toBeNull()
  expect(within(screen.getByRole('navigation', { name: 'swarm.managed.workspace' })).getAllByRole('button')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: 'scene main' }))
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
  expect(screen.getByRole('textbox')).toBeTruthy()
  expect(test.api).not.toHaveBeenCalled()
})

it('collapses collaboration without unmounting chat or focusing its input', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'Keep this Main draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'swarm.workspace.open' }))
  expect(screen.queryByTestId('studio-selection')).toBeNull()
  expect(screen.getByRole('textbox')).toBe(input)
  expect((input as HTMLTextAreaElement).value).toBe('Keep this Main draft')
  expect(document.activeElement).not.toBe(input)
  expect(document.querySelector('.swarm-conversation-workspace')?.getAttribute('data-scene')).toBe('false')
  showScene()
  expect(screen.getByTestId('studio-selection')).toBeTruthy()
  expect(test.api).not.toHaveBeenCalled()
})

it('maps the old collaboration tab to the unified Main workspace on reopen', () => {
  localStorage.setItem('roami.swarm.panel.v2:/agent/swarms/sw-one', 'studio')
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
  expect(screen.getByTestId('studio-selection')).toBeTruthy()
})

it('lists real task state in the right workbench without replacing the conversation', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  const chat = screen.getByRole('textbox')
  fireEvent.change(chat, { target: { value: 'Main draft' } })
  showTasks()
  const list = screen.getByRole('list', { name: 'swarm.managed.tab.board' })
  expect(within(list).getByRole('button', { name: /Build page/ }).textContent).toContain('swarm.managed.state.waiting_user')
  expect(list.closest('aside')?.className).toBe('swarm-collaboration-pane')
  expect(document.querySelector('.swarm-board-columns')).toBeNull()
  expect(document.querySelector('.swarm-managed > .tt-pagehead')).toBeNull()
  expect(screen.getByRole('textbox')).toBe(chat)
  expect((chat as HTMLTextAreaElement).value).toBe('Main draft')
  fireEvent.click(within(list).getByRole('button', { name: /Build page/ }))
  expect(screen.getByRole('textbox')).toBe(chat)
  expect(document.querySelector('.swarm-work-detail')?.closest('aside')).toBeTruthy()
  expect(test.api).not.toHaveBeenCalled()
})

it('opens an assigned member through its existing task page without sending or launching', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('work')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.relations.openWork' }))
  expect(test.openTask).toHaveBeenCalledWith('tasks', 'task')
  expect(test.api).not.toHaveBeenCalled()
})
it.each(['scene', 'directory', 'reply'])('selects a member via %s while keeping the Main draft private', async source => {
  test.data!.work[0].attempt!.sessionId = 'real-session'
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@leader Keep this Main draft' } })
  if (source === 'scene') {
    showScene()
    fireEvent.click(screen.getByRole('button', { name: 'scene work' }))
  } else if (source === 'directory') chooseConversation('work')
  else { chooseConversation('group'); fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.replyMember' })) }
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('work')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Member instruction' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledOnce())
  expect(test.api.mock.calls[0][2]).toMatchObject({ workId: 'work', taskRevision: 1, text: 'Member instruction' })
  chooseConversation('main')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('@leader Keep this Main draft')
})
it('keeps independent drafts when explicitly switching Main and member chats', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Main draft' } })
  chooseConversation('work')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@frontend Member draft' } })
  chooseConversation('main')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Main draft')
  chooseConversation('work')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('@frontend Member draft')
  expect(test.api).not.toHaveBeenCalled()
})

it.each([false, true])('keeps undispatched plans local and routes adjustments to Main (phone=%s)', phone => {
  test.phone = phone
  test.data = { ...test.data!, work: test.data!.work.map(item => ({ ...item, task_id: null, revision: null, attempt: null })) }
  const term = vi.fn()
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={term} />)
  expect(screen.queryByRole('button', { name: 'swarm.relations.openWork' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'swarm.relations.chat' })).toBeNull()
  showTasks()
  fireEvent.click(screen.getByRole('button', { name: /Build page/ }))
  const detail = phone ? within(screen.getByRole('dialog')) : within(document.querySelector('.swarm-work-detail') as HTMLElement)
  expect(detail.getByText('Full instructions').closest('details')?.open).toBe(false)
  chooseConversation('main')
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
  expect(test.openTask).not.toHaveBeenCalled()
  expect(term).not.toHaveBeenCalled()
  expect(test.api).not.toHaveBeenCalled()
})
it('keeps the selected member stable while editing recognized mentions', () => {
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('work')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@MAIN This is for Main' } })
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('work')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '@frontend This is for the member' } })
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('work')
  expect(test.api).not.toHaveBeenCalled()
})

it('keeps the team and shared chat in one workspace and scopes real task posts by member', () => {
 test.data = { ...test.data!, posts: [{id:1,author:'frontend',text:'Member evidence',taskId:'task',createdMs:20},{id:2,author:'old-member',text:'Archived task post',taskId:'old-task',createdMs:15}] }
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
 const workspace = screen.getByRole('navigation',{name:'swarm.managed.workspace'})
 expect(within(workspace).queryByRole('button',{name:'swarm.managed.tab.chat'})).toBeNull()
 expect(screen.queryByRole('region',{name:'swarm.relations.title'})).toBeNull()
 chooseConversation('group')
 expect(screen.getByText('Member evidence')).toBeTruthy()
 chooseConversation('work')
 expect(screen.getByText('Member evidence')).toBeTruthy()
 expect(screen.queryByText('Main response')).toBeNull()
 expect(screen.queryByText('Archived task post')).toBeNull()
 chooseConversation('main')
 expect(screen.queryByText('Main response')).toBeNull()
 expect(screen.queryByText('Archived task post')).toBeNull()
 chooseConversation('group')
 expect(screen.getByText('Archived task post')).toBeTruthy()
 expect(test.api).not.toHaveBeenCalled()
})
it('opens phone collaboration as a secondary page and preserves the mounted conversation', () => {
  test.phone = true
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.queryByTestId('studio-selection')).toBeNull()
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'Main phone draft' } })
  showScene()
  expect(screen.getByTestId('studio-selection').getAttribute('data-active')).toBe('true')
  expect(screen.queryByRole('dialog')).toBeTruthy()
  expect(screen.getByRole('textbox')).toBe(input)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.workspace.open' }))
  expect(screen.queryByTestId('studio-selection')).toBeNull()
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Main phone draft')
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
})

it('keeps the phone member identity in the heading and puts secondary details in More', () => {
  test.phone = true
  test.data = { ...snapshot(), memberProtocol: 1, members: [{ id: 'member', swarm_id: 'sw-one', name: 'frontend', executor: 'codex', dutyPreview: 'Build', workId: 'work', taskId: 'task', taskRevision: 1, state: 'waiting_user', memoryPath: '', roundCount: 1 }] }
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('member')
  const heading = document.querySelector('.swarm-conversation-head')!
  expect(heading.querySelector('strong')?.textContent).toBe('frontend')
  expect(heading.querySelector('small')?.textContent).toBe('swarm.managed.state.waiting_user')
  expect(heading.querySelector('.swarm-detail-actions')).toBeNull()
  const more = heading.querySelector('details')!
  expect(more.querySelector('button')?.textContent).toBe('swarm.member.details')
  expect(test.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})

it('returns from a phone collaboration member to that conversation without sending', () => {
  test.phone = true
  test.data!.work[0].attempt!.sessionId = 'real-session'
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  showScene()
  fireEvent.click(screen.getByRole('button', { name: 'scene work' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('work')
  expect(test.api).not.toHaveBeenCalled()
})

it('opens a concrete current conversation only after reading its real task identity', async () => {
 const session = vi.fn()
 test.api.mockResolvedValueOnce({data:{task:{id:'task',revision:1,executor:'codex'},attempts:[{id:'run',revision:1,state:'succeeded',sessionId:'real-session'}]}})
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 chooseConversation('work')
 fireEvent.click(screen.getByRole('button',{name:'swarm.managed.openSession'}))
 await waitFor(()=>expect(session).toHaveBeenCalledWith('real-session'))
 expect(test.api).toHaveBeenCalledOnce()
 expect(test.api).toHaveBeenCalledWith('GET','/agent/tasks/task')
 expect(test.openTask).not.toHaveBeenCalled()
})
it.each(['closed','changed','revision'])('keeps a %s conversation on its real task detail instead of opening an obsolete session', async kind => {
 const session = vi.fn()
 test.api.mockResolvedValueOnce({data:{task:{id:'task',revision:1,executor:'codex'},sessionClosure:kind==='closed'?{state:'closed'}:null,attempts:[{id:kind==='changed'?'new-run':'run',revision:kind==='revision'?0:1,sessionId:'obsolete'}]}})
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 chooseConversation('work')
 fireEvent.click(screen.getByRole('button',{name:'swarm.managed.openSession'}))
 await waitFor(()=>expect(test.openTask).toHaveBeenCalledWith('tasks','task'))
 expect(session).not.toHaveBeenCalled()
 expect(test.api).toHaveBeenCalledOnce()
})

it('enters a bound native conversation instead of creating a new agent', async () => {
 test.data!.work[0].executor = 'native'
 const session = vi.fn()
 test.api.mockResolvedValueOnce({data:{task:{id:'task',revision:1,executor:'native',nativeSession:{id:'native-session',conversationId:'native-conversation'}},attempts:[{id:'run',revision:1,state:'succeeded'}]}})
 render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 chooseConversation('work')
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
 chooseConversation('work')
 fireEvent.click(screen.getByRole('button', {name:'swarm.managed.openSession'}))
 expect(test.api).toHaveBeenCalledWith('GET','/agent/tasks/task')
 test.data = {...test.data!,work:test.data!.work.map(work=>({...work,revision:2,attempt:{...work.attempt!,runId:'run-new'}}))}
 view.rerender(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
 resolve({data:{task:{id:'task',revision:1,executor:'codex'},attempts:[{id:'run',revision:1,sessionId:'obsolete-session'}]}})
 await waitFor(()=>expect(test.openTask).toHaveBeenCalledWith('tasks','task'))
 expect(session).not.toHaveBeenCalled()
 expect(test.api).toHaveBeenCalledOnce()
})


it('opens phone contacts as a secondary page and returns to the selected member thread', () => {
  test.phone = true
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.conversation.list' }))
  const contacts = screen.getByRole('dialog')
  expect(within(contacts).getByRole('navigation', { name: 'swarm.conversation.list' })).toBeTruthy()
  expect(screen.queryByTestId('studio-selection')).toBeNull()
  fireEvent.click(within(contacts).getByRole('button', { name: 'frontend', pressed: false }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('work')
  expect(document.activeElement?.tagName).not.toBe('TEXTAREA')
})

it('does not open a recorded CLI session missing from the shared live-session overview', async () => {
  const session = vi.fn()
  test.api.mockResolvedValueOnce({ data: { task: { id: 'task', revision: 1, executor: 'codex' }, attempts: [{ id: 'run', revision: 1, sessionId: 'gone-session' }] } })
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={session} />)
  chooseConversation('work')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.openSession' }))
  await waitFor(() => expect(test.openTask).toHaveBeenCalledWith('tasks', 'task'))
  expect(session).not.toHaveBeenCalled()
})


it('shows only confirmed live instances in the scene and keeps historical and planned work in the roster', () => {
  test.data!.work[0].attempt!.sessionId = 'real-session'
  test.data!.work.push({ ...test.data!.work[0], id: 'gone', member_name: 'old-role', attempt: { ...test.data!.work[0].attempt!, sessionId: 'gone-session' } }, { ...test.data!.work[0], id: 'planned', member_name: 'future-role', task_id: null, attempt: null })
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  showScene()
  expect(screen.getByTestId('studio-selection').getAttribute('data-nodes')).toBe('main,work')
  expect(screen.getByRole('button', { name: 'old-role', pressed: false })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'future-role', pressed: false })).toBeTruthy()
  expect(screen.queryAllByRole('combobox')).toHaveLength(0)
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
  showScene()
  expect(screen.getByTestId('studio-selection').getAttribute('data-nodes')).toBe(nodes)
})


it('keeps a missing historical recipient draft out of Main without deleting it', () => {
  const saved = JSON.stringify({ draft: 'Keep this request', scope: 'gone', recipient: 'gone' })
  localStorage.setItem('roami.swarm.draft:/agent/swarms/sw-one', saved)
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('main')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
  expect((screen.getByRole('button', { name: 'common.send' }) as HTMLButtonElement).disabled).toBe(true)
  expect(localStorage.getItem('roami.swarm.draft:/agent/swarms/sw-one')).toBe(saved)
  expect(test.api).not.toHaveBeenCalled()
})

function registeredTeam() {
  test.data!.memberProtocol = 1
  test.data!.work[0].memberId = 'role'
  test.data!.work[0].attempt!.sessionId = 'real-session'
  test.api.mockImplementation((method: string) => Promise.resolve({ data: method === 'GET' ? { task: { id: 'task', revision: 1, executor: 'codex' }, attempts: [{ id: 'run', revision: 1, sessionId: 'real-session' }] } : {} }))
  test.data!.members = [{ id: 'role', swarm_id: 'sw-one', name: 'frontend', executor: 'codex', dutyPreview: 'Maintain the interface', workId: 'work', taskId: 'task', taskRevision: 1, state: 'waiting_user', memoryPath: 'members/role/memory.md', roundCount: 3 }]
}
it('restores an exact old work draft to the stable role without changing its destination', async () => {
  registeredTeam()
  localStorage.setItem('roami.swarm.draft:/agent/swarms/sw-one', JSON.stringify({ draft: 'Keep working', scope: 'work' }))
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('role')
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('role')
  expect((await screen.findByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep working')
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledTimes(2))
  expect(test.api.mock.calls[1][2]).toMatchObject({ workId: 'work', taskRevision: 1 })
  expect(within(screen.getByRole('navigation', { name: 'swarm.conversation.list' })).getAllByRole('button', { name: 'frontend' })).toHaveLength(1)
})
it('keeps an idle registered role visible but never sends its draft through Main implicitly', () => {
  registeredTeam(); test.data!.work = []
  Object.assign(test.data!.members![0], { workId: null, taskId: null, taskRevision: null, state: 'unassigned' })
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'frontend', pressed: false }))
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('role')
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByRole('button', { name: 'common.send' })).toBeNull()
  expect(screen.getByText('swarm.member.unassigned')).toBeTruthy()
  expect(test.api).not.toHaveBeenCalled()
})
it('does not reconstruct people from tasks when the registered team response is incomplete', () => {
  registeredTeam(); delete test.data!.members
  localStorage.setItem('roami.swarm.draft:/agent/swarms/sw-one', JSON.stringify({ draft: 'Do not redirect', scope: 'work' }))
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.queryByRole('option', { name: 'frontend' })).toBeNull()
  expect((screen.getByRole('button', { name: 'common.send' }) as HTMLButtonElement).disabled).toBe(true)
  expect(test.api).not.toHaveBeenCalled()
})
it('a failed deferred lookup returns to the current task instead of the old task', async () => {
  registeredTeam()
  let reject!: (reason: Error) => void
  test.api.mockImplementationOnce(() => new Promise((_resolve, failure) => { reject = failure }))
  const terminal = vi.fn(), view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={terminal} />)
  chooseConversation('role')
  test.data = { ...test.data!, work: [{ ...test.data!.work[0], task_id: 'current-task' }], members: [{ ...test.data!.members![0], taskId: 'current-task' }] }
  view.rerender(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={terminal} />)
  reject(new Error('network failed'))
  fireEvent.click(await screen.findByRole('button', { name: 'swarm.managed.openTask' }))
  await waitFor(() => expect(test.openTask).toHaveBeenCalledWith('tasks', 'current-task'))
  expect(test.openTask).not.toHaveBeenCalledWith('tasks', 'task')
  expect(terminal).not.toHaveBeenCalled()
})
it('loads role history only on demand and preserves the chat recipient and draft', async () => {
  registeredTeam()
  const implementation = test.api.getMockImplementation()!
  test.api.mockImplementation((method: string, path: string) => path === '/agent/swarms/sw-one/members/role' ? Promise.resolve({ data: { member: { ...test.data!.members![0], duty: 'Durable responsibility' }, rounds: { items: [], hasMore: false, nextBefore: null } } }) : implementation(method, path))
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  chooseConversation('role')
  fireEvent.change(await screen.findByRole('textbox'), { target: { value: 'Preserve this draft' } })
  expect(test.api.mock.calls.some(call => call[1].includes('/members/'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.member.details' }))
  expect(await screen.findByText('Durable responsibility')).toBeTruthy()
  expect(test.api.mock.calls.filter(call => call[1].includes('/members/'))).toEqual([['GET', '/agent/swarms/sw-one/members/role']])
  fireEvent.click(screen.getByRole('button', { name: 'common.close' }))
  expect((await screen.findByRole('textbox') as HTMLTextAreaElement).value).toBe('Preserve this draft')
  expect(document.querySelector('.swarm-conversation-pane')?.getAttribute('data-recipient')).toBe('role')
})

it('uses the actual private Main turn for the scene and releases it outside the scene', () => {
  test.mainTurns = [{ state: 'running' }]
  test.data!.mainState = 'idle'
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  showScene()
  expect(screen.getByTestId('studio-selection').getAttribute('data-main-state')).toBe('running')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.workspace.open' }))
  expect(screen.queryByTestId('studio-selection')).toBeNull()
})

it.each(['executor', 'project', 'unknown closure'])('keeps a %s mismatch on task details instead of opening a session', async mismatch => {
  test.data!.target = { projectId: 'bound-project' }
  const task = { id: 'task', revision: 1, executor: mismatch === 'executor' ? 'claude' : 'codex', projectId: mismatch === 'project' ? 'another-project' : 'bound-project' }
  test.api.mockResolvedValueOnce({ data: { task, attempts: [{ id: 'run', revision: 1, sessionId: 'real-session' }], sessionClosure: mismatch === 'unknown closure' ? { state: 'unknown' } : null } })
  const terminal = vi.fn()
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={terminal} />)
  chooseConversation('work')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.openSession' }))
  await waitFor(() => expect(test.openTask).toHaveBeenCalledWith('tasks', 'task'))
  expect(terminal).not.toHaveBeenCalled()
})

it('does not animate a CLI session whose live executor differs from the member', () => {
  test.data!.work[0].attempt!.sessionId = 'real-session'
  test.data!.work[0].executor = 'claude'
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={vi.fn()} />)
  showScene()
  expect(screen.getByTestId('studio-selection').getAttribute('data-nodes')).toBe('main')
  expect(screen.getByRole('button', { name: 'frontend', pressed: false })).toBeTruthy()
})


it.each([false, true])('opens the original legacy member using host project identity (phone=%s)', async phone => {
  test.phone = phone
  test.data!.target = { projectId: 'bound-project' }
  test.sessions[0].projectKey = 'bound-project'
  test.api.mockResolvedValueOnce({ data: { task: { id: 'task', revision: 1, executor: 'codex', projectId: null, origin_conversation_id: 'main' }, attempts: [{ id: 'run', revision: 1, sessionId: 'real-session' }] } })
  const terminal = vi.fn()
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={terminal} />)
  chooseConversation('work')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.openSession' }))
  await waitFor(() => expect(terminal).toHaveBeenCalledWith('real-session'))
  expect(test.openTask).not.toHaveBeenCalled()
})

it.each(['missing project', 'other project', 'other Main', 'explicit conflict', 'host conflict', 'native alias', 'dormant', 'ambiguous session'])('rejects legacy session entry with %s', async mismatch => {
  test.data!.target = { projectId: 'bound-project' }
  test.sessions[0].projectKey = ['other project', 'host conflict'].includes(mismatch) ? 'another-project' : mismatch === 'missing project' ? undefined : 'bound-project'
  if (mismatch === 'dormant') test.sessions[0].dormant = true
  if (mismatch === 'ambiguous session') test.sessions.push({ ...test.sessions[0] })
  test.api.mockResolvedValueOnce({ data: { task: { id: 'task', revision: 1, executor: 'codex', nativeSession: mismatch === 'native alias' ? { id: 'native', conversationId: 'worker' } : null, projectId: mismatch === 'explicit conflict' ? 'another-project' : mismatch === 'host conflict' ? 'bound-project' : null, origin_conversation_id: mismatch === 'other Main' ? 'another-main' : 'main' }, attempts: [{ id: 'run', revision: 1, sessionId: 'real-session' }] } })
  const terminal = vi.fn()
  render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={terminal} />)
  chooseConversation('work')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.openSession' }))
  await waitFor(() => expect(test.openTask).toHaveBeenCalledWith('tasks', 'task'))
  expect(terminal).not.toHaveBeenCalled()
})


it.each(['project', 'Main'])('rejects a %s binding changed during the session lookup', async changed => {
  test.data!.target = { projectId: 'bound-project' }
  test.sessions[0].projectKey = 'bound-project'
  let resolve!: (value: unknown) => void
  test.api.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const terminal = vi.fn(), view = render(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={terminal} />)
  chooseConversation('work')
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.openSession' }))
  test.data = { ...test.data!, ...(changed === 'project' ? { target: { projectId: 'another-project' } } : { mainConversationId: 'another-main' }) }
  view.rerender(<ManagedSwarm id="sw-one" onBack={vi.fn()} openTerm={terminal} />)
  resolve({ data: { task: { id: 'task', revision: 1, executor: 'codex', projectId: null, origin_conversation_id: 'main' }, attempts: [{ id: 'run', revision: 1, sessionId: 'real-session' }] } })
  await waitFor(() => expect(test.openTask).toHaveBeenCalledWith('tasks', 'task'))
  expect(terminal).not.toHaveBeenCalled()
})

it('focuses bound roles while retaining unknown history and exact task routing', async () => {
  const current = snapshot().work[0]; current.attempt!.sessionId = 'real-session'
  test.sessions[0].projectKey = 'project'
  test.api.mockImplementation((method: string) => Promise.resolve({ data: method === 'GET' ? { task: { id:'task', revision:1, executor:'codex', projectId:'project' }, attempts:[{ id:'run', revision:1, sessionId:'real-session' }] } : {} }))
  test.data = { ...snapshot(), target: { projectId: 'project' }, memberProtocol: 1, members: [
    { id: 'member', swarm_id: 'sw-one', name: 'frontend', executor: 'codex', dutyPreview: 'Build', workId: 'work', taskId: 'task', taskRevision: 1, state: 'waiting_user', memoryPath: '', roundCount: 1 },
    { id: 'old', swarm_id: 'sw-one', name: 'old-run', executor: 'codex', dutyPreview: 'Old', workId: 'old-work', taskId: 'old-task', taskRevision: 1, state: 'unknown', memoryPath: '', roundCount: 1 },
  ], work: [current, { ...current, id: 'old-work', task_id: 'old-task', title: 'Old unknown work', state: 'unknown' }] }
  const roles = [{ id: 'writer', name: 'Content', executor: 'codex', duty: 'Daily content', memberId: 'member' }]
  render(<ManagedSwarm id="sw-one" projectId="project" roles={roles} onBack={vi.fn()} openTerm={vi.fn()} />)
  const directory = screen.getByRole('navigation', { name: 'swarm.conversation.list' })
  expect(within(directory).getByRole('button', { name: 'Content' })).toBeTruthy()
  const history = directory.querySelector('details')!
  expect(history.open).toBe(false)
  expect(history.textContent).toContain('old-run')
  expect(history.textContent).toContain('swarm.managed.state.unknown')
  fireEvent.click(within(directory).getByRole('button', { name: 'Content' }))
  fireEvent.change(await screen.findByRole('textbox'), { target: { value: 'Continue this role' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.send' }))
  await waitFor(() => expect(test.api).toHaveBeenCalledWith('POST', '/agent/swarms/sw-one/messages', expect.objectContaining({ text: 'Continue this role', workId: 'work', taskRevision: 1 })))
  showTasks()
  expect(screen.queryByRole('button', { name: /Old unknown work/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'swarm.member.includeHistory' }))
  expect(screen.getByRole('button', { name: /Old unknown work/ })).toBeTruthy()
  expect(test.data.members).toHaveLength(2)
  expect(test.data.work[1].state).toBe('unknown')
})

it('does not expose a different project group behind configured role bindings', () => {
  test.data = { ...snapshot(), target: { projectId: 'foreign-project' }, memberProtocol: 1 }
  render(<ManagedSwarm id="sw-one" projectId="project" roles={[{ id: 'writer', memberId: 'member', name: 'Content', executor: 'codex', duty: 'Write' }]} onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.getByRole('alert').textContent).toContain('swarm.member.registryUnavailable')
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByRole('navigation', { name: 'swarm.conversation.list' })).toBeNull()
  expect(screen.queryByText('Task update')).toBeNull()
  expect(test.api).not.toHaveBeenCalled()
})

it('puts Group before Main, then the current members', () => {
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  const buttons = within(screen.getByRole('navigation', { name: 'swarm.conversation.list' })).getAllByRole('button')
  expect(buttons.map(button => button.getAttribute('aria-label')).slice(0, 3)).toEqual(['swarm.managed.tab.chat', 'Main', 'frontend'])
})
it('defaults to active work, filters by real state, and remembers the selection', () => {
  test.data!.work.push({ ...test.data!.work[0], id: 'active', title: 'In progress', state: 'running', attempt: { runId: 'active-run', state: 'running' } }, { ...test.data!.work[0], id: 'finished', title: 'Verified output', state: 'succeeded' })
  const view = render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.managed.tab.board' }))
  expect(screen.getByRole('button', { name: 'agent.task.filter.active' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: /In progress/ })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /Build page|Verified output/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.attention' }))
  expect(screen.getByRole('button', { name: /Build page/ })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /In progress|Verified output/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.all' }))
  expect(document.querySelectorAll('.swarm-task-row')).toHaveLength(3)
  view.unmount()
  render(<ManagedSwarm id="sw-one" embedded onBack={vi.fn()} openTerm={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'agent.task.filter.all' }).getAttribute('aria-pressed')).toBe('true')
  expect(document.querySelectorAll('.swarm-task-row')).toHaveLength(3)
})
