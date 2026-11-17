import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { WorkspaceStateProvider, useViewScope, useViewState } from '../../view-state'
import type { StatePolicy, ViewStateScope } from '../../workspace-state'

const FileWorkspaceState = createContext<ViewStateScope | null>(null)

export function FileWorkspaceStateProvider({ scope, children }: { scope?: ViewStateScope; children: ReactNode }) {
  const inherited = useViewScope(scope)
  return <WorkspaceStateProvider store={inherited.store}><FileWorkspaceState.Provider value={inherited}>{children}</FileWorkspaceState.Provider></WorkspaceStateProvider>
}
export function useFileWorkspaceState<T,>(key: string, initial: T | (() => T), policy?: StatePolicy) {
  const scope = useContext(FileWorkspaceState)
  return useViewState(key, initial, { scope, policy })
}
export function useFileResourceScope(path: string, preview = false) {
  const workspace = useContext(FileWorkspaceState), inherited = useViewScope()
  const parent = workspace || inherited
  return useMemo(() => parent.child('file', path, preview ? 'preview' : 'source'), [parent, path, preview])
}
export function useForgetFilePageView() {
  const workspace = useContext(FileWorkspaceState)
  return (path: string, preview = false) => workspace?.child('file', path, preview ? 'preview' : 'source').clear()
}
