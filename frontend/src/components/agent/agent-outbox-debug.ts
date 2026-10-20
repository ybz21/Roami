import { useSyncExternalStore } from 'react'
import type { OutboxMessage } from './useAgentOutbox'

type OutboxDebug = { items: { id: string; state: OutboxMessage['state']; attachments: number }[]; paused: boolean; sending: string }
const snapshots = new Map<string, OutboxDebug>(), subscribers = new Set<() => void>()
const empty: OutboxDebug = { items: [], paused: false, sending: '' }

function outboxMetadata(value: { items: OutboxMessage[]; paused: boolean }, sending: string): OutboxDebug {
  return { items: value.items.map(item => ({ id: item.id, state: item.id === sending ? 'sending' : item.state, attachments: item.attachments.length })), paused: value.paused, sending }
}

export function publishOutboxDebug(scope: string, value: { items: OutboxMessage[]; paused: boolean }, sending = '') {
  const next = outboxMetadata(value, sending)
  if (JSON.stringify(snapshots.get(scope)) === JSON.stringify(next)) return
  snapshots.set(scope, next)
  subscribers.forEach(listener => listener())
}

function snapshot(scope: string): OutboxDebug {
  if (!snapshots.has(scope)) {
    try {
      const value = JSON.parse(localStorage.getItem('roami.agent.outbox.' + scope) || 'null')
      if (value && Array.isArray(value.items)) snapshots.set(scope, outboxMetadata({ ...value, items: value.items.map((item: OutboxMessage) => ({ ...item, state: item.state === 'sending' ? 'unconfirmed' : item.state })) }, ''))
    } catch {}
    if (!snapshots.has(scope)) snapshots.set(scope, empty)
  }
  return snapshots.get(scope)!
}

export function useAgentOutboxDebug(scope: string) {
  return useSyncExternalStore(listener => {
    subscribers.add(listener)
    const storage = (event: StorageEvent) => { if (event.key === 'roami.agent.outbox.' + scope) { snapshots.delete(scope); listener() } }
    window.addEventListener('storage', storage)
    return () => { subscribers.delete(listener); window.removeEventListener('storage', storage) }
  }, () => snapshot(scope))
}
