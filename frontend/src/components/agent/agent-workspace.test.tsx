// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentWorkspace } from './useAgentWorkspace'
import AgentWorkspaceActivity from './AgentWorkspaceActivity'
import type { AgentActivityItem } from './agent-protocol'
import { api } from '../../api'
import { taskExecutor } from './agent-task-protocol'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => { const t = (key: string) => key; return { useI18n: () => ({ t, locale: 'en-US' }) } })
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks() })
it('restores the visible panel and tab on first paint', () => {
  const page = renderHook(() => useAgentWorkspace(null))
  expect(page.result.current.open).toBe(true)
  act(() => page.result.current.change({ open: false, tab: 'memory' }))
  page.unmount()
  const next = renderHook(() => useAgentWorkspace(null))
  expect(next.result.current.open).toBe(false)
  expect(next.result.current.tab).toBe('memory')
})
it('keeps node preferences separate without painting the old node state', () => {
  const page = renderHook(({ node }) => useAgentWorkspace(node), { initialProps: { node: 'first' } })
  act(() => page.result.current.change({ open: false, tab: 'tasks' }))
  page.rerender({ node: 'second' })
  expect(page.result.current.open).toBe(true)
  expect(page.result.current.tab).toBe('activity')
  page.rerender({ node: 'first' })
  expect(page.result.current.open).toBe(false)
  expect(page.result.current.tab).toBe('tasks')
})
it('recovers from a malformed saved panel preference', () => {
  localStorage.setItem('roami.agent.workspace.local', '{broken')
  expect(renderHook(() => useAgentWorkspace(null)).result.current.tab).toBe('activity')
})
const action = (id: string, state: string, ms: number): AgentActivityItem => ({ id, kind: 'tool', name: 'read', state, anchorMessageId: 'message', startedMs: ms, updatedMs: ms })
const props = { cid: 'main', branch: 'branch', onSession: vi.fn(), onTask: vi.fn() }
it('keeps unknown and waiting states distinct from an accepted delegation', () => {
  const ms = Date.now()
  const page = render(<AgentWorkspaceActivity {...props} items={[action('unknown', 'unrecognized', ms), action('waiting', 'waiting_user', ms), { ...action('dispatch', 'succeeded', ms), name: 'delegate' }]} />)
  expect(page.container.querySelector('[data-state="unknown"]')).toBeTruthy()
  expect(screen.getByText('agent.activity.state.waiting_user')).toBeTruthy()
  expect(screen.getByText('agent.activity.accepted')).toBeTruthy()
  expect(screen.queryByText('agent.activity.state.succeeded')).toBeNull()
})
it('orders latest changes first, opens the exact task, and leaves missing times unknown', async () => {
  vi.mocked(api).mockResolvedValue({ data: [{ id: 'exact-task', revision: 1, state: 'running', intent_json: JSON.stringify({ goal: 'Current task' }) }] })
  const page = render(<AgentWorkspaceActivity {...props} items={[action('old', 'succeeded', 1), { ...action('task', 'running', Date.now()), kind: 'task', name: 'codex', taskId: 'exact-task' }, action('no-time', 'running', 0)]} />)
  await screen.findByText('Current task')
  const rows = page.container.querySelectorAll('.agent-workspace-entry')
  expect(rows[0].textContent).toContain('Current task')
  fireEvent.click(rows[0]); expect(props.onTask).toHaveBeenCalledWith('exact-task')
  expect(screen.getByText('agent.workspace.timeUnknown')).toBeTruthy()
  expect(rows[2].querySelector('time')).toBeNull()
  expect(api).toHaveBeenCalledTimes(1)
  expect(api).toHaveBeenCalledWith('GET', '/agent/tasks?conversationId=main', undefined, expect.anything())
})
it('updates one activity in place when its streamed state changes', () => {
  const page = render(<AgentWorkspaceActivity {...props} items={[action('same', 'running', Date.now())]} />)
  expect(screen.getByText('agent.activity.state.running')).toBeTruthy()
  page.rerender(<AgentWorkspaceActivity {...props} items={[action('same', 'succeeded', Date.now())]} />)
  expect(screen.queryByText('agent.activity.state.running')).toBeNull()
  expect(screen.getByText('agent.activity.state.succeeded')).toBeTruthy()
  expect(page.container.querySelectorAll('.agent-workspace-entry')).toHaveLength(1)
  expect(api).not.toHaveBeenCalled()
})

it('resolves professional CLI identity from recorded intent and leaves unsupported identities unknown', () => {
 const task = { id: 'task', revision: 1, state: 'waiting_user', intent_json: JSON.stringify({ executor: 'codex' }), latestAttempt: { executorKind: 'cli', state: 'succeeded' } }
 expect(taskExecutor(task)).toBe('codex')
 expect(taskExecutor({ ...task, intent_json: '{broken' })).toBeNull()
 expect(taskExecutor({ ...task, latestAttempt: { executorKind: 'native', state: 'running' } })).toBe('native')
 expect(taskExecutor({ ...task, latestAttempt: { executorKind: 'future', state: 'running' } })).toBeNull()
})
