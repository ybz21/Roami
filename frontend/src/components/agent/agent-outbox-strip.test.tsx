// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentOutbox from './AgentOutbox'
import type { useAgentOutbox } from './useAgentOutbox'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', () => ({ Dropdown: ({ children }: any) => children, Input: { TextArea: (props: any) => <textarea {...props} /> } }))
afterEach(cleanup)
it('starts as one pending-message strip, expands the queue, and submits only the selected stable ID', () => {
  const outbox = { items: ['first', 'second'].map(id => ({ id, text: id + ' pending message', attachments: [], state: 'waiting' as const })), paused: false, storageFailed: false, sending: '', sendNow: vi.fn(), remove: vi.fn(), pause: vi.fn(), edit: vi.fn(), retry: vi.fn(), enqueue: vi.fn() } as unknown as ReturnType<typeof useAgentOutbox>
  render(<AgentOutbox outbox={outbox} ready running />)
  expect(screen.getByText('first pending message')).toBeTruthy()
  expect(screen.queryByText('second pending message')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.outbox.count' }))
  expect(screen.getByText('second pending message')).toBeTruthy()
  fireEvent.click(screen.getAllByRole('button', { name: 'agent.outbox.interruptNow' })[1])
  expect(outbox.sendNow).toHaveBeenCalledWith('second')
  expect(screen.queryByText('agent.outbox.localHint')).toBeNull()
})
