// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from 'antd'
import AgentChat from './AgentChat'
import OkrMainChat from '../projects/okr/OkrMainChat'
import { emptyConfiguration } from '../projects/okr/okr-workspace'
import { clearAgentDataCache } from './agent-data-cache'
import { projectAgentEvent, type AgentActivityItem, type AgentEvent, type AgentSnapshot } from './agent-protocol'

const state = vi.hoisted(() => ({ phone: false, api: vi.fn(), streams: new Map<string, ReadableStreamDefaultController<Uint8Array>>(), snapshots: new Map<string, any>() }))
vi.mock('../../api', () => ({ api: state.api, openEventStream: async (path: string, signal: AbortSignal) => {
  const cid = path.split('/')[3]
  return new Response(new ReadableStream<Uint8Array>({ start(controller) { state.streams.set(cid, controller); signal.addEventListener('abort', () => controller.close(), { once: true }) } }))
} }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: state.phone, size: state.phone ? 'compact' : 'expanded' }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null, currentNodeId: () => null, nodeApi: (path: string) => '/api' + path }))
vi.mock('./AgentTasks', () => ({ default: ({ cid }: { cid: string }) => <div>Tasks for {cid}</div> }))
vi.mock('../chat/VoiceInput', () => ({ default: () => null }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <div>{children}</div> }))
function snapshot(cid: string): AgentSnapshot { return { conversation: { id: cid, title: cid, active_branch_id: 'branch', updated_ms: 0 }, branchId: 'branch', turns: [], messages: [], snapshotCursor: 0 } }
beforeEach(() => {
  state.phone = false; clearAgentDataCache(); localStorage.clear(); state.streams.clear(); state.snapshots.clear(); state.api.mockReset()
  for (const cid of ['home', 'project-main']) state.snapshots.set(cid, snapshot(cid))
  state.api.mockImplementation(async (method, path, body) => {
    if (path === '/agent/status') return { data: { projectOkrMain: true, okrMessageContext: true } }
    if (path === '/agent/conversations') return { data: { id: 'project-main' } }
    if (method === 'POST' && path.endsWith('/messages') && body.text === '/tasks') return { data: { kind: 'ui_action', action: 'tasks' } }
    if (method === 'POST' && path.endsWith('/messages')) return { data: { kind: 'message', messageId: 'user', turnId: 'turn' } }
    if (path.includes('/messages?')) return { data: structuredClone(state.snapshots.get(path.split('/')[3])) }
    if (path === '/agent/model-settings') return { data: { main: { model: 'saved-model', images: true } } }
    return { data: {} }
  })
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); clearAgentDataCache(); vi.restoreAllMocks() })
async function emit(cid: string, event: AgentEvent) {
  state.snapshots.set(cid, projectAgentEvent(state.snapshots.get(cid), event).view)
  await act(async () => { state.streams.get(cid)!.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n')) })
}
it.each([false, true])('hides delegated execution from snapshot and SSE while keeping Main calls and results (phone=%s)', async phone => {
  state.phone = phone
  const main: AgentActivityItem = { id: 'tool:delegate', kind: 'tool', name: 'delegate', state: 'succeeded', anchorMessageId: '', startedMs: 1, updatedMs: 1 }
  const task: AgentActivityItem = { ...main, id: 'task:research', kind: 'task', name: 'native', title: 'Trending research', taskId: 'research', state: 'running', startedMs: 2 }
  const internal: AgentActivityItem = { ...main, id: 'tool:internal', name: 'bash', taskId: 'research', state: 'failed', startedMs: 3 }
  state.snapshots.set('home', { ...snapshot('home'), activities: [main, task, internal] })
  const page = render(<App><AgentChat cid="home" branch="" node={null} inbox={{ conversations: [{ id: 'home' }], refresh: vi.fn() } as any} inboxOpen={false} select={vi.fn()} notifications={vi.fn()} projects={[]} onSession={vi.fn()} onOverview={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.has('home')).toBe(true))
  expect(page.container.querySelector('[data-activity-id="tool:delegate"]')).toBeTruthy()
  expect(screen.getByText('Trending research')).toBeTruthy()
  expect(page.container.querySelector('[data-activity-id="tool:internal"]')).toBeNull()
  for (const [index, status] of ['running', 'succeeded', 'failed', 'unknown'].entries()) {
    await emit('home', { id: index + 1, kind: 'task.activity', branchId: 'branch', payload: { activity: { ...internal, id: 'tool:nested-' + index, taskId: 'nested', parentTaskId: 'research', state: status } } })
  }
  expect(page.container.querySelector('.agent-activity-group')).toBeNull()
  expect(page.container.querySelectorAll('.agent-activity')).toHaveLength(1)
  expect(page.container.querySelector('[data-state="failed"]')).toBeNull()
  await emit('home', { id: 5, kind: 'task.failed', branchId: 'branch', payload: { activity: { ...task, state: 'failed', updatedMs: 5 } } })
  expect(page.container.querySelector('[data-activity-id="task:research"][data-state="failed"]')).toBeTruthy()
  await emit('home', { id: 6, kind: 'message.started', branchId: 'branch', payload: { messageId: 'result', turnId: 'turn' } })
  await emit('home', { id: 7, kind: 'message.delta', branchId: 'branch', payload: { messageId: 'result', turnId: 'turn', offset: 0, text: 'Research result with deliverables' } })
  await emit('home', { id: 8, kind: 'message.completed', branchId: 'branch', payload: { messageId: 'result', turnId: 'turn' } })
  expect(screen.getByText('Research result with deliverables')).toBeTruthy()
  expect(state.snapshots.get('home').activities).toContainEqual(internal)
})
it('renders real incremental SSE before completion in both hosts and keeps the project destination independent', async () => {
  const select = vi.fn()
  render(<App><AgentChat cid="home" branch="" node={null} inbox={{ conversations: [{ id: 'home' }], refresh: vi.fn() } as any} inboxOpen={false} select={select} notifications={vi.fn()} projects={[]} onSession={vi.fn()} onOverview={vi.fn()} />
    <OkrMainChat embedded projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.size).toBe(2))
  fireEvent.change(screen.getByRole('textbox', { name: 'okr.chatInput' }), { target: { value: 'Project only' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[0] === 'POST' && call[1].endsWith('/messages'))).toHaveLength(1))
  expect(state.api.mock.calls.find(call => call[0] === 'POST' && call[1].endsWith('/messages'))![1]).toBe('/agent/conversations/project-main/messages')
  for (const cid of ['home', 'project-main']) {
    await emit(cid, { id: 1, kind: 'message.started', branchId: 'branch', payload: { messageId: 'answer', turnId: 'turn' } })
    await emit(cid, { id: 2, kind: 'message.delta', branchId: 'branch', payload: { messageId: 'answer', turnId: 'turn', offset: 0, text: 'First segment' } })
  }
  await waitFor(() => expect(screen.getAllByText('First segment')).toHaveLength(2))
  expect(screen.getAllByLabelText('agent.responding')).toHaveLength(2)
  await emit('project-main', { id: 3, kind: 'message.delta', branchId: 'other-branch', payload: { messageId: 'answer', offset: 13, text: 'wrong branch' } })
  expect(screen.queryByText(/wrong branch/)).toBeNull()
  await emit('project-main', { id: 4, kind: 'message.delta', branchId: 'branch', payload: { messageId: 'answer', offset: 13, text: ', next segment' } })
  await screen.findByText('First segment, next segment')
  expect(screen.getAllByLabelText('agent.responding')).toHaveLength(2)
  await emit('project-main', { id: 5, kind: 'message.completed', branchId: 'branch', payload: { messageId: 'answer', turnId: 'turn' } })
  await waitFor(() => expect(screen.getAllByLabelText('agent.responding')).toHaveLength(1))
  expect(select).not.toHaveBeenCalled()
  expect(document.querySelectorAll('.agent-reading')).toHaveLength(2)
  expect(document.querySelectorAll('.agent-workspace-rail')).toHaveLength(0)
})

it('opens project task commands in a scoped phone subpage and returns to the same Main', async () => {
  state.phone = true
  const origin = location.hash
  render(<App><OkrMainChat embedded projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.has('project-main')).toBe(true))
  fireEvent.change(screen.getByRole('textbox', { name: 'okr.chatInput' }), { target: { value: '/tasks' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByText('Tasks for project-main')
  expect(location.hash).toBe(origin)
  expect(screen.queryByText('Tasks for home')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'common.back' }))
  await waitFor(() => expect(screen.queryByText('Tasks for project-main')).toBeNull())
  expect(screen.getByRole('textbox', { name: 'okr.chatInput' })).toBeTruthy()
})

it('shows live tool execution and its result before the final reply in both hosts', async () => {
  const page = render(<App><AgentChat cid="home" branch="" node={null} inbox={{ conversations: [{ id: 'home' }], refresh: vi.fn() } as any} inboxOpen={false} select={vi.fn()} notifications={vi.fn()} projects={[]} onSession={vi.fn()} onOverview={vi.fn()} />
    <OkrMainChat embedded projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.size).toBe(2))
  for (const cid of ['home', 'project-main']) {
    await emit(cid, { id: 1, kind: 'message.started', branchId: 'branch', payload: { messageId: 'working', turnId: 'turn' } })
    await emit(cid, { id: 2, kind: 'message.delta', branchId: 'branch', payload: { messageId: 'working', turnId: 'turn', offset: 0, text: 'Checking the source.' } })
    await emit(cid, { id: 3, kind: 'tool.started', branchId: 'branch', payload: { activity: {
      id: 'tool:read', kind: 'tool', name: 'file_read', anchorMessageId: 'working', state: 'running', startedMs: 100, updatedMs: 100,
      preview: { input: { text: 'README.md', truncated: false }, output: null },
    } } })
  }
  expect(page.container.querySelectorAll('.agent-activity[data-state="running"]')).toHaveLength(2)
  expect(screen.queryByText('The source is verified.')).toBeNull()
  for (const button of screen.getAllByRole('button', { name: /agent.activity.read/ })) fireEvent.click(button)
  expect(screen.getAllByText('README.md')).toHaveLength(2)
  for (const cid of ['home', 'project-main']) await emit(cid, { id: 4, kind: 'tool.completed', branchId: 'branch', payload: { activity: {
    id: 'tool:read', kind: 'tool', name: 'file_read', anchorMessageId: 'working', state: 'succeeded', startedMs: 100, updatedMs: 200,
    preview: { input: { text: 'README.md', truncated: false }, output: { text: 'Verified source content', truncated: false } },
  } } })
  await waitFor(() => expect(screen.getAllByText('Verified source content')).toHaveLength(2))
  expect(page.container.querySelectorAll('.agent-activity[data-state="succeeded"]')).toHaveLength(2)
  expect(screen.queryByText('The source is verified.')).toBeNull()
  for (const cid of ['home', 'project-main']) {
    await emit(cid, { id: 5, kind: 'message.started', branchId: 'branch', payload: { messageId: 'answer', turnId: 'turn' } })
    await emit(cid, { id: 6, kind: 'message.delta', branchId: 'branch', payload: { messageId: 'answer', turnId: 'turn', offset: 0, text: 'The source is verified.' } })
    await emit(cid, { id: 7, kind: 'message.completed', branchId: 'branch', payload: { messageId: 'answer', turnId: 'turn' } })
  }
  expect(screen.getAllByText('The source is verified.')).toHaveLength(2)
  expect(screen.getAllByText('Verified source content')).toHaveLength(2)
})

