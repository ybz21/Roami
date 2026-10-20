// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentMessageView from './AgentMessageView'
import type { AgentMessage } from './agent-protocol'

vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, values?: Record<string, string>) => key + (values ? ' ' + Object.values(values).join(' ') : ''), locale: 'en-US' }) }))
vi.mock('antd', () => ({ App: { useApp: () => ({ message: { error: vi.fn() } }) } }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <p>{children}</p> }))
afterEach(cleanup)
const item = (status: string): AgentMessage => ({ id: 'report', branch_id: 'b', role: 'assistant', status: 'completed', seq: 2, content: { text: 'PR created, tests passed.', sessionReply: { dispatchId: 'dispatch-1', sessionId: 'original-codex', status, verified: false } } })

it.each(['completed', 'failed', 'progress', 'blocked', 'unknown'])('labels %s as executor evidence, with unknown never shown as success', status => {
  render(<AgentMessageView node={null} item={item(status)} focused={false} remember={vi.fn()} />)
  expect(screen.getByRole('status').textContent).toContain('agent.sessionReply.' + status)
  expect(screen.getByRole('status').textContent).toContain('agent.sessionReply.unverified')
  expect(screen.getByText('original-codex')).toBeTruthy()
  if (status !== 'completed') expect(screen.queryByText('agent.sessionReply.completed')).toBeNull()
})

it('answers a blocker with its exact session and assignment, rather than an ambiguous bare label', async () => {
  const answer = vi.fn().mockResolvedValue(true), message = item('blocked')
  message.content.question = { prompt: 'Choose base', options: [{ label: 'main' }, { label: 'release' }] }
  render(<AgentMessageView node={null} item={message} focused={false} remember={vi.fn()} canAnswer answer={answer} />)
  fireEvent.click(screen.getByRole('button', { name: 'main' }))
  await waitFor(() => expect(answer).toHaveBeenCalledWith('agent.sessionReply.answer original-codex dispatch-1 main'))
})

it('keeps old messages without session report metadata renderable', () => {
  const message = item('completed'); delete message.content.sessionReply
  render(<AgentMessageView node={null} item={message} focused={false} remember={vi.fn()} />)
  expect(screen.getByText('PR created, tests passed.')).toBeTruthy()
  expect(screen.queryByRole('status')).toBeNull()
})
