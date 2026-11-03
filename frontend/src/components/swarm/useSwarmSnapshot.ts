import { useCallback, useEffect, useRef, useState } from 'react'
import { api, openEventStream } from '../../api'
import { agentEvents } from '../agent/agent-protocol'
import { nodeApi } from '../cluster/node-url'
import type { SwarmSnapshot } from './swarm-protocol'

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
  const [data, setData] = useState<SwarmSnapshot | null>(null), [error, setError] = useState(false)
  const dataRef = useRef(data), mounted = useRef(false)
  const currentScope = useRef(scope); currentScope.current = scope
  dataRef.current = data
  const refresh = useCallback(async () => {
    try { const next = await load(path); if (mounted.current && currentScope.current === scope) { setData(next); setError(false) } }
    catch { if (mounted.current && currentScope.current === scope) setError(true) }
  }, [scope])
  useEffect(() => {
    mounted.current = true; setData(null); dataRef.current = null
    let stopped = false, abort: AbortController | null = null, timer: ReturnType<typeof setTimeout> | undefined, failures = 0
    const connect = async () => {
      if (stopped || document.hidden) return
      abort?.abort(); abort = new AbortController()
      const currentAbort = abort
      try {
        const next = await load(path)
        if (stopped || document.hidden || currentAbort.signal.aborted) return
        setData(next); dataRef.current = next; setError(false)
        const response = await openEventStream(`${path}/events?after=${next.sequence}`, currentAbort.signal)
        for await (const event of agentEvents(response)) {
          if (stopped || currentAbort.signal.aborted) return
          const snapshot = event.payload as SwarmSnapshot
          if (snapshot.id !== id || snapshot.sequence <= (dataRef.current?.sequence ?? 0)) continue
          setData(snapshot); dataRef.current = snapshot; setError(false); failures = 0
        }
        throw new Error('STREAM_ENDED')
      } catch {
        if (stopped || currentAbort.signal.aborted || document.hidden) return
        setError(true); timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** failures++))
      }
    }
    const visible = () => { clearTimeout(timer); if (document.hidden) abort?.abort(); else { failures = 0; void connect() } }
    document.addEventListener('visibilitychange', visible); void connect()
    return () => { stopped = true; mounted.current = false; clearTimeout(timer); abort?.abort(); document.removeEventListener('visibilitychange', visible) }
  }, [scope])
  return { data, error, refresh }
}
