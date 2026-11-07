import { useCallback, useEffect, useRef, useState } from 'react'
import { api, openEventStream } from '../../api'
import { agentCacheEpoch, agentDataKey, invalidateAgentData, loadAgentData, peekAgentData, storeAgentData } from './agent-data-cache'
import { publishMemoryEvent } from './agent-memory-events'
import { publishTaskEvent } from './agent-task-events'
import { agentEvents, projectAgentEvent, type AgentSnapshot, type AgentMessage } from './agent-protocol'

export function useAgentThread(cid: string, branch = '', node: string | null = null, focus = '') {
  const path = `/agent/conversations/${encodeURIComponent(cid)}`
  const pagePath = path + '/messages?limit=50' + (branch ? '&branch=' + encodeURIComponent(branch) : '')
  const messages = pagePath + (focus ? '&anchor=' + encodeURIComponent(focus) : '')
  const scope = agentDataKey(messages)
  const cached = () => cid ? peekAgentData<AgentSnapshot>(scope) || null : null
  const [state, setState] = useState<{ scope: string; view: AgentSnapshot | null; loading: boolean; connected: boolean; failed: boolean; loadingOlder?: boolean; olderFailed?: boolean }>(() => ({ scope, view: cached(), loading: !!cid && !cached(), connected: false, failed: false }))
  const refreshRef = useRef<() => void>(() => {})
  const olderRef = useRef<() => Promise<void>>(async () => {})
  const acceptedRef = useRef<(receipt: any, text: string, context?: AgentMessage['content']['okrContext']) => void>(() => {})
  useEffect(() => {
    if (scope !== agentDataKey(messages)) return
    setState({ scope, view: cached(), loading: !!cid && !cached(), connected: false, failed: false })
    if (!cid) { refreshRef.current = () => {}; acceptedRef.current = () => {}; return }
    const abort = new AbortController()
    const owner = agentCacheEpoch()
    let stopped = false, view: AgentSnapshot | null = cached(), connected = false
    let timer: ReturnType<typeof setTimeout> | undefined, retryTimer: ReturnType<typeof setTimeout> | undefined
    let loading = false, again = false, loadingOlder = false, olderFailed = false
    let olderAbort: AbortController | undefined
    const visibility = () => { if (document.hidden) olderAbort?.abort() }
    document.addEventListener('visibilitychange', visibility)
    const publish = () => { if (!stopped && owner === agentCacheEpoch() && scope === agentDataKey(messages)) setState({ scope, view, loading: !view, connected, failed: false, loadingOlder, olderFailed }) }
    const snapshot = async (freshFor = 0) => {
      if (loading) { again = true; return }
      loading = true
      try {
        const data = { ...await loadAgentData<AgentSnapshot>(messages, freshFor) }
        if (stopped) return
        if (!view || data.snapshotCursor >= view.snapshotCursor) {
          if (view && scope === agentDataKey(messages)) for (const item of data.activities || []) {
            const previous = view.activities?.find(old => old.id === item.id)
            if (item.kind === 'task' && (!previous || previous.updatedMs !== item.updatedMs)) publishTaskEvent({ id: data.snapshotCursor, kind: 'task.snapshot', payload: { activity: item } })
          }
          if (view && data.page && view.branchId === data.branchId) {
            const boundary = view.messages.findIndex(item => item.id === data.messages[0]?.id)
            if (boundary >= 0) {
              data.messages = [...view.messages.slice(0, boundary), ...data.messages]
              const latest = new Map((data.activities || []).map(item => [item.id, item]))
              data.activities = [...(view.activities || []).filter(item => !latest.has(item.id)), ...latest.values()]
              data.page = view.page || data.page
            }
          }
          view = data; publish()
        } else again = true
      } finally {
        loading = false
        if (again && !stopped) { again = false; schedule() }
      }
    }
    const schedule = () => {
      if (timer) return
      timer = setTimeout(() => { timer = undefined; void snapshot().catch(() => {}) }, 60)
    }
    refreshRef.current = () => { invalidateAgentData(scope); schedule() }
    acceptedRef.current = (receipt, text, context) => {
      if (!view || !receipt.messageId || view.messages.some((m) => m.id === receipt.messageId)) { schedule(); return }
      const first = view.messages.findIndex(message => message.turn_id === receipt.turnId)
      const index = first < 0 ? view.messages.length : first
      const seq = view.messages[index]?.seq ?? Math.max(0, ...view.messages.map(message => message.seq)) + 1
      const started = view.messages[index]?.created_ms ?? view.activities?.find(activity => activity.id === 'turn:' + receipt.turnId)?.startedMs
      const accepted = { id: receipt.messageId, branch_id: view.branchId, role: 'user', status: 'completed', seq, created_ms: started ?? Date.now(), turn_id: receipt.turnId, content: { text, ...(context ? { okrContext: { version: context.version, revision: context.revision } } : {}) } }
      // SSE can settle this turn before the POST receipt reaches the client.
      view = { ...view,
        messages: [...view.messages.slice(0, index), accepted, ...view.messages.slice(index).map(message => ({ ...message, seq: message.seq + 1 }))],
        turns: view.turns.some(turn => turn.id === receipt.turnId) ? view.turns : [...view.turns, { id: receipt.turnId, state: 'queued' }],
      }
      publish()
    }
    olderRef.current = async () => {
      const before = view?.page?.olderCursor
      if (!view || !before || loadingOlder || document.hidden) return
      const controller = new AbortController(); olderAbort = controller
      const cancel = () => controller.abort()
      abort.signal.addEventListener('abort', cancel, { once: true })
      const timeout = setTimeout(cancel, 15_000)
      loadingOlder = true; olderFailed = false; publish()
      try {
        const { data } = await api('GET', pagePath + '&before=' + encodeURIComponent(before) + (!branch ? '&branch=' + encodeURIComponent(view.branchId) : ''), undefined, { signal: controller.signal })
        if (stopped || controller.signal.aborted || !view || owner !== agentCacheEpoch()) return
        const existing = new Set(view.messages.map(item => item.id))
        const activities = new Map((view.activities || []).map(item => [item.id, item]))
        view = { ...view, messages: [...data.messages.filter((item: AgentSnapshot['messages'][number]) => !existing.has(item.id)), ...view.messages],
          activities: [...(data.activities || []).filter((item: any) => !activities.has(item.id)), ...activities.values()],
          page: data.page?.olderCursor === before ? { hasMore: false, olderCursor: null } : data.page }
      } catch { if (!stopped && !abort.signal.aborted && !document.hidden) olderFailed = true }
      finally { clearTimeout(timeout); abort.signal.removeEventListener('abort', cancel); if (olderAbort === controller) olderAbort = undefined; loadingOlder = false; if (!stopped) publish() }
    }
    const connect = async () => {
      try {
        if (!view) await snapshot(5000)
        if (stopped || !view) return
        const response = await openEventStream(path + '/events?after=' + view.snapshotCursor + '&summaries=true', abort.signal)
        connected = true; publish()
        void snapshot(5000).catch(() => {})
        for await (const event of agentEvents(response)) {
          if (stopped || !view) break
          if (event.id > view.snapshotCursor && scope === agentDataKey(messages)) { publishTaskEvent(event); publishMemoryEvent(event) }
          const projected = projectAgentEvent(view, event)
          view = projected.view; publish()
          if (event.kind === 'memory.forgotten') {
            olderAbort?.abort()
            view = { ...view, messages: [], activities: [], page: undefined }
            storeAgentData(scope, view, owner); invalidateAgentData(scope); publish()
          }
          if (projected.reload) schedule()
        }
      } catch {
        if (!stopped) setState({ scope, view, loading: false, connected: false, failed: true })
      } finally {
        connected = false
        if (!stopped) {
          setState({ scope, view, loading: false, connected: false, failed: true })
          retryTimer = setTimeout(() => { void connect() }, 2000)
        }
      }
    }
    void connect()
    return () => { olderRef.current = async () => {}; if (view) storeAgentData(scope, view, owner); stopped = true; abort.abort(); olderAbort?.abort(); document.removeEventListener('visibilitychange', visibility); clearTimeout(timer); clearTimeout(retryTimer) }
  }, [cid, branch, node, scope, focus])
  return { ...(state.scope === scope ? state : { view: cached(), loading: !!cid && !cached(), connected: false, failed: false, loadingOlder: false, olderFailed: false }), loadOlder: useCallback(() => olderRef.current(), []), refresh: useCallback(() => refreshRef.current(), []), accepted: useCallback((receipt: any, text: string, context?: AgentMessage['content']['okrContext']) => acceptedRef.current(receipt, text, context), []) }
}
