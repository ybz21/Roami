import { usePageEffect } from '../../page-activity'
import { useCallback, useRef, useState } from 'react'
import { api, openEventStream } from '../../api'
import { agentEvents } from '../agent/agent-protocol'
import { nodeApi } from '../cluster/node-url'
import type { SwarmSnapshot } from './swarm-protocol'

type SwarmSnapshotState = { scope: string; data: SwarmSnapshot | null; error: boolean; missing: boolean }
const emptySnapshot = (scope: string): SwarmSnapshotState => ({ scope, data: null, error: false, missing: false })

const inflight = new Map<string, Promise<SwarmSnapshot>>()
function load(path: string) {
  const key = nodeApi(path)
  let request = inflight.get(key)
  if (!request) {
    request = api('GET', path).then(r => r.data as SwarmSnapshot).finally(() => inflight.delete(key))
    inflight.set(key, request)
  }
  return request
}
export function useSwarmSnapshot(id: string) {
  const path = `/agent/swarms/${encodeURIComponent(id)}`, scope = nodeApi(path)
  const [snapshot, setSnapshot] = useState(() => emptySnapshot(scope))
  // Children must never commit an old node's data before passive cleanup.
  const { data, error, missing } = snapshot.scope === scope ? snapshot : emptySnapshot(scope)
  const update = useCallback((patch: Partial<Omit<SwarmSnapshotState, 'scope'>>) => {
    setSnapshot(previous => ({ ...(previous.scope === scope ? previous : emptySnapshot(scope)), ...patch }))
  }, [scope])
  const dataRef = useRef(data), mounted = useRef(false)
  const currentScope = useRef(scope); currentScope.current = scope
  dataRef.current = data
  const refresh = useCallback(async () => {
    if (!/^sw-[a-f0-9]{32}$/.test(id)) { update({ missing: true }); return }
    try { const next = await load(path); if (mounted.current && currentScope.current === scope) { update({ data: next, error: false, missing: false }) } }
    catch (cause) { if (mounted.current && currentScope.current === scope) { const absent = (cause as { status?: number }).status === 404; update({ missing: absent, error: !absent, ...(absent ? { data: null } : {}) }); if (absent) dataRef.current = null } }
  }, [scope])
  usePageEffect(() => {
    mounted.current = true; update({ data: null, error: false, missing: false }); dataRef.current = null
    if (!/^sw-[a-f0-9]{32}$/.test(id)) { update({ missing: true }); return () => { mounted.current = false } }
    let stopped = false, abort: AbortController | null = null, timer: ReturnType<typeof setTimeout> | undefined, failures = 0
    const connect = async () => {
      if (stopped || document.hidden) return
      abort?.abort(); abort = new AbortController()
      const currentAbort = abort
      try {
        const next = await load(path)
        if (stopped || document.hidden || currentAbort.signal.aborted) return
        update({ data: next, error: false, missing: false }); dataRef.current = next
        const response = await openEventStream(`${path}/events?after=${next.sequence}`, currentAbort.signal)
        for await (const event of agentEvents(response)) {
          if (stopped || currentAbort.signal.aborted) return
          const snapshot = event.payload as SwarmSnapshot
          if (snapshot.id !== id || snapshot.sequence <= (dataRef.current?.sequence ?? 0)) continue
          update({ data: snapshot, error: false }); dataRef.current = snapshot; failures = 0
        }
        throw new Error('STREAM_ENDED')
      } catch (cause) {
        if (stopped || currentAbort.signal.aborted || document.hidden) return
        if ((cause as { status?: number }).status === 404) { update({ data: null, missing: true, error: false }); dataRef.current = null; return }
        update({ error: true }); timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** failures++))
      }
    }
    const visible = () => { clearTimeout(timer); if (document.hidden) abort?.abort(); else { failures = 0; void connect() } }
    document.addEventListener('visibilitychange', visible); void connect()
    return () => { stopped = true; mounted.current = false; clearTimeout(timer); abort?.abort(); document.removeEventListener('visibilitychange', visible) }
  }, [scope])
  return { data, error, missing, refresh }
}
