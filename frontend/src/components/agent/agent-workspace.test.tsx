// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentWorkspace } from './useAgentWorkspace'
import { taskExecutor } from './agent-task-protocol'
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
  expect(page.result.current.tab).toBe('tasks')
  page.rerender({ node: 'first' })
  expect(page.result.current.open).toBe(false)
  expect(page.result.current.tab).toBe('tasks')
})
it('recovers from a malformed saved panel preference', () => {
  localStorage.setItem('roami.agent.workspace.local', '{broken')
  expect(renderHook(() => useAgentWorkspace(null)).result.current.tab).toBe('tasks')
})
it.each(['activity', 'reminders'])('migrates the removed %s tab without changing the collapsed preference', tab => {
 localStorage.setItem('roami.agent.workspace.local', JSON.stringify({ open: false, tab }))
 const page = renderHook(() => useAgentWorkspace(null))
 expect(page.result.current.tab).toBe('tasks')
 expect(page.result.current.open).toBe(false)
})
it('opens tasks by default and retains a saved memory tab', () => {
 expect(renderHook(() => useAgentWorkspace(null)).result.current.tab).toBe('tasks')
 localStorage.setItem('roami.agent.workspace.local', JSON.stringify({ open: true, tab: 'memory' }))
 expect(renderHook(() => useAgentWorkspace(null)).result.current.tab).toBe('memory')
})

it('resolves professional CLI identity from recorded intent and leaves unsupported identities unknown', () => {
 const task = { id: 'task', revision: 1, state: 'waiting_user', intent_json: JSON.stringify({ executor: 'codex' }), latestAttempt: { executorKind: 'cli', state: 'succeeded' } }
 expect(taskExecutor(task)).toBe('codex')
 expect(taskExecutor({ ...task, intent_json: '{broken' })).toBeNull()
 expect(taskExecutor({ ...task, latestAttempt: { executorKind: 'native', state: 'running' } })).toBe('native')
 expect(taskExecutor({ ...task, latestAttempt: { executorKind: 'future', state: 'running' } })).toBeNull()
})
