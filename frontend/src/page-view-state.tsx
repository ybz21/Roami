import { createContext, useCallback, useContext, useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'

const PageViewState = createContext<Map<string, unknown> | undefined>(undefined)
const PageRetention = createContext(() => () => {})

export function PageViewStateProvider({ memory, retain, children }: { memory: Map<string, unknown>; retain: () => () => void; children: ReactNode }) {
  return <PageViewState.Provider value={memory}><PageRetention.Provider value={retain}>{children}</PageRetention.Provider></PageViewState.Provider>
}

// Mutations keep their controller until completion, even when navigation hides the page.
export function usePageRetention() { return useContext(PageRetention) }

// Store controls and drafts here; reloadable payloads belong to the mounted view.
export function usePageViewState<T,>(key: string, initial: T | (() => T)) {
  const memory = useContext(PageViewState)
  const [value, update] = useState<T>(() => memory?.has(key) ? memory.get(key) as T : typeof initial === 'function' ? (initial as () => T)() : initial)
  const latest = useRef(value)
  const setValue: Dispatch<SetStateAction<T>> = useCallback(action => {
    const next = typeof action === 'function' ? (action as (previous: T) => T)(latest.current) : action
    latest.current = next
    memory?.set(key, next)
    update(next)
  }, [key, memory])
  return [value, setValue] as const
}

export function usePageViewRef<T,>(key: string, initial: T) {
  const memory = useContext(PageViewState)
  const value = useRef<T>(memory?.has(key) ? (memory.get(key) as { current: T }).current : initial)
  useEffect(() => { memory?.set(key, value) }, [key, memory, value])
  return value
}
