import { useEffect, useRef, useState } from 'react'
import type { AgentAttachment } from './useAgentAttachments'
import { publishOutboxDebug } from './agent-outbox-debug'

export type OutboxMessage = { id: string; text: string; attachments: AgentAttachment[]; state: 'waiting' | 'sending' | 'unconfirmed' | 'failed' }
type OutboxState = { items: OutboxMessage[]; paused: boolean }
const prefix = 'roami.agent.outbox.'
function read(scope: string): OutboxState {
  try {
    const saved = JSON.parse(localStorage.getItem(prefix + scope) || 'null')
    if (saved && Array.isArray(saved.items) && saved.items.every((item: OutboxMessage) => typeof item.id === 'string' && typeof item.text === 'string' && Array.isArray(item.attachments) && item.attachments.every(file => typeof file.id === 'string' && typeof file.name === 'string') && ['waiting', 'sending', 'unconfirmed', 'failed'].includes(item.state))) return { paused: saved.paused === true, items: saved.items.map((item: OutboxMessage) => ({ ...item, state: item.state === 'sending' ? 'unconfirmed' : item.state })) }
  } catch {}
  return { items: [], paused: false }
}

export function useAgentOutbox(scope: string, ready: boolean, idle: boolean, send: (item: OutboxMessage) => Promise<void>) {
  const snapshots = useRef<Record<string, OutboxState>>({})
  const [version, setVersion] = useState(0), [storageFailed, setStorageFailed] = useState(false), [forced, setForced] = useState('')
  const active = useRef(scope); active.current = scope
  const sender = useRef(send); sender.current = send
  const flight = useRef<{ scope: string; id: string } | null>(null)
  const mounted = useRef(true)
  const current = snapshots.current[scope] ||= read(scope)
  useEffect(() => { publishOutboxDebug(scope, current, flight.current?.scope === scope ? flight.current.id : '') }, [scope, current, version])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { setStorageFailed(false); setForced('') }, [scope])
  useEffect(() => {
    const sync = (event: StorageEvent) => { if (event.key === prefix + scope) { snapshots.current[scope] = read(scope); setVersion(value => value + 1) } }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [scope])
  const change = (owner: string, apply: (previous: OutboxState) => OutboxState) => {
    const next = apply(read(owner))
    try { if (next.items.length || next.paused) localStorage.setItem(prefix + owner, JSON.stringify(next)); else localStorage.removeItem(prefix + owner) }
    catch { if (mounted.current && active.current === owner) setStorageFailed(true); return false }
    snapshots.current[owner] = next
    publishOutboxDebug(owner, next, flight.current?.scope === owner ? flight.current.id : '')
    if (mounted.current) { if (active.current === owner) setStorageFailed(false); setVersion(value => value + 1) }
    return true
  }
  useEffect(() => {
    if (!ready || flight.current || storageFailed) return
    const selected = forced ? current.items.find(item => item.id === forced) : !current.paused && idle ? current.items[0] : undefined
    if (!selected) { if (forced) setForced(''); return }
    if (selected.state !== 'waiting') return
    const owner = scope, id = selected.id
    if (!change(owner, value => ({ ...value, items: value.items.map(item => item.id === id ? { ...item, state: 'sending' } : item) }))) return
    flight.current = { scope: owner, id }; setForced('')
    // A stable request ID makes a lost receipt safe to retry after refresh.
    void sender.current(selected).then(() => { change(owner, value => ({ ...value, items: value.items.filter(item => item.id !== id) })) }).catch(reason => { change(owner, value => ({ ...value, items: value.items.map(item => item.id === id ? { ...item, state: reason?.apiError ? 'failed' : 'unconfirmed' } : item) })) }).finally(() => { flight.current = null; publishOutboxDebug(owner, snapshots.current[owner] || read(owner)); if (mounted.current) setVersion(value => value + 1) })
  }, [scope, ready, idle, current, forced, storageFailed, version])
  const locked = (id: string) => flight.current?.scope === scope && flight.current.id === id
  return {
    items: current.items, paused: current.paused, storageFailed,
    enqueue: (text: string, attachments: AgentAttachment[]) => change(scope, value => ({ ...value, items: [...value.items, { id: crypto.randomUUID(), text, attachments, state: 'waiting' }] })),
    pause: (paused: boolean) => change(scope, value => ({ ...value, paused })),
    remove: (id: string) => !locked(id) && change(scope, value => ({ ...value, items: value.items.filter(item => item.id !== id) })),
    edit: (id: string, text: string) => !locked(id) && change(scope, value => ({ ...value, items: value.items.map(item => item.id === id && item.state === 'waiting' ? { ...item, text } : item) })),
    retry: (id: string) => { setStorageFailed(false); return !locked(id) && change(scope, value => ({ ...value, items: value.items.map(item => item.id === id ? { ...item, state: 'waiting' } : item) })) },
    sendNow: (id: string) => { if (ready && !flight.current) setForced(id) },
    sending: flight.current?.scope === scope ? flight.current.id : '',
  }
}
