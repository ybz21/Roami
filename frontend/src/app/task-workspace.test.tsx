// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionDirectory } from './useSessionDirectory'
import { useTaskWorkspace } from './useTaskWorkspace'
import { applyWorkspaceChange, type WorkspaceState } from './workspace-state'

vi.mock('../components/shell/useWorkspaceLayout', () => ({ useWorkspaceLayout: () => ({ setDockOpen: vi.fn(), setFocus: vi.fn() }) }))
vi.mock('../components/sessions/session-project', () => ({ useSessionProjects: () => ({}) }))
vi.mock('../components/cluster/node-url', async importOriginal => ({ ...await importOriginal<typeof import('../components/cluster/node-url')>(), currentNodeId: () => 'node-a', useCurrentNodeId: () => 'node-a' }))
const mock = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('../api', () => ({ api: mock.api }))

const ids = { byId: { '$1': 'alpha', '$2': 'beta' }, byName: { alpha: '$1', beta: '$2' } }
const go = vi.fn()
let server: WorkspaceState
function useWorkspace(mobile = false) {
  const directory = useSessionDirectory()
  return { workspace: useTaskWorkspace({ directory, nodeId: 'node-a', desktop: !mobile, mobile, page: 'w', navigate: go }), directory }
}
beforeEach(() => {
  localStorage.clear(); go.mockClear(); history.replaceState(null, '', '#/w')
  server = { revision: 1, terms: ['$1'], active: '$1', files: [], activeFile: '' }
  mock.api.mockReset().mockImplementation(async (method, path, body) => {
    if (path === '/agent/native-sessions') return { data: [] }
    if (path === '/sessions') return Object.entries(ids.byId).map(([id, name]) => ({ id, name }))
    if (path !== '/workspace') throw new Error(path)
    if (method === 'PATCH') {
      if (!server.revision && body.seed) server = { ...body.seed, revision: 0 }
      for (const change of body.changes) server = applyWorkspaceChange(server, change)
      server = { ...server, revision: server.revision + 1 }
    }
    return { data: structuredClone(server) }
  })
})
afterEach(cleanup)

describe('server workspace lifecycle', () => {
  it('uses the backend despite stale URL tabs and retains memory filters and history', async () => {
    history.replaceState({ roamiMemoryFrom: '#/home/memory/home' }, '', '#/home/memory/home?memoryView=review&memoryId=one&terms=%242&active=%242&node=n1')
    const { result } = renderHook(() => useWorkspace())
    await waitFor(() => expect(result.current.workspace.active).toBe('alpha'))
    const params = () => new URLSearchParams(location.hash.split('?')[1])
    expect(Object.fromEntries(params())).toEqual({ memoryView: 'review', memoryId: 'one', node: 'n1' })
    act(() => result.current.workspace.openTerm('beta'))
    await waitFor(() => expect(server.terms).toEqual(['$1', '$2']))
    expect(params().has('terms')).toBe(false)
    expect(history.state.roamiMemoryFrom).toBe('#/home/memory/home')
  })

  it('imports old links and files once after identity arrives, then deletes the local copy', async () => {
    server = { revision: 0, terms: [], active: '', files: [], activeFile: '' }
    localStorage.setItem('roam.terms', JSON.stringify({ 'node-a': { terms: ['$2'], active: '$2', files: [{ path: '/repo/readme.md', preview: false, mode: 'preview', task: '/repo' }], activeFile: '/repo/readme.md' } }))
    history.replaceState(null, '', '#/w?terms=%241&active=%241')
    const { result } = renderHook(() => useWorkspace())
    await waitFor(() => expect(result.current.workspace.activeFile).toBe('/repo/readme.md'))
    expect(result.current.workspace.terms).toEqual(['alpha'])
    expect(server.terms).toEqual(['$1'])
    expect(localStorage.getItem('roam.terms')).toBeNull()
    expect(location.hash).toBe('#/w')
  })

  it('shares the whole session list on phones while opening only the selected overlay', async () => {
    const { result } = renderHook(() => useWorkspace(true))
    await waitFor(() => expect(result.current.workspace.active).toBe('alpha'))
    expect(result.current.workspace.overlay).toBe(false)
    act(() => result.current.workspace.openTerm('beta'))
    await waitFor(() => expect(server.active).toBe('$2'))
    expect(result.current.workspace.terms).toEqual(['alpha', 'beta'])
    expect(result.current.workspace.overlay).toBe(true)
    act(() => result.current.workspace.closeTerm('beta'))
    await waitFor(() => expect(server.terms).toEqual(['$1']))
    act(() => result.current.workspace.closeTerm('alpha'))
    await waitFor(() => expect(server.terms).toEqual([]))
    expect(result.current.workspace.overlay).toBe(false)
    expect(result.current.workspace.active).toBeNull()
  })

  it('dismisses the phone overlay when another device closes the last tab', async () => {
    const { result } = renderHook(() => useWorkspace(true))
    await waitFor(() => expect(result.current.workspace.active).toBe('alpha'))
    act(() => result.current.workspace.openTerm('alpha'))
    expect(result.current.workspace.overlay).toBe(true)
    server = { ...server, revision: server.revision + 1, terms: [], active: '' }
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await waitFor(() => expect(result.current.workspace.overlay).toBe(false))
    expect(result.current.workspace.terms).toEqual([])
  })

  it('keeps stable session IDs when renamed and selects the neighboring file when closed', async () => {
    const { result } = renderHook(() => useWorkspace())
    await waitFor(() => expect(result.current.workspace.active).toBe('alpha'))
    act(() => result.current.workspace.renameOpenTerm('alpha', 'renamed'))
    expect(result.current.workspace.active).toBe('renamed')
    expect(server.terms).toEqual(['$1'])
    act(() => result.current.workspace.openFileTab('/repo/one.md'))
    act(() => result.current.workspace.openFileTab('/repo/two.ts', 12))
    expect(result.current.workspace.reveal?.line).toBe(12)
    act(() => result.current.workspace.closeFileTab('/repo/two.ts'))
    expect(result.current.workspace.activeFile).toBe('/repo/one.md')
    act(() => result.current.workspace.activateSession('renamed'))
    expect(result.current.workspace.activeFile).toBe('')
    await waitFor(() => expect(server.files.map(file => file.path)).toEqual(['/repo/one.md']))
  })
})