it('streams provisional prose through both hosts, keeps checking visible, then replaces it once', async () => {
  render(<App><AgentChat cid="home" branch="" node={null} inbox={{ conversations: [{ id: 'home' }], refresh: vi.fn() } as any} inboxOpen={false} select={vi.fn()} notifications={vi.fn()} projects={[]} onSession={vi.fn()} onOverview={vi.fn()} />
    <OkrMainChat embedded projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.size).toBe(2))
  for (const cid of ['home', 'project-main']) {
    await emit(cid, { id: 1, kind: 'message.started', branchId: 'branch', payload: { messageId: 'draft', turnId: 'turn' } })
    await emit(cid, { id: 2, kind: 'reply.preview', branchId: 'branch', payload: { messageId: 'draft', turnId: 'turn', offset: 0, text: '正文😀', state: 'generating' } })
  }
  await waitFor(() => expect(screen.getAllByText('正文😀')).toHaveLength(2))
  expect(screen.getAllByText('agent.replyPreview.generating')).toHaveLength(2)
  expect(screen.queryByRole('button', { name: 'agent.remember' })).toBeNull()
  for (const cid of ['home', 'project-main']) {
    await emit(cid, { id: 3, kind: 'reply.preview', branchId: 'branch', payload: { messageId: 'draft', turnId: 'turn', offset: 3, text: '继续', state: 'checking' } })
    await emit(cid, { id: 4, kind: 'message.tool_calls', branchId: 'branch', payload: { messageId: 'draft', calls: [{ id: 'reply-call' }] } })
  }
  await waitFor(() => expect(screen.getAllByText('正文😀继续')).toHaveLength(2))
  expect(screen.getAllByText('agent.replyPreview.checking')).toHaveLength(2)
  for (const cid of ['home', 'project-main']) {
    await emit(cid, { id: 5, kind: 'message.started', branchId: 'branch', payload: { messageId: 'approved', turnId: 'turn' } })
    await emit(cid, { id: 6, kind: 'message.delta', branchId: 'branch', payload: { messageId: 'approved', turnId: 'turn', offset: 0, text: '正文😀继续' } })
    await emit(cid, { id: 7, kind: 'message.completed', branchId: 'branch', payload: { messageId: 'approved', turnId: 'turn' } })
  }
  await waitFor(() => expect(screen.getAllByText('正文😀继续')).toHaveLength(2))
  expect(document.querySelectorAll('.agent-reply-preview')).toHaveLength(0)
  expect(screen.getAllByRole('button', { name: 'agent.remember' })).toHaveLength(2)
})

