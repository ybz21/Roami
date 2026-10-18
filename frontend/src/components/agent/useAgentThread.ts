import { useCallback, useEffect, useRef, useState } from 'react'
import { api, openEventStream } from '../../api'
import { agentEvents, projectAgentEvent, type AgentSnapshot } from './agent-protocol'

export function useAgentThread(cid: string, branch = '') {
  const [state, setState] = useState<{ view: AgentSnapshot | null; loading: boolean; connected: boolean; failed: boolean }>({ view: null, loading: !!cid, connected: false, failed: false })
  const refreshRef = useRef<() => void>(() => {})
  const acceptedRef = useRef<(receipt: any, text: string) => void>(() => {})
  useEffect(() => {
    setState({ view: null, loading: !!cid, connected: false, failed: false })
    if (!cid) { refreshRef.current = () => {}; acceptedRef.current = () => {}; return }
    const abort = new AbortController()
    const path = `/agent/conversations/${encodeURIComponent(cid)}`
    let stopped = false, view: AgentSnapshot | null = null, connected = false
    let timer: ReturnType<typeof setTimeout> | undefined, retryTimer: ReturnType<typeof setTimeout> | undefined
    let loading = false, again = false
    const publish = () => { if (!stopped) setState({ view, loading: !view, connected, failed: false }) }
    const snapshot = async () => {
      if (loading) { again = true; return }
      loading = true
      try {
        const { data } = await api('GET', path + '/messages' + (branch ? '?branch=' + encodeURIComponent(branch) : ''), undefined, { signal: abort.signal })
        if (stopped) return
        if (!view || data.snapshotCursor >= view.snapshotCursor) { view = data; publish() } else again = true
      } finally {
        loading = false
        if (again && !stopped) { again = false; schedule() }
      }
    }
    const schedule = () => {
      if (timer) return
      timer = setTimeout(() => { timer = undefined; void snapshot().catch(() => {}) }, 60)
    }
    refreshRef.current = schedule
    acceptedRef.current = (receipt, text) => {
      if (!view || !receipt.messageId || view.messages.some((m) => m.id === receipt.messageId)) { schedule(); return }
      view = { ...view, messages: [...view.messages, { id: receipt.messageId, branch_id: view.branchId, role: 'user', status: 'completed', seq: Math.max(0, ...view.messages.map((m) => m.seq)) + 1, created_ms: Date.now(), turn_id: receipt.turnId, content: { text } }], turns: [...view.turns, { id: receipt.turnId, state: 'queued' }] }
      publish()
    }
    const connect = async () => {
      try {
        await snapshot()
        if (stopped || !view) return
        const response = await openEventStream(path + '/events?after=' + view.snapshotCursor, abort.signal)
        connected = true; publish()
        for await (const event of agentEvents(response)) {
          if (stopped || !view) break
          const projected = projectAgentEvent(view, event)
          view = projected.view; publish()
          if (projected.reload) schedule()
        }
      } catch {
        if (!stopped) setState({ view, loading: false, connected: false, failed: true })
      } finally {
        connected = false
        if (!stopped) {
          setState({ view, loading: false, connected: false, failed: true })
          retryTimer = setTimeout(() => { void connect() }, 2000)
        }
      }
    }
    void connect()
    return () => { stopped = true; abort.abort(); clearTimeout(timer); clearTimeout(retryTimer) }
  }, [cid, branch])
  return { ...state, refresh: useCallback(() => refreshRef.current(), []), accepted: useCallback((receipt: any, text: string) => acceptedRef.current(receipt, text), []) }
}
