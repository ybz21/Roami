// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentChat from './AgentChat'
import { api } from '../../api'

const state = vi.hoisted(() => ({ turns: [{ id: 'current', state: 'running' }], messages: [] as any[], renderMessage: vi.fn(() => null), accepted: vi.fn(), refresh: vi.fn() }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false, landscape: false }) }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: vi.fn() } }) },
  Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
  Dropdown: ({ children }: any) => children,
  Input: Object.assign((props: any) => <input {...props} />, { TextArea: ({ variant: _variant, autoSize: _autoSize, ...props }: any) => <textarea {...props} /> }),
  Modal: () => null, Spin: () => null,
}))
vi.mock('./useAgentThread', () => ({ useAgentThread: () => ({ connected: true, view: { conversation: { id: 'main', active_branch_id: 'branch' }, branchId: 'branch', messages: state.messages, turns: state.turns }, accepted: state.accepted, refresh: state.refresh }) }))
vi.mock('./useAgentAttachments', () => ({ useAgentAttachments: () => ({ ids: [], items: [], blocked: false, clear: vi.fn() }) }))
vi.mock('./useAgentModels', () => ({ useAgentModels: () => ({}) }))
vi.mock('./useVisibleAgentReads', () => ({ useVisibleAgentReads: () => {} }))
vi.mock('./useAgentMessageFocus', () => ({ useAgentMessageFocus: () => {} }))
vi.mock('./AgentContextUsage', () => ({ default: () => null }))
vi.mock('./AgentComposerPlus', () => ({ default: () => null }))
vi.mock('./AgentMessageView', async () => ({ default: (await import('react')).memo(state.renderMessage) }))
vi.mock('./AgentActivity', () => ({ default: () => null }))
vi.mock('./AgentTasks', () => ({ default: () => null }))
vi.mock('./AgentMemory', () => ({ default: () => null }))
vi.mock('../markdown/Markdown', () => ({ default: () => null }))

const props = { cid: 'main', branch: '', node: null, inbox: { conversations: [{ id: 'main' }], refresh: vi.fn() } as any, inboxOpen: false, select: vi.fn(), notifications: vi.fn(), projects: [], onSession: vi.fn(), onOverview: vi.fn() }
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); state.messages = []; state.turns = [{ id: 'current', state: 'running' }] })

it('does not rerender settled history while typing in the composer', () => {
  state.messages = [{ id: 'answer', role: 'assistant', status: 'completed', seq: 1, content: { text: 'A long completed report' } }]
  render(<AgentChat {...props} />)
  const initial = state.renderMessage.mock.calls.length
  for (const value of ['a', 'ab', 'abc', 'abcd', 'abcde']) fireEvent.change(screen.getByRole('textbox', { name: 'agent.message' }), { target: { value } })
  expect(state.renderMessage.mock.calls.length).toBe(initial)
  expect(initial).toBe(1)
})

it('queues a normal busy-time send above the composer and lets the user interrupt with that exact message', async () => {
  vi.mocked(api).mockResolvedValue({ data: { kind: 'message', messageId: 'urgent', turnId: 'next' } })
  const page = render(<AgentChat {...props} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'agent.message' }), { target: { value: 'do this next' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.outbox.add' }))
  expect(api).not.toHaveBeenCalled()
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
  const queue = screen.getByRole('region', { name: 'agent.outbox.title' })
  const card = page.container.querySelector('.agent-compose-card')!
  expect(queue.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  const saved = JSON.parse(localStorage.getItem('roami.agent.outbox.roami.agent.draft.local.main')!)
  fireEvent.click(screen.getByRole('button', { name: 'agent.outbox.interruptNow' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/main/messages', { requestKey: saved.items[0].id, text: 'do this next', attachmentIds: [] }))
  await waitFor(() => expect(screen.queryByRole('region', { name: 'agent.outbox.title' })).toBeNull())
  expect(api).toHaveBeenCalledTimes(1)
  expect(state.accepted).toHaveBeenCalledWith(expect.objectContaining({ messageId: 'urgent' }), 'do this next')
})

it('sends slash commands immediately instead of leaving stop trapped behind the current reply', async () => {
  vi.mocked(api).mockResolvedValue({ data: { kind: 'interrupt' } })
  render(<AgentChat {...props} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'agent.message' }), { target: { value: '/stop' } })
  fireEvent.submit(screen.getByRole('textbox').closest('form')!)
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/main/messages', expect.objectContaining({ text: '/stop' })))
  expect(screen.queryByRole('region', { name: 'agent.outbox.title' })).toBeNull()
})
