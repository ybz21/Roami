import type { TabSet } from '../components/terminal/term-tabs-store'

export type WorkspaceState = TabSet & { revision: number }
export type WorkspaceChange = {
  add?: string[]; remove?: string[]; order?: string[]; active?: string
  files?: TabSet['files']; removeFiles?: string[]; activeFile?: string
}
type Request = (method: string, path: string, body?: unknown, options?: { signal?: AbortSignal }) => Promise<{ data: WorkspaceState }>
const empty = (): WorkspaceState => ({ revision: 0, terms: [], active: '', files: [], activeFile: '' })

export function applyWorkspaceChange(state: WorkspaceState, change: WorkspaceChange): WorkspaceState {
  let terms = [...new Set([...state.terms.filter(id => !change.remove?.includes(id)), ...change.add || []])]
  if (change.order) terms = [...new Set([...change.order, ...terms])].filter(id => terms.includes(id))
  const selected = change.active ?? state.active
  const active = terms.includes(selected) ? selected : terms[terms.length - 1] || ''
  const files = state.files.filter(file => !change.removeFiles?.includes(file.path)).map(file => change.files?.find(f => f.path === file.path) || file)
  files.push(...(change.files || []).filter(file => !files.some(f => f.path === file.path)))
  const selectedFile = change.activeFile ?? state.activeFile
  return { ...state, terms, active, files, activeFile: files.some(f => f.path === selectedFile) ? selectedFile : '' }
}

export function workspaceChange(before: TabSet, after: TabSet): WorkspaceChange {
  const change: WorkspaceChange = {}
  const add = after.terms.filter(id => !before.terms.includes(id))
  const remove = before.terms.filter(id => !after.terms.includes(id))
  if (add.length) change.add = add
  if (remove.length) change.remove = remove
  if (JSON.stringify(before.terms.filter(id => after.terms.includes(id))) !== JSON.stringify(after.terms.filter(id => before.terms.includes(id)))) change.order = after.terms
  if (before.active !== after.active) change.active = after.active
  const files = after.files.filter(file => JSON.stringify(file) !== JSON.stringify(before.files.find(f => f.path === file.path)))
  const removeFiles = before.files.filter(file => !after.files.some(f => f.path === file.path)).map(file => file.path)
  if (files.length) change.files = files
  if (removeFiles.length) change.removeFiles = removeFiles
  if (before.activeFile !== after.activeFile) change.activeFile = after.activeFile
  return change
}

export function createWorkspaceState(request: Request, seed: () => TabSet, migrated: () => void) {
  let server = empty()
  let snapshot = { state: server, loaded: false, error: false }
  let pending: WorkspaceChange[] = []
  let inFlight: Promise<void> | undefined
  const listeners = new Set<() => void>()
  const emit = (loaded = snapshot.loaded, error = snapshot.error) => {
    const state = pending.reduce(applyWorkspaceChange, server)
    if (JSON.stringify(state) === JSON.stringify(snapshot.state) && loaded === snapshot.loaded && error === snapshot.error) return
    if (JSON.stringify(state.terms) === JSON.stringify(snapshot.state.terms)) state.terms = snapshot.state.terms
    if (JSON.stringify(state.files) === JSON.stringify(snapshot.state.files)) state.files = snapshot.state.files
    snapshot = { state, loaded, error }
    listeners.forEach(listener => listener())
  }
  const accept = (state: WorkspaceState) => { if (state.revision >= server.revision) server = state }
  const write = async (body: unknown) => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 15_000)
    try { return (await request('PATCH', '/workspace', body, { signal: controller.signal })).data }
    finally { clearTimeout(timer) }
  }
  const refresh = (signal?: AbortSignal): Promise<void> => {
    if (inFlight) return inFlight
    inFlight = (async () => {
      const controller = new AbortController()
      const abort = () => controller.abort()
      if (signal?.aborted) abort()
      signal?.addEventListener('abort', abort, { once: true })
      const timer = setTimeout(abort, 15_000)
      try { accept((await request('GET', '/workspace', undefined, { signal: controller.signal })).data) }
      finally { clearTimeout(timer); signal?.removeEventListener('abort', abort) }
      if (server.revision === 0) accept(await write({ seed: seed(), changes: [] }))
      migrated()
      emit(true, pending.length > 0 && snapshot.error)
      while (pending.length) {
        const batch = pending.slice()
        accept(await write({ changes: batch }))
        pending = pending.slice(batch.length)
        emit(true, false)
      }
    })().catch(error => {
      if (!signal?.aborted) emit(snapshot.loaded, true)
      throw error
    }).finally(() => { inFlight = undefined })
    return inFlight
  }
  return {
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
    getSnapshot: () => snapshot,
    refresh,
    update: (update: (state: WorkspaceState) => TabSet) => {
      const change = workspaceChange(snapshot.state, update(snapshot.state))
      if (!Object.keys(change).length) return
      pending.push(change)
      emit()
      // Batch synchronous tab and selection changes into a single write.
      void Promise.resolve().then(() => refresh()).catch(() => {})
    },
  }
}