it('opens Roami beside Codex in the shared workspace and restores its stable identity', async () => {
  const base = mock.api.getMockImplementation()!
  mock.api.mockImplementation(async (method, path, body) => path === '/agent/native-sessions' ? { data: [{ nativeSessionId: 'native', taskId: 'task', title: 'Roami chat', taskState: 'waiting_user' }] } : base(method, path, body))
  const first = renderHook(() => useWorkspace(true))
  await waitFor(() => expect(first.result.current.directory.sessListLoaded).toBe(true))
  act(() => first.result.current.workspace.openTerm('roami:native'))
  await waitFor(() => expect(server.active).toBe('roami:native'))
  expect(first.result.current.workspace.terms).toEqual(['alpha', 'roami:native'])
  expect(first.result.current.workspace.overlay).toBe(true)
  first.unmount()
  const next = renderHook(() => useWorkspace())
  await waitFor(() => expect(next.result.current.workspace.active).toBe('roami:native'))
  expect(next.result.current.workspace.terms).toEqual(['alpha', 'roami:native'])
})

it('loads the workspace while the Roami inventory is pending and prunes only after a fresh response', async () => {
  server.terms = ['$1', 'roami:pending']; server.active = 'roami:pending'
  let finish!: (value: unknown) => void
  const base = mock.api.getMockImplementation()!
  mock.api.mockImplementation((method, path, body) => path === '/agent/native-sessions' ? new Promise(resolve => { finish = resolve }) : base(method, path, body))
  const { result } = renderHook(() => useWorkspace())
  await waitFor(() => expect(result.current.workspace.active).toBe('roami:pending'))
  expect(result.current.workspace.terms).toEqual(['alpha', 'roami:pending'])
  await act(async () => { finish({ data: [] }) })
  await waitFor(() => expect(server.terms).toEqual(['$1']))
})

it('keeps session identities and open tabs stable when only Roami activity changes', async () => {
  let state = 'running'
  const base = mock.api.getMockImplementation()!
  mock.api.mockImplementation((method, path, body) => path === '/agent/native-sessions' ? Promise.resolve({ data: [{ nativeSessionId: 'native', taskId: 'task', title: 'Chat', taskState: state }] }) : base(method, path, body))
  const { result } = renderHook(() => useWorkspace())
  await waitFor(() => expect(result.current.directory.sessList.some(session => session.name === 'roami:native')).toBe(true))
  const identities = result.current.directory.sessIds, terms = result.current.workspace.terms
  state = 'succeeded'
  await act(async () => { window.dispatchEvent(new Event('roami:sessions-changed')) })
  await waitFor(() => expect(result.current.directory.sessList.find(session => session.name === 'roami:native')).toMatchObject({ running: false }))
  expect(result.current.directory.sessIds).toBe(identities)
  expect(result.current.workspace.terms).toBe(terms)
})
