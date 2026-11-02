import { useEffect, useMemo, useRef, useState } from 'react'
import { agentCacheEpoch, agentDataKey } from './agent-data-cache'
import { usePagedAgentData } from './usePagedAgentData'
import { useAgentData } from './useAgentData'
import { useCurrentNodeId } from '../cluster/node-url'
import type { MemoryCatalog, MemoryFacets, MemoryRecord } from './memory-record'
import type { MemoryRoute } from './memory-browser-route'

export function useMemoryCatalog(route: MemoryRoute, cid: string, defaultConversation = false) {
  useCurrentNodeId()
  const category = route.view === 'activity' ? 'activity' : 'knowledge', state = route.view === 'review' ? 'review' : 'active'
  const params = new URLSearchParams({ query: route.query, state, category, limit: '20', compact: 'true', offset: String(route.page * 20) })
  if (route.view !== 'activity') {
    params.set('scope', route.scope)
    if (route.kind !== 'all') params.set('kind', route.kind)
    const entity = route.entity || (defaultConversation && route.scope === 'conversation' ? cid : '')
    if (entity && ['project', 'conversation', 'task'].includes(route.scope)) params.set(route.scope + 'Id', entity)
  } else {
    if (route.entity) params.set('projectId', route.entity)
    if (route.date) params.set('dayKey', route.date)
  }
  const desired = '/agent/memories/catalog?' + params, [path, setPath] = useState(desired)
  useEffect(() => { const timer = setTimeout(() => setPath(desired), 150); return () => clearTimeout(timer) }, [desired])
  const result = usePagedAgentData<MemoryRecord>(path)
  const value = useMemo(() => result.value ? { ...(result.value as unknown as MemoryCatalog), items: result.items } : undefined, [result.value, result.items])
  const facets = useAgentData<MemoryFacets>('/agent/memories/facets?state=' + state + '&category=' + category, 15_000)
  const scope = agentDataKey('/agent/memories') + ':' + agentCacheEpoch()
  const previous = useRef<{ scope: string; value?: MemoryCatalog }>({ scope })
  if (previous.current.scope !== scope) previous.current = { scope }
  useEffect(() => { if (value) previous.current = { scope, value } }, [scope, value])
  return { ...result, value: value || previous.current.value, loading: path !== desired || result.loading, facets, scope }
}
