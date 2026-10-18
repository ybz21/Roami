// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentActivity from './AgentActivity'
import type { AgentActivityItem } from './agent-protocol'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, p?: Record<string, unknown>) => key + (p ? ' ' + Object.values(p).join(' ') : ''), locale: 'en-US' }) }))
afterEach(cleanup)
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
  expect(screen.getByText('shell')).toBeTruthy()
  expect(screen.getByText('agent.activity.state.running')).toBeTruthy()
  expect(document.querySelector('time')?.dateTime).toBe('1970-01-01T00:00:01.000Z')
  view.rerender(<AgentActivity items={[{ ...item, state: 'unrecognized-provider-state' }]} onSession={vi.fn()} />)
  expect(document.querySelector('[data-state="unknown"]')).toBeTruthy()
  expect(screen.queryByText('agent.activity.state.succeeded')).toBeNull()
})
