// @vitest-environment jsdom
import React from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useProjectActions } from './useProjectActions'

const mock = vi.hoisted(() => ({ api: vi.fn(), open: vi.fn(), error: vi.fn() }))
vi.mock('../api', () => ({ api: mock.api }))
vi.mock('antd', async original => ({ ...await original<typeof import('antd')>(), App: { useApp: () => ({ message: { error: mock.error }, modal: { confirm: vi.fn() } }) } }))
vi.mock('../components/projects/Projects', () => ({ NewProjectModal: () => null }))
vi.mock('../components/sessions/TaskComposer', () => ({ TaskComposer: () => null }))
vi.mock('../components/sessions/session-closer', () => ({ useSessionCloser: () => ({}) }))

function options() {
  const sessions = [{ name: 'first', label: 'First' }, { name: 'active', label: 'Active' }]
  const treeSrc = { projects: [{ key: 'p', name: 'P', dir: '/repo', git: true }], worktrees: { p: [{ path: '/work', branch: 'fix/rsi', isMain: false, sessions: sessions.map(s => ({ session: s.name })) }] } }
  return {
    data: { sessList: sessions, sessIds: null, sessListLoaded: true, refresh: vi.fn() },
    directory: { treeSrc, treeSrcRef: { current: treeSrc }, refresh: vi.fn() },
    workspace: { terms: [], active: 'active', activeTask: '/work', activeTaskRef: { current: '/work' }, projTable: {}, keyOf: () => '/work', space: {}, openTerm: mock.open },
    runtime: { claudeMap: {}, codexMap: {}, termRefs: { current: {} } }, isMobile: false, agentKinds: {}, go: vi.fn(),
  } as unknown as Parameters<typeof useProjectActions>[0]
}
beforeEach(() => { mock.api.mockReset().mockResolvedValue({ data: { operationId: 'operation', resourceId: 'created' } }); mock.open.mockReset(); mock.error.mockReset() })
afterEach(cleanup)
it('forks from the current session when adding a terminal in the current workspace', async () => {
  const { result } = renderHook(() => useProjectActions(options()))
  await act(() => result.current.newTerminalInTask('shell'))
  expect(mock.api).toHaveBeenCalledWith('POST', '/session-lifecycle/operations', expect.objectContaining({ kind: 'create', intent: expect.objectContaining({ dir: '/work', parent: 'active', name: expect.any(String) }) }))
  expect(mock.api).not.toHaveBeenCalledWith('POST', '/sessions', expect.anything())
  expect(mock.open).toHaveBeenCalledWith('created', '/work')
})
it('uses the explicitly selected parent rather than another active session', async () => {
  const { result } = renderHook(() => useProjectActions(options()))
  await act(() => result.current.newTerminalInTask('shell', '/work', 'first'))
  expect(mock.api.mock.calls[0][1]).toBe('/session-lifecycle/operations')
  expect(mock.api.mock.calls[0][2].intent.parent).toBe('first')
})
it('reuses an available workspace parent for the directory entry point', async () => {
  const { result } = renderHook(() => useProjectActions(options()))
  await act(() => result.current.newTerminalAt('shell', '/work'))
  expect(mock.api.mock.calls[0][1]).toBe('/session-lifecycle/operations')
  expect(mock.api.mock.calls[0][2].intent.parent).toBe('first')
})
it('does not fall back to an unrelated new session after fork fails', async () => {
  mock.api.mockRejectedValue(new Error('FORK_FAILED'))
  const { result } = renderHook(() => useProjectActions(options()))
  await act(() => result.current.newTerminalInTask('shell'))
  expect(mock.api.mock.calls.filter(([method]) => method === 'POST')).toHaveLength(1)
  expect(mock.error).toHaveBeenCalledWith('FORK_FAILED')
  expect(mock.open).not.toHaveBeenCalled()
})
it('creates an independent session when the directory has no usable parent', async () => {
  const { result } = renderHook(() => useProjectActions(options()))
  await act(() => result.current.newTerminalAt('shell', '/fresh'))
  expect(mock.api).toHaveBeenCalledWith('POST', '/session-lifecycle/operations', expect.objectContaining({ intent: expect.objectContaining({ name: 'fresh-sh', dir: '/fresh', parent: undefined }) }))
})
