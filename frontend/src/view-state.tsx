import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore, type Dispatch, type MutableRefObject, type ReactNode, type SetStateAction } from 'react'
import { WorkspaceStateStore, type StatePolicy, type ViewStateScope } from './workspace-state'

const WorkspaceState = createContext<WorkspaceStateStore | null>(null)
const ViewState = createContext<ViewStateScope | null>(null)
const PageRetention = createContext(() => () => {})

export function WorkspaceStateProvider({ store, children }: { store?: WorkspaceStateStore; children: ReactNode }) {
  const parent = useContext(WorkspaceState)
  const owned = useRef<WorkspaceStateStore>()
  if (!store && !parent && !owned.current) owned.current = new WorkspaceStateStore()
  const state = store || parent || owned.current!
  useEffect(() => {
    if (parent === state) return
    const warn = (event: BeforeUnloadEvent) => { if (state.hasDrafts()) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [parent, state])
  return <WorkspaceState.Provider value={state}>{children}</WorkspaceState.Provider>
}
export function useWorkspaceStateStore() {
  const parent = useContext(WorkspaceState)
  const owned = useRef<WorkspaceStateStore>()
  if (!parent && !owned.current) owned.current = new WorkspaceStateStore()
  return parent || owned.current!
}
export function ViewStateProvider({ scope, retain, children }: { scope: ViewStateScope; retain?: () => () => void; children: ReactNode }) {
  const inherited = useContext(PageRetention)
  return <ViewState.Provider value={scope}><PageRetention.Provider value={retain || inherited}>{children}</PageRetention.Provider></ViewState.Provider>
}
export function useViewRetention() { return useContext(PageRetention) }

export function useViewScope(override?: ViewStateScope | null) {
  const parent = useContext(ViewState), store = useWorkspaceStateStore(), id = useId()
  const inherited = override === null ? null : override || parent
  const scope = useMemo(() => inherited || store.scope('instance', id), [inherited, store, id])
  useEffect(() => () => { if (!inherited) scope.clear() }, [inherited, scope])
  return scope
}

export function useViewState<T,>(key: string, initial: T | (() => T), options?: { scope?: ViewStateScope | null; policy?: StatePolicy }): [T, Dispatch<SetStateAction<T>>] {
  const scope = useViewScope(options?.scope)
  const [fallback] = useState(() => typeof initial === 'function' ? (initial as () => T)() : initial)
  scope.initialize(key, fallback, options?.policy)
  const snapshot = useCallback(() => (scope.has(key) ? scope.get<T>(key) as T : fallback), [scope, key, fallback])
  const subscribe = useCallback((listener: () => void) => scope.subscribe(key, listener), [scope, key])
  const value = useSyncExternalStore(subscribe, snapshot, snapshot)
  const setValue: Dispatch<SetStateAction<T>> = useCallback(action => {
    const previous = (scope.has(key) ? scope.get<T>(key) as T : fallback)
    scope.set(key, typeof action === 'function' ? (action as (value: T) => T)(previous) : action, options?.policy)
  }, [scope, key, fallback, options?.policy])
  return [value, setValue]
}

// A ref-shaped adapter stores the value, never the React ref or a resource instance.
export function useViewRef<T,>(key: string, initial: T, policy: StatePolicy = 'view'): MutableRefObject<T> {
  const scope = useViewScope()
  return useMemo(() => ({ get current() { return (scope.has(key) ? scope.get<T>(key) as T : initial) }, set current(value: T) { scope.set(key, value, policy) } }), [scope, key, policy])
}
