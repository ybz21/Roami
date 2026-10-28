// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { mainTaskActivities } from './main-task-activity'
import AgentTaskActivity from './AgentTaskActivity'
import { projectAgentEvent, type AgentActivityItem } from './agent-protocol'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, values?: Record<string, unknown>) => key + (values ? ' ' + Object.values(values).join(' ') : '') }) }))
afterEach(cleanup)
const task: AgentActivityItem = { id: 'task:t', taskId: 't', kind: 'task', name: 'native', title: '查询天气', state: 'succeeded', anchorMessageId: 'm', startedMs: 1, updatedMs: 10 }
const tool: AgentActivityItem = { ...task, id: 'tool:read', kind: 'tool', name: 'memory_search', state: 'failed' }

it('gives failed replies a retry hint and forwards gateway quota errors', () => {
  const { rerender } = render(<AgentTaskActivity items={[{ ...task, taskId: undefined, kind: 'turn', state: 'failed', errorCode: 'MODEL_HTTP_400' }]} onTask={vi.fn()} />)
  expect(screen.getByRole('status').textContent).toBe('agent.requestFailed')
  expect(screen.queryByRole('button')).toBeNull()
  rerender(<AgentTaskActivity items={[{ ...task, taskId: undefined, kind: 'turn', state: 'failed', errorCode: 'MODEL_HTTP_402' }]} onTask={vi.fn()} />)
  expect(screen.getByRole('status').textContent).toBe('agent.models.gatewayQuota')
})

it('keeps the task subject and exact detail destination without recovered tool errors, route explanations or internal IDs', () => {
  const open = vi.fn()
  const items = mainTaskActivities([task, tool, { ...tool, id: 'tool:next', state: 'succeeded' }])
  render(<AgentTaskActivity items={items} onTask={open} />)
  expect(screen.getByText('查询天气')).toBeTruthy()
  expect(screen.getByText('agent.state.succeeded')).toBeTruthy()
  expect(screen.queryByRole('status')).toBeNull()
  expect(document.body.textContent).not.toContain('memory_search')
  expect(document.body.textContent).not.toContain('task:t')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.viewNamed 查询天气' }))
  expect(open).toHaveBeenCalledWith('t')
})

it('retains unknown outcomes and child questions without duplicating ordinary child execution', () => {
  const child = { ...task, id: 'task:child', taskId: 'child', parentTaskId: 't', state: 'running' }
  expect(mainTaskActivities([task, child])).toEqual([task])
  expect(mainTaskActivities([{ ...task, state: 'running' }, { ...child, state: 'waiting_user' }])).toHaveLength(2)
  const items = mainTaskActivities([task, { ...tool, state: 'unknown' }])
  render(<AgentTaskActivity items={items} onTask={vi.fn()} />)
  expect(screen.getByRole('status').textContent).toContain('agent.activity.outcomeUnknown')
  expect(document.body.textContent).not.toContain('memory_search')
})

it('cannot evict the task card with hundreds of live internal tool events', () => {
  let view = { conversation: { id: 'c', title: '', active_branch_id: 'b', updated_ms: 0 }, branchId: 'b', messages: [], turns: [], activities: [task], snapshotCursor: 0 }
  for (let id = 1; id <= 300; id++) view = projectAgentEvent(view, { id, kind: 'task.activity', payload: { activity: { ...tool, id: 'tool:' + id } } }).view as typeof view
  expect(view.activities).toEqual([task])
})
