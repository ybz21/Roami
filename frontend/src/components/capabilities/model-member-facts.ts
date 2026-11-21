import { useEffect, useState } from 'react'
import { api } from '../../api'
import { usePageActive } from '../../page-activity'
import type { CatalogModel, ModelCatalog } from './model-hub-api'
import { useRoutingStatus, type RoutingBlock } from './model-routing-api'
import { useModelMonitor } from './model-monitor-api'
import { configuredSourceModelIds } from './configured-source-models'
import type { SourceModelDetail } from './source-model-directory'
export type MemberFact = { configured?: boolean; ready?: boolean; block?: RoutingBlock; context?: number; sourceLatencyMs?: number }
export function useModelMemberFacts(model: CatalogModel, saved: CatalogModel | undefined, catalog: ModelCatalog, active: boolean) {
  const pageActive = usePageActive()
  active = active && pageActive
  const status = useRoutingStatus(saved?.id || '', active && !!saved && saved.enabled !== false, catalog.revision)
  const monitor = useModelMonitor(active, 24, '', '', 0)
  const [directory, setDirectory] = useState<{ key: string; models: Record<string, SourceModelDetail[]> } | null>(null)
  const serverChecksSavedMembers = !!saved && saved.enabled !== false && (!status.data || !!status.data.members)
  const pluginSourceIds = new Set(catalog.sources.filter(row => row.pluginSourceId).map(row => row.id))
  const ids = [...new Set(model.candidates.filter(row => row.sourceId !== '@group' &&
    (pluginSourceIds.has(row.sourceId) || !serverChecksSavedMembers || !saved?.candidates.some(member => member.sourceId === row.sourceId && member.model === row.model)),
  ).map(row => row.sourceId))].sort()
  const sourceKey = JSON.stringify(ids), key = catalog.revision + ':' + sourceKey
  useEffect(() => {
    if (!active || !ids.length || directory?.key === key) return
    const abort = new AbortController(), queue = [...ids], models: Record<string, SourceModelDetail[]> = {}
    const worker = async () => {
      while (queue.length && !abort.signal.aborted) {
        const id = queue.shift()!, source = catalog.sources.find(row => row.id === id)
        if (!source) continue
        try {
          const { data } = await api('POST', '/agent/model-gateway/catalog/discover', { source, revision: catalog.revision }, { signal: abort.signal })
          models[id] = data.details || []
        } catch { models[id] = [] }
      }
    }
    void Promise.all(Array.from({ length: Math.min(3, ids.length) }, worker)).then(() => { if (!abort.signal.aborted) setDirectory({ key, models }) })
    return () => abort.abort()
  }, [active, key, directory?.key])
  const facts: Record<string, MemberFact> = {}
  for (const candidate of model.candidates) {
    const channels = status.data?.channels?.filter(row => row.sourceId === candidate.sourceId && row.model === candidate.model)
    const member = status.data?.members?.find(row => row.sourceId === candidate.sourceId && row.model === candidate.model)
    const latency = monitor.data?.sources?.find(row => row.sourceId === candidate.sourceId)?.totals.firstTokenP95
    facts[candidate.sourceId + '/' + candidate.model] = {
      configured: candidate.sourceId === '@group' ? undefined : configuredSourceModelIds(catalog.models, candidate.sourceId).includes(candidate.model),
      ready: channels?.length ? channels.some(row => row.ready) : undefined,
      ...(member?.block ? { block: member.block } : {}),
      context: member?.context ?? (directory?.key === key ? directory.models[candidate.sourceId]?.find(row => row.id === candidate.model)?.context : undefined),
      sourceLatencyMs: typeof latency === 'number' && latency >= 0 ? latency : undefined,
    }
  }
  return { facts, status }
}
