// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { agentPagePath, backAgentPage, openAgentPage, readAgentPage } from './agent-page-route'

afterEach(() => { vi.restoreAllMocks(); history.replaceState(null, '', '#/home') })

it.each(['tasks', 'memory', 'notifications'] as const)('restores the %s page with its exact source conversation after refresh', view => {
  const origin = 'home/conversation/branch/source-message'
  expect(readAgentPage(agentPagePath(view, origin))).toEqual({ view, origin, task: '' })
})

it('keeps task detail links distinct from the original conversation and task list', () => {
  const route = agentPagePath('tasks', 'home/c', 'task/with spaces')
  expect(readAgentPage(route)).toEqual({ view: 'tasks', origin: 'home/c', task: 'task/with spaces' })
  expect(readAgentPage('home/c/branch/message')).toBeNull()
})

it.each(['home/tasks/%invalid', 'home/tasks/home%2Fbad%25', 'home/memory/home/task', 'home/tasks/', 'home/tasks/home/task/extra'])('rejects malformed page route %s', route => {
  expect(readAgentPage(route)).toBeNull()
})

it('preserves node terminal parameters and adds one navigation entry for a content page', () => {
  history.replaceState({ existing: 'retained' }, '', '#/home/c/b/m?terms=s1&active=s1')
  const before = history.length
  openAgentPage('memory')
  expect(location.hash).toBe('#/home/memory/home%2Fc%2Fb%2Fm?terms=s1&active=s1')
  expect(history.length).toBe(before + 1)
  expect(history.state).toMatchObject({ existing: 'retained', roamiAgentPageFrom: '#/home/c/b/m?terms=s1&active=s1' })
})

it('replaces child task details without adding an extra back step', () => {
  const list = '#/' + agentPagePath('tasks', 'home/c')
  history.replaceState({ roamiAgentPageFrom: list }, '', '#/' + agentPagePath('tasks', 'home/c', 'parent'))
  const before = history.length, changed = vi.fn()
  window.addEventListener('hashchange', changed)
  openAgentPage('tasks', 'child')
  expect(history.length).toBe(before)
  expect(readAgentPage(location.hash.slice(2))).toEqual({ view: 'tasks', origin: 'home/c', task: 'child' })
  expect(history.state.roamiAgentPageFrom).toBe(list)
  expect(changed).toHaveBeenCalledOnce()
  window.removeEventListener('hashchange', changed)
})

it('uses native history for both detail-to-list and list-to-conversation returns', () => {
  const back = vi.spyOn(history, 'back').mockImplementation(() => {})
  history.replaceState({ roamiAgentPageFrom: '#/' + agentPagePath('tasks', 'home/c') }, '', '#/' + agentPagePath('tasks', 'home/c', 'task'))
  backAgentPage({ view: 'tasks', origin: 'home/c', task: 'task' })
  history.replaceState({ roamiAgentPageFrom: '#/home/c?terms=s1' }, '', '#/' + agentPagePath('tasks', 'home/c'))
  backAgentPage({ view: 'tasks', origin: 'home/c', task: '' })
  expect(back).toHaveBeenCalledTimes(2)
})
