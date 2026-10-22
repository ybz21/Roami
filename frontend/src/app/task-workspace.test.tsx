// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadTabs, saveTabs } from '../components/terminal/term-tabs-store'
import { useSessionDirectory } from './useSessionDirectory'
import { useTaskWorkspace } from './useTaskWorkspace'

vi.mock('../components/shell/useWorkspaceLayout', () => ({ useWorkspaceLayout: () => ({ setDockOpen: vi.fn(), setFocus: vi.fn() }) }))
vi.mock('../components/sessions/session-project', () => ({ useSessionProjects: () => ({}) }))

const mock = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('../api', () => ({ api: mock.api }))

const ids = { byId: { '$1': 'alpha', '$2': 'beta' }, byName: { alpha: '$1', beta: '$2' } }
const go = vi.fn()
function useWorkspace(options: { mobile?: boolean } = {}) {
  const directory = useSessionDirectory()
  return { workspace: useTaskWorkspace({ directory, nodeId: 'node-a', desktop: !options.mobile, mobile: !!options.mobile, page: 'w', navigate: go }), directory }
}

beforeEach(() => {
  localStorage.clear(); go.mockClear(); history.replaceState(null, '', '#/w')
  mock.api.mockReset().mockResolvedValue(Object.entries(ids.byId).map(([id, name]) => ({ id, name })))
})
afterEach(cleanup)

describe('workspace tab lifecycle', () => {
  it('preserves live memory filters and selection when restoring and updating terminal tabs', async () => {
    history.replaceState({ roamiMemoryFrom: '#/home/memory/home' }, '', '#/home/memory/home?memoryView=review&memoryScope=project&memoryEntity=project-a&memoryQuery=Codex&memoryPage=1&memoryId=one&terms=%241&active=%241&node=n1')
    const { result } = renderHook(() => useWorkspace())
    await waitFor(() => expect(result.current.workspace.active).toBe('alpha'))
    const params = () => new URLSearchParams(location.hash.split('?')[1])
    expect(Object.fromEntries(params())).toMatchObject({ memoryView: 'review', memoryScope: 'project', memoryEntity: 'project-a', memoryQuery: 'Codex', memoryPage: '1', memoryId: 'one', node: 'n1' })
    const updated = params(); updated.set('memoryId', 'two')
    history.replaceState(history.state, '', '#/home/memory/home?' + updated)
    act(() => result.current.workspace.openTerm('beta'))
    expect(params().get('memoryId')).toBe('two')
    expect(params().get('memoryQuery')).toBe('Codex')
    act(() => result.current.workspace.closeTerm('beta'))
    expect(params().get('memoryId')).toBe('two')
    expect(history.state.roamiMemoryFrom).toBe('#/home/memory/home')
  })

  it('waits for session identity before restoring URL tabs and node-local files', async () => {
    saveTabs('node-a', ['$2'], '$2', [{ path: '/repo/readme.md', preview: false, mode: 'preview', task: '/repo' }], '/repo/readme.md')
    history.replaceState(null, '', '#/w?terms=%241&active=%241')
    let resolve!: (sessions: { id: string; name: string }[]) => void
    mock.api.mockReturnValueOnce(new Promise(done => { resolve = done }))
    const { result } = renderHook(() => useWorkspace())
    expect(result.current.workspace.terms).toEqual([])
    expect(location.hash).toContain('terms=%241')
    await act(async () => resolve([{ id: '$1', name: 'alpha' }, { id: '$2', name: 'beta' }]))
    await waitFor(() => expect(result.current.workspace.terms).toEqual(['alpha']))
    expect(result.current.workspace.active).toBe('alpha')
    expect(result.current.workspace.activeFile).toBe('/repo/readme.md')
    expect(loadTabs('node-a').terms).toEqual(['$1'])
  })

  it('keeps an explicitly clean page from overwriting another page’s saved tabs', async () => {
    saveTabs('node-a', ['$1'], '$1')
    history.replaceState(null, '', '#/projects?terms=none')
    const { result } = renderHook(() => useWorkspace())
    await waitFor(() => expect(result.current.directory.sessIds).toBeTruthy())
    expect(result.current.workspace.terms).toEqual([])
    expect(loadTabs('node-a').terms).toEqual(['$1'])
    expect(location.hash).toContain('terms=none')
    act(() => result.current.workspace.openTerm('beta'))
    expect(loadTabs('node-a').terms).toEqual(['$2'])
  })

  it('preserves session IDs through renaming and selects a neighboring file on close', async () => {
    history.replaceState(null, '', '#/w?terms=%241&active=%241')
    const { result } = renderHook(() => useWorkspace())
    await waitFor(() => expect(result.current.workspace.active).toBe('alpha'))
    act(() => result.current.workspace.renameOpenTerm('alpha', 'renamed'))
    expect(result.current.workspace.active).toBe('renamed')
    expect(loadTabs('node-a').terms).toEqual(['$1'])
    act(() => result.current.workspace.openFileTab('/repo/one.md'))
    act(() => result.current.workspace.openFileTab('/repo/two.ts', 12))
    expect(result.current.workspace.reveal?.line).toBe(12)
    act(() => result.current.workspace.closeFileTab('/repo/two.ts'))
    expect(result.current.workspace.activeFile).toBe('/repo/one.md')
    act(() => result.current.workspace.activateSession('renamed'))
    expect(result.current.workspace.activeFile).toBe('')
  })

  it('keeps only the selected session on phones and closes its full-screen overlay', async () => {
    const { result } = renderHook(() => useWorkspace({ mobile: true }))
    await waitFor(() => expect(result.current.directory.sessIds).toBeTruthy())
    act(() => result.current.workspace.openTerm('alpha'))
    act(() => result.current.workspace.openTerm('beta'))
    expect(result.current.workspace.terms).toEqual(['beta'])
    expect(result.current.workspace.overlay).toBe(true)
    act(() => result.current.workspace.closeTerm('beta'))
    expect(result.current.workspace.overlay).toBe(false)
    expect(result.current.workspace.active).toBeNull()
  })
})
