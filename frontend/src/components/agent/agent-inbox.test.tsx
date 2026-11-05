// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentInbox from './AgentInbox'
import { api } from '../../api'
import { clearAgentDataCache } from './agent-data-cache'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('./AgentReminders', () => ({ default: ({ conversationId }: { conversationId: string }) => <p data-conversation={conversationId}>Future reminder</p> }))
afterEach(() => { cleanup(); clearAgentDataCache(); vi.resetAllMocks() })
const notices = [
  { id: 4, conversation_id: 'main', branch_id: 'branch', message_id: 'message', title: 'New report', summary: 'Report ready: [交付文件](/api/file/raw?path=%2Fproject%2Fa-very-long-path', created_ms: 1, read: false },
  { id: 2, conversation_id: 'main', branch_id: 'branch', title: 'Old report', summary: '', created_ms: 1, read: true },
]
const inbox = () => ({ conversations: [{ id: 'main', title: 'Home', active_branch_id: 'branch', updated_ms: 0 }], notices: [], unread: 1, cursor: 4, unavailable: false, refresh: vi.fn() })
it('loads a short page only when opened and applies Unread on the server', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: { items: path.includes('unreadOnly=true') ? notices.slice(0, 1) : notices, nextCursor: null } }))
  const select = vi.fn()
  render(<AgentInbox inbox={inbox()} select={select} />)
  expect(screen.getByText('Future reminder')).toBeTruthy()
  expect(await screen.findByText('Report ready: 交付文件')).toBeTruthy()
  expect(screen.queryByText(/%2Fproject/)).toBeNull()
  expect(await screen.findByText('Old report')).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.unread' }))
  await screen.findByText('New report')
  expect(screen.queryByText('Future reminder')).toBeNull()
  expect(screen.queryByText('Old report')).toBeNull()
  fireEvent.click(screen.getByText('New report'))
  await waitFor(() => expect(select).toHaveBeenCalledWith('main', 'branch', 'message'))
})
it('marks all notices through the observed watermark without downloading every page', async () => {
  vi.mocked(api).mockResolvedValue({ data: { items: notices, nextCursor: '2' } })
  const state = inbox()
  render(<AgentInbox inbox={state} select={vi.fn()} />)
  await screen.findByText('New report')
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.readAll' }))
  await waitFor(() => expect(state.refresh).toHaveBeenCalled())
  expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/main/read', { eventId: 4 })
  expect(vi.mocked(api).mock.calls.some(call => call[1].includes('before='))).toBe(false)
  expect(screen.getByText('Future reminder')).toBeTruthy()
})
it('exposes a failed read acknowledgement without claiming success', async () => {
  vi.mocked(api).mockImplementation(async method => { if (method === 'POST') throw new Error('offline'); return { data: { items: notices, nextCursor: null } } })
  render(<AgentInbox inbox={inbox()} select={vi.fn()} />)
  await screen.findByText('New report')
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.readAll' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
})
it('does not report an empty inbox while the first page is pending or failed', async () => {
  vi.mocked(api).mockRejectedValue(new Error('offline'))
  render(<AgentInbox inbox={inbox()} select={vi.fn()} />)
  expect(screen.queryByText('agent.noNotifications')).toBeNull()
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByText('agent.noNotifications')).toBeNull()
})

it('scopes a conversation workspace on the server and acknowledges only that conversation', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.includes('/summary') ? { conversationId: 'main', unread: 1, cursor: 4 } : { items: [...notices, { ...notices[0], id: 5, conversation_id: 'project-main', title: 'Another project' }], nextCursor: null } }))
  render(<AgentInbox conversationId="main" inbox={inbox()} select={vi.fn()} />)
  await screen.findByText('New report')
  expect(screen.queryByText('Another project')).toBeNull()
  expect(api).toHaveBeenCalledWith('GET', expect.stringContaining('conversationId=main'), undefined, expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.readAll' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/main/read', { eventId: 4 }))
  expect(vi.mocked(api).mock.calls.some(([method, path]) => method === 'POST' && path === '/agent/notifications/read')).toBe(false)
})

it('limits the Home entry to its own instance even if a response includes OKR messages', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.includes('/summary') ? { conversationId: 'main', unread: 1, cursor: 4 } : { items: [...notices, { ...notices[0], id: 900, conversation_id: 'okr-main', title: 'OKR delivery' }], nextCursor: null } }))
  const state = { ...inbox(), unread: 99, cursor: 900 }, select = vi.fn()
  render(<AgentInbox inbox={state} select={select} />)
  await screen.findByText('New report')
  expect(screen.queryByText('OKR delivery')).toBeNull()
  expect(screen.getByText('Future reminder').getAttribute('data-conversation')).toBe('main')
  expect(vi.mocked(api).mock.calls.every(([, path]) => path.includes('conversationId=main'))).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.readAll' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/main/read', { eventId: 4 }))
  fireEvent.click(screen.getByText('New report'))
  await waitFor(() => expect(select).toHaveBeenCalledWith('main', 'branch', 'message'))
})

it('does not fetch an owner-wide inbox before the Home instance is known or after it fails', async () => {
  const state = { ...inbox(), conversations: [] }
  const view = render(<AgentInbox inbox={state} select={vi.fn()} />)
  expect(api).not.toHaveBeenCalled()
  expect(screen.queryByText('Future reminder')).toBeNull()
  view.rerender(<AgentInbox inbox={{ ...state, unavailable: true }} select={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  expect(state.refresh).toHaveBeenCalledOnce()
  expect(api).not.toHaveBeenCalled()
})

it('discards the previous instance while the next instance is loading', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => path.includes('conversationId=next') ? new Promise(() => {}) : { data: { items: notices, nextCursor: null } })
  const view = render(<AgentInbox inbox={inbox()} select={vi.fn()} />)
  await screen.findByText('New report')
  view.rerender(<AgentInbox inbox={{ ...inbox(), conversations: [{ ...inbox().conversations[0], id: 'next' }] }} select={vi.fn()} />)
  expect(screen.queryByText('New report')).toBeNull()
  expect(screen.getByText('Future reminder').getAttribute('data-conversation')).toBe('next')
})
