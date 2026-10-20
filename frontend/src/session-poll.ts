import { useMemo, useSyncExternalStore } from 'react'
import { api } from './api'
import { currentNodeId, useCurrentNodeId } from './components/cluster/node-url'
import { pollWhileVisible } from './visible-poll'

/** Consumers on the same machine share a request and an unchanged snapshot. */
export function createSessionPoll<T>(path: string, interval: number, initial: T, read: (response: any) => T) {
  const empty = { value: initial, failed: false }
  let current: { node: string | null; store: ReturnType<typeof createStore> } | undefined
  const idleSubscribe = () => () => {}
  const emptySnapshot = () => empty

  function createStore(node: string | null) {
    let snapshot = empty, signature = JSON.stringify(initial)
    let poll: ReturnType<typeof pollWhileVisible> | undefined
    const listeners = new Set<() => void>()
    const emit = () => listeners.forEach(listener => listener())
    const load = async (signal: AbortSignal) => {
      if (currentNodeId() !== node) return
      try {
        const next = read(await api('GET', path, undefined, { signal }))
        if (signal.aborted || currentNodeId() !== node) return
        const nextSignature = JSON.stringify(next)
        if (nextSignature !== signature || snapshot.failed) {
          const value = nextSignature === signature ? snapshot.value : next
          signature = nextSignature
          snapshot = { value, failed: false }; emit()
        }
      } catch (error) {
        if (!signal.aborted && currentNodeId() === node && !snapshot.failed) {
          snapshot = { ...snapshot, failed: true }; emit()
        }
        throw error
      }
    }
    return {
      getSnapshot: () => snapshot,
      subscribe: (listener: () => void) => {
        listeners.add(listener)
        if (listeners.size === 1) poll = pollWhileVisible(load, interval)
        return () => {
          listeners.delete(listener)
          if (!listeners.size) { poll?.stop(); poll = undefined }
        }
      },
    }
  }

  return function useSessionPoll(enabled = true) {
    const node = useCurrentNodeId()
    const store = useMemo(() => {
      if (!current || current.node !== node) current = { node, store: createStore(node) }
      return current.store
    }, [node])
    return useSyncExternalStore(enabled ? store.subscribe : idleSubscribe, enabled ? store.getSnapshot : emptySnapshot, emptySnapshot)
  }
}
