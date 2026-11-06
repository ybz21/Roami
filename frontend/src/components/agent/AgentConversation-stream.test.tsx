// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from 'antd'
import AgentChat from './AgentChat'
import OkrMainChat from '../projects/okr/OkrMainChat'
import { emptyConfiguration } from '../projects/okr/okr-workspace'
import { clearAgentDataCache } from './agent-data-cache'
import { projectAgentEvent, type AgentEvent, type AgentSnapshot } from './agent-protocol'

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
    if (path === '/agent/status') return { data: { projectOkrMain: true } }
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
