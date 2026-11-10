import { useCallback, useSyncExternalStore } from 'react'
import { nodeApi } from '../cluster/node-url'

const listeners = new Map<string, Set<() => void>>()
const empty = () => ''

// The pending view and the inspector may both be mounted for the same session.
export function useLifecycleDraft(name: string) {
  const key = nodeApi('/sessions/' + name) + ':lifecycle-draft'
  const subscribe = useCallback((listener: () => void) => {
    const subscribers = listeners.get(key) || new Set<() => void>()
    listeners.set(key, subscribers); subscribers.add(listener)
    const storage = (event: StorageEvent) => { if (event.key === key || event.key === null) listener() }
    window.addEventListener('storage', storage)
    return () => { subscribers.delete(listener); if (!subscribers.size) listeners.delete(key); window.removeEventListener('storage', storage) }
  }, [key])
  const snapshot = useCallback(() => localStorage.getItem(key) || '', [key])
  const draft = useSyncExternalStore(subscribe, snapshot, empty)
  const setDraft = useCallback((text: string) => {
    if (text) localStorage.setItem(key, text); else localStorage.removeItem(key)
    listeners.get(key)?.forEach(listener => listener())
  }, [key])
  return { draft, setDraft }
}
