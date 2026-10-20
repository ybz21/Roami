// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentInbox from './AgentInbox'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('./AgentReminders', () => ({ default: () => <p>Future reminder</p> }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const notices = [
  { id: 4, conversation_id: 'main', branch_id: 'branch', message_id: 'message', title: 'New report', content_json: '{"text":"Report ready"}', created_ms: 1, read: false },
  { id: 2, conversation_id: 'main', branch_id: 'branch', title: 'Old report', content_json: 'invalid', created_ms: 1, read: true },
]
const inbox = () => ({ conversations: [], notices, unread: 1, unavailable: false, refresh: vi.fn() })
it('keeps history and scheduled reminders in All; Unread filters only happened messages', () => {
  const select = vi.fn()
  render(<AgentInbox inbox={inbox()} select={select} />)
  expect(screen.getByText('Future reminder')).toBeTruthy()
  expect(screen.getByText('Old report')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.unread' }))
  expect(screen.queryByText('Future reminder')).toBeNull()
  expect(screen.queryByText('Old report')).toBeNull()
  fireEvent.click(screen.getByText('New report'))
  expect(select).toHaveBeenCalledWith('main', 'branch', 'message')
})
it('marks only the observed cursor and never cancels reminders', async () => {
  vi.mocked(api).mockResolvedValue({ data: {} })
  const state = inbox()
  render(<AgentInbox inbox={state} select={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.readAll' }))
  await waitFor(() => expect(state.refresh).toHaveBeenCalled())
  expect(api).toHaveBeenCalledTimes(1)
  expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/main/read', { eventId: 4 })
  expect(screen.getByText('Future reminder')).toBeTruthy()
})
it('exposes a failed read acknowledgement without claiming success', async () => {
  vi.mocked(api).mockRejectedValue(new Error('offline'))
  render(<AgentInbox inbox={inbox()} select={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'agent.notification.readAll' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
})

it('does not report an empty inbox while the first response is pending or failed', () => {
  const page = render(<AgentInbox inbox={{ ...inbox(), notices: [], notificationsLoading: true }} select={vi.fn()} />)
  expect(screen.queryByText('agent.noNotifications')).toBeNull()
  page.rerender(<AgentInbox inbox={{ ...inbox(), notices: [], notificationsFailed: true }} select={vi.fn()} />)
  expect(screen.getByRole('alert')).toBeTruthy()
  expect(screen.queryByText('agent.noNotifications')).toBeNull()
})
