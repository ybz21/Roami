import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import { agentCacheEpoch, agentDataKey, peekAgentData, storeAgentData } from './agent-data-cache'
import { useAgentData } from './useAgentData'

export type AgentPage<T> = { items: T[]; nextCursor: string | null }
type Extra<T> = { scope: string; items: T[]; cursor?: string | null; failed: boolean; loading: boolean }

export function usePagedAgentData<T extends { id: string | number }>(path: string | null, pollMs = 0) {
  const scope = path ? agentDataKey(path) : '', cacheKey = 'pages ' + scope
  const cached = () => peekAgentData<Extra<T>>(cacheKey)
  const first = useAgentData<AgentPage<T>>(path, 5000, pollMs)
  const [extra, setExtra] = useState<Extra<T>>(() => cached() || { scope, items: [], failed: false, loading: false })
  const state = extra.scope === scope ? extra : cached() || { scope, items: [], failed: false, loading: false }
  const current = useRef(scope); current.current = scope
  const pending = useRef<AbortController | null>(null)
  const epoch = agentCacheEpoch()
  const cursor = state.cursor === undefined ? first.value?.nextCursor : state.cursor
  const items = useMemo(() => {
    const latest = first.value?.items || [], ids = new Set(latest.map(item => item.id))
    return [...latest, ...state.items.filter(item => !ids.has(item.id))]
  }, [first.value, state.items])
  const loadMore = useCallback(async () => {
    if (!path || !cursor || pending.current || document.hidden) return
    const controller = new AbortController(); pending.current = controller
    let timedOut = false
    const timeout = setTimeout(() => { timedOut = true; controller.abort() }, 15_000)
    setExtra(previous => ({ ...(previous.scope === scope ? previous : state), failed: false, loading: true }))
    try {
      const { data } = await api('GET', path + (path.includes('?') ? '&' : '?') + 'before=' + encodeURIComponent(cursor), undefined, { signal: controller.signal })
      if (controller.signal.aborted || current.current !== scope || agentCacheEpoch() !== epoch) return
      setExtra(previous => {
        const next = { scope, items: [...new Map([...items, ...data.items].map(item => [item.id, item])).values()] as T[], cursor: data.nextCursor === cursor ? null : data.nextCursor, loading: false, failed: false }
        storeAgentData(cacheKey, next, epoch)
        return next
      })
    } catch {
      if ((!controller.signal.aborted || timedOut) && current.current === scope) setExtra(previous => ({ ...previous, scope, loading: false, failed: true }))
    } finally {
      clearTimeout(timeout)
      if (pending.current === controller) pending.current = null
    }
  }, [path, cursor, scope, epoch, cacheKey, state, items])
  useEffect(() => {
    setExtra(previous => previous.scope === scope ? previous : cached() || { scope, items: [], failed: false, loading: false })
    const cancel = () => { if (document.hidden) { pending.current?.abort(); pending.current = null; setExtra(previous => ({ ...previous, loading: false })) } }
    document.addEventListener('visibilitychange', cancel)
    return () => { pending.current?.abort(); pending.current = null; document.removeEventListener('visibilitychange', cancel) }
  }, [scope])
  const refresh = useCallback(() => {
    pending.current?.abort(); pending.current = null
    const empty = { scope, items: [] as T[], failed: false, loading: false }
    storeAgentData(cacheKey, empty, epoch); setExtra(empty); first.refresh()
  }, [scope, cacheKey, epoch, first.refresh])
  return { ...first, refresh, items, hasMore: !!cursor, loadingMore: state.loading, moreFailed: state.failed, loadMore }
}
