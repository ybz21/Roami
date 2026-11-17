import { createContext, useContext, useEffect, useSyncExternalStore, type DependencyList, type EffectCallback, type ReactNode } from 'react'

const PageActivity = createContext(true)
const subscribeVisibility = (listener: () => void) => {
  document.addEventListener('visibilitychange', listener)
  return () => document.removeEventListener('visibilitychange', listener)
}
const documentVisible = () => !document.hidden

export function PageActivityProvider({ active, children }: { active: boolean; children: ReactNode }) {
  const visible = useSyncExternalStore(subscribeVisibility, documentVisible, () => true)
  return <PageActivity.Provider value={active && visible}>{children}</PageActivity.Provider>
}

export function usePageActive() { return useContext(PageActivity) }

// Suspend subscriptions and recurring work without discarding the page's local state.
export function usePageEffect(effect: EffectCallback, dependencies?: DependencyList) {
  const active = usePageActive()
  useEffect(() => active ? effect() : undefined, dependencies ? [active, ...dependencies] : undefined)
}
