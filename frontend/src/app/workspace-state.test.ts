import { describe, expect, it, vi } from 'vitest'
import { applyWorkspaceChange, createWorkspaceState, type WorkspaceChange, type WorkspaceState } from './workspace-state'

const empty = (): WorkspaceState => ({ revision: 0, terms: [], active: '', files: [], activeFile: '' })
function backend(initial = empty()) {
  let server = initial
  const request = vi.fn(async (method: string, _path: string, body?: unknown) => {
    if (method === 'PATCH') {
      const patch = body as { seed?: WorkspaceState; changes: WorkspaceChange[] }
      if (!server.revision && patch.seed) server = { ...patch.seed, revision: 0 }
      for (const change of patch.changes) server = applyWorkspaceChange(server, change)
      server = { ...server, revision: server.revision + 1 }
    }
    return { data: structuredClone(server) }
  })
  return { request, state: () => server }
}

describe('workspace synchronization', () => {
  it('merges edits from stale clients, shares selection, and restores a clean client', async () => {
    const remote = backend({ ...empty(), revision: 1, terms: ['base'], active: 'base' })
    const desktop = createWorkspaceState(remote.request, empty, vi.fn())
    const phone = createWorkspaceState(remote.request, empty, vi.fn())
    await Promise.all([desktop.refresh(), phone.refresh()])
    desktop.update(state => ({ ...state, terms: [...state.terms, 'desktop'], active: 'desktop' }))
    phone.update(state => ({ ...state, terms: [...state.terms, 'phone'], active: 'phone' }))
    await Promise.all([desktop.refresh(), phone.refresh()])
    expect(remote.state().terms).toEqual(['base', 'desktop', 'phone'])
    phone.update(state => ({ ...state, terms: state.terms.filter(id => id !== 'base') }))
    await phone.refresh()
    await desktop.refresh()
    expect(desktop.getSnapshot().state.terms).toEqual(['desktop', 'phone'])
    expect(desktop.getSnapshot().state.active).toBe('phone')
    const fresh = createWorkspaceState(remote.request, empty, vi.fn())
    await fresh.refresh()
    expect(fresh.getSnapshot()).toEqual(desktop.getSnapshot())
  })

  it('preserves optimistic edits across failure and retries without dropping remote tabs', async () => {
    const remote = backend({ ...empty(), revision: 1, terms: ['remote'], active: 'remote' })
    const store = createWorkspaceState(remote.request, empty, vi.fn())
    await store.refresh()
    remote.request.mockRejectedValueOnce(new Error('offline'))
    store.update(state => ({ ...state, terms: [...state.terms, 'local'], active: 'local' }))
    await expect(store.refresh()).rejects.toThrow('offline')
    expect(store.getSnapshot().state.terms).toEqual(['remote', 'local'])
    expect(store.getSnapshot().error).toBe(true)
    await store.refresh()
    expect(remote.state().terms).toEqual(['remote', 'local'])
    expect(store.getSnapshot().error).toBe(false)
  })

  it('does not revive closed tabs from old browser state and keeps stable snapshot references', async () => {
    const remote = backend({ ...empty(), revision: 7 })
    const seed = vi.fn(() => ({ ...empty(), terms: ['obsolete'], active: 'obsolete' }))
    const store = createWorkspaceState(remote.request, seed, vi.fn())
    await store.refresh()
    const snapshot = store.getSnapshot()
    await store.refresh()
    expect(store.getSnapshot()).toBe(snapshot)
    expect(seed).not.toHaveBeenCalled()
    expect(remote.request).not.toHaveBeenCalledWith('PATCH', expect.anything(), expect.anything())
  })
})
