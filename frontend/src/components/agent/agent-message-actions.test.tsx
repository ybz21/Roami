// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from 'antd'
import AgentChat from './AgentChat'
import { clearAgentDataCache } from './agent-data-cache'
import { projectAgentEvent, type AgentEvent, type AgentSnapshot } from './agent-protocol'

const state = vi.hoisted(() => ({
  phone: false,
  api: vi.fn(),
  streams: new Map<string, ReadableStreamDefaultController<Uint8Array>>(),
  snapshots: new Map<string, AgentSnapshot>(),
}))

vi.mock('../../api', () => ({
  api: state.api,
  openEventStream: async (path: string, signal: AbortSignal) => {
    const cid = path.split('/')[3]
    return new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        state.streams.set(cid, controller)
        signal.addEventListener('abort', () => controller.close(), { once: true })
      },
    }))
  },
}))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: state.phone, size: state.phone ? 'compact' : 'expanded' }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null, currentNodeId: () => null, nodeApi: (path: string) => '/api' + path, nodePath: (path: string) => path }))
vi.mock('../chat/VoiceInput', () => ({ default: () => null }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <div>{children}</div> }))

function baseSnapshot(): AgentSnapshot {
  return {
    conversation: { id: 'home', title: 'Home', active_branch_id: 'branch', updated_ms: 0 },
    branchId: 'branch',
    turns: [],
    snapshotCursor: 1,
    messages: [
      { id: 'u1', branch_id: 'branch', role: 'user', status: 'completed', seq: 1, created_ms: 1_700_000_000_000, content: { text: 'Hello agent' } },
      { id: 'a1', branch_id: 'branch', role: 'assistant', status: 'completed', seq: 2, created_ms: 1_700_000_060_000, content: { text: 'Hello human' } },
    ],
  }
}

async function emit(cid: string, event: AgentEvent) {
  state.snapshots.set(cid, projectAgentEvent(state.snapshots.get(cid)!, event).view)
  await act(async () => {
    state.streams.get(cid)!.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n'))
  })
}

beforeEach(() => {
  state.phone = false
  clearAgentDataCache()
  localStorage.clear()
  state.streams.clear()
  state.snapshots.clear()
  state.api.mockReset()
  state.snapshots.set('home', baseSnapshot())
  state.api.mockImplementation(async (method, path) => {
    if (method === 'DELETE' && path.startsWith('/agent/conversations/home/messages/')) {
      const id = decodeURIComponent(path.split('/').pop()!)
      const current = state.snapshots.get('home')!
      state.snapshots.set('home', { ...current, messages: current.messages.filter(m => m.id !== id) })
      return { data: { messageId: id, deleted: true } }
    }
    if (path.includes('/messages?')) return { data: structuredClone(state.snapshots.get('home')) }
    if (path === '/agent/model-settings') return { data: { main: { model: 'saved-model', images: true } } }
    return { data: {} }
  })
  window.matchMedia = vi.fn().mockImplementation(() => ({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }))
})

afterEach(() => {
  cleanup()
  clearAgentDataCache()
  vi.restoreAllMocks()
})

it('copies user and assistant messages with visual feedback and loads full text when truncated', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

  const snap = baseSnapshot()
  snap.messages[1] = { ...snap.messages[1], contentTruncated: true, content: { text: 'Truncated preview...' } }
  state.snapshots.set('home', snap)
  const original = state.api.getMockImplementation()!
  state.api.mockImplementation(async (method, path, body) => {
    if (method === 'GET' && path === '/agent/conversations/home/messages/a1?branch=branch') {
      return { data: { ...snap.messages[1], contentTruncated: false, content: { text: 'Full untruncated reply' } } }
    }
    return original(method, path, body)
  })

  render(<App><AgentChat cid="home" branch="" node={null} inbox={{ conversations: [{ id: 'home' }], refresh: vi.fn() } as any} inboxOpen={false} select={vi.fn()} notifications={vi.fn()} projects={[]} onSession={vi.fn()} onOverview={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.has('home')).toBe(true))

  const copyButtons = screen.getAllByRole('button', { name: 'common.copy' })
  expect(copyButtons).toHaveLength(2)

  fireEvent.click(copyButtons[0])
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('Hello agent'))
  await waitFor(() => expect(screen.getAllByRole('button', { name: 'common.copied' })).toHaveLength(1))

  fireEvent.click(copyButtons[1])
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('Full untruncated reply'))
})

it.each([false, true])('confirms and deletes user/assistant messages and reacts to SSE message.deleted (phone=%s)', async phone => {
  state.phone = phone
  const inboxRefresh = vi.fn()
  render(<App><AgentChat cid="home" branch="" node={null} inbox={{ conversations: [{ id: 'home' }], refresh: inboxRefresh } as any} inboxOpen={false} select={vi.fn()} notifications={vi.fn()} projects={[]} onSession={vi.fn()} onOverview={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.has('home')).toBe(true))

  expect(screen.getByText('Hello agent')).toBeTruthy()
  expect(screen.getByText('Hello human')).toBeTruthy()
  const deleteButtons = screen.getAllByRole('button', { name: 'agent.deleteMessage' })
  expect(deleteButtons).toHaveLength(2)

  fireEvent.click(deleteButtons[1])
  const confirm = await screen.findByRole('button', { name: 'agent.deleteMessageAction' })
  fireEvent.click(confirm)

  await waitFor(() => expect(state.api).toHaveBeenCalledWith('DELETE', '/agent/conversations/home/messages/a1'))
  await waitFor(() => expect(screen.queryByText('Hello human')).toBeNull())
  expect(screen.getByText('Hello agent')).toBeTruthy()
  expect(inboxRefresh).toHaveBeenCalled()

  // Another client deleting u1 arrives over SSE and removes it immediately.
  await emit('home', { id: 2, kind: 'message.deleted', branchId: 'branch', payload: { messageId: 'u1', branchId: 'branch' } })
  await waitFor(() => expect(screen.queryByText('Hello agent')).toBeNull())
})

it('hides delete action on streaming messages and shows delete action on attachment-only messages', async () => {
  const snap = baseSnapshot()
  snap.messages = [
    { id: 'img-only', branch_id: 'branch', role: 'user', status: 'completed', seq: 1, created_ms: 1_700_000_000_000, content: { attachments: [{ id: 'att1', name: 'doc.pdf', sizeBytes: 1024, mimeType: 'application/pdf' }] } },
    { id: 'live', branch_id: 'branch', role: 'assistant', status: 'streaming', seq: 2, created_ms: 1_700_000_060_000, content: { text: 'Still typing' } },
  ]
  state.snapshots.set('home', snap)

  render(<App><AgentChat cid="home" branch="" node={null} inbox={{ conversations: [{ id: 'home' }], refresh: vi.fn() } as any} inboxOpen={false} select={vi.fn()} notifications={vi.fn()} projects={[]} onSession={vi.fn()} onOverview={vi.fn()} /></App>)
  await waitFor(() => expect(state.streams.has('home')).toBe(true))

  const deleteButtons = screen.getAllByRole('button', { name: 'agent.deleteMessage' })
  expect(deleteButtons).toHaveLength(1)
  expect(screen.getByText('doc.pdf')).toBeTruthy()
  expect(screen.getByText('Still typing')).toBeTruthy()
})
