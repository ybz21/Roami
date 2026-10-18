// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentActivity from './AgentActivity'
import type { AgentActivityItem } from './agent-protocol'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, p?: Record<string, unknown>) => key + (p ? ' ' + Object.values(p).join(' ') : ''), locale: 'en-US' }) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const task = (state: string, delivered = false): AgentActivityItem => ({ id: 'task:t', kind: 'task', name: 'codex', anchorMessageId: 'm', taskId: 't', state, delivered, external: true, target: 'session-one', startedMs: 1000, updatedMs: 2000 })
it('keeps a failed dispatch visible while collapsed and never describes it as delivered', () => {
  render(<AgentActivity items={[{ ...task('failed'), errorCode: 'SESSION_NOT_IDLE' }]} onSession={vi.fn()} />)
  expect(screen.getByRole('status').textContent).toContain('agent.activity.notDelivered')
  expect(screen.getByRole('status').textContent).toContain('agent.activity.sessionBusy')
  expect(document.querySelector('.agent-activity-details')).toBeNull()
  fireEvent.click(screen.getByRole('button'))
  expect(document.querySelector('.agent-activity-details')).toBeTruthy()
  expect(screen.queryByText('agent.activity.openSession')).toBeNull()
})
it('updates the same task from queued to running and opens only the bound session', () => {
  const open = vi.fn(), view = render(<AgentActivity items={[task('queued')]} onSession={open} />)
  fireEvent.click(screen.getByRole('button'))
  expect(screen.getByText('agent.activity.state.queued')).toBeTruthy()
  view.rerender(<AgentActivity items={[task('running', true)]} onSession={open} />)
  fireEvent.click(screen.getByText('agent.activity.openSession'))
  expect(open).toHaveBeenCalledWith('session-one')
  expect(document.querySelectorAll('[data-activity-id]')).toHaveLength(1)
})

it('shows tools, timestamps and running state without expanding and does not label unknown as success', () => {
  const item = { ...task('running'), id: 'tool:one', kind: 'tool' as const, name: 'shell' }
  const view = render(<AgentActivity items={[item]} onSession={vi.fn()} />)
  expect(screen.getByText('agent.activity.shell shell')).toBeTruthy()
  expect(screen.getByText('agent.activity.state.running')).toBeTruthy()
  expect(document.querySelector('time')?.dateTime).toBe('1970-01-01T00:00:01.000Z')
  view.rerender(<AgentActivity items={[{ ...item, state: 'unrecognized-provider-state' }]} onSession={vi.fn()} />)
  expect(document.querySelector('[data-state="unknown"]')).toBeTruthy()
  expect(screen.queryByText('agent.activity.state.succeeded')).toBeNull()
})

it('collapses consecutive steps together and keeps failures visible in the group summary', () => {
  render(<AgentActivity items={[{ ...task('succeeded'), id: 'tool:first', kind: 'tool', name: 'read' }, { ...task('unknown'), id: 'tool:second', kind: 'tool', name: 'browser_act' }]} onSession={vi.fn()} conversationId="c" />)
  expect(screen.getByRole('button').getAttribute('aria-expanded')).toBe('false')
  expect(document.querySelectorAll('[data-activity-id]')).toHaveLength(0)
  expect(screen.getByText('agent.activity.needsAttention')).toBeTruthy()
  expect(screen.getByText('agent.activity.problems 1')).toBeTruthy()
  expect(screen.queryByText('agent.activity.state.succeeded')).toBeNull()
})

it('loads input and output only on expansion and refreshes an open running step', async () => {
  const { api } = await import('../../api')
  vi.mocked(api).mockResolvedValueOnce({ data: { id: 'tool:one', state: 'running', input: { text: '{"query":"browser"}', truncated: false }, output: null } }).mockResolvedValueOnce({ data: { id: 'tool:one', state: 'succeeded', input: { text: '{"query":"browser"}', truncated: false }, output: { text: '{"found":3}', truncated: true } } })
  const item = { ...task('running'), id: 'tool:one', kind: 'tool' as const, name: 'tool_search' }
  const view = render(<AgentActivity items={[item]} onSession={vi.fn()} conversationId="c" branchId="b" />)
  expect(api).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button'))
  await screen.findByText('agent.activity.noOutput')
  expect(api).toHaveBeenCalledWith('GET', '/agent/conversations/c/activities/tool%3Aone?branchId=b', undefined, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  fireEvent.click(screen.getByText('agent.activity.input'))
  expect(screen.getByText('{"query":"browser"}')).toBeTruthy()
  view.rerender(<AgentActivity items={[{ ...item, state: 'succeeded', updatedMs: 3000 }]} onSession={vi.fn()} conversationId="c" branchId="b" />)
  await screen.findByText('{"found":3}')
  expect(screen.getByText('agent.activity.previewTruncated')).toBeTruthy()
  expect(document.querySelector('.agent-activity-toggle')?.getAttribute('aria-expanded')).toBe('true')
})

it('reports unavailable historical details and allows a retry without claiming success', async () => {
  const { api } = await import('../../api')
  vi.mocked(api).mockRejectedValueOnce(new Error('removed')).mockResolvedValueOnce({ data: { id: 'tool:gone', state: 'unknown', input: { text: '{}', truncated: false }, output: null } })
  render(<AgentActivity items={[{ ...task('unknown'), id: 'tool:gone', kind: 'tool', name: 'shell' }]} onSession={vi.fn()} conversationId="c" />)
  fireEvent.click(screen.getByRole('button'))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByText('agent.retry'))
  await screen.findByText('agent.activity.noOutput')
  expect(screen.queryByText('agent.activity.state.succeeded')).toBeNull()
})