it('withdraws a failed candidate and ignores its late preview event', async () => {
  render(<App><OkrMainChat embedded projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.has('project-main')).toBe(true))
  await emit('project-main', { id: 1, kind: 'message.started', branchId: 'branch', payload: { messageId: 'draft', turnId: 'turn' } })
  await emit('project-main', { id: 2, kind: 'reply.preview', branchId: 'branch', payload: { messageId: 'draft', turnId: 'turn', offset: 0, text: 'Provisional only', state: 'generating' } })
  await screen.findByText('Provisional only')
  await emit('project-main', { id: 3, kind: 'turn.failed', branchId: 'branch', payload: { turnId: 'turn', error: 'MODEL_HTTP_500' } })
  await waitFor(() => expect(screen.queryByText('Provisional only')).toBeNull())
  await emit('project-main', { id: 4, kind: 'reply.preview', branchId: 'branch', payload: { messageId: 'draft', turnId: 'turn', offset: 0, text: 'Late candidate', state: 'generating' } })
  expect(screen.queryByText('Late candidate')).toBeNull()
  expect(screen.queryByRole('button', { name: 'agent.remember' })).toBeNull()
})

it('recovers a phone reply announced by notifications when the chat stream misses completion', async () => {
  state.phone = true
  const props = { cid: 'home', branch: '', node: null, inboxOpen: false, select: vi.fn(), notifications: vi.fn(), projects: [], onSession: vi.fn(), onOverview: vi.fn() }
  const inbox = { conversations: [{ id: 'home' }], refresh: vi.fn(), cursor: 0 } as any
  const view = render(<App><AgentChat {...props} inbox={inbox} /></App>)
  await waitFor(() => expect(state.streams.has('home')).toBe(true))
  const completed = { ...snapshot('home'), snapshotCursor: 4, messages: [{ id: 'answer', branch_id: 'branch', role: 'assistant', status: 'completed', seq: 1, content: { text: 'Reply already delivered' } }] }
  state.snapshots.set('home', completed)
  view.rerender(<App><AgentChat {...props} inbox={{ ...inbox, cursor: 4 }} /></App>)
  await screen.findByText('Reply already delivered')
  expect(screen.queryByLabelText('agent.responding')).toBeNull()
})
