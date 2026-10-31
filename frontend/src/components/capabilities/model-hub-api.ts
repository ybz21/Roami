import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'

export type ModelSource = { id: string; name: string; baseUrl: string; protocol: string; authMode: string; hasKey?: boolean; apiKey?: string }
export type ModelCandidate = { sourceId: string; model: string }
export type CatalogModel = { id: string; name: string; protocol: string; strategy: 'fixed' | 'failover'; candidates: ModelCandidate[] }
export type ModelCatalog = { revision: string; sources: ModelSource[]; models: CatalogModel[]; drafts: CatalogModel[]; baseUrl: string; uses: Record<string, string[]>; canRestoreRoami?: boolean; roamiModels?: Record<string, string> }
const normalizeCatalog = (data: ModelCatalog): ModelCatalog => ({ ...data, sources: data.sources || [], models: data.models || [], drafts: data.drafts || [], uses: data.uses || {} })
export const MODEL_CATALOG_CHANGED = 'roami:model-catalog-changed'
export const modelProtocols = ['openai-completions', 'openai-responses', 'anthropic-messages']
export function catalogFailure(cause: any): string {
  const code = cause?.apiError?.code || cause?.message
  return code === 'MODEL_CONFIGURATION_BUSY' ? 'agent.models.busy' : code === 'MODEL_CATALOG_CHANGED' || code === 'AGENT_CONFIG_CHANGED' ? 'hub.error.changed' : code === 'MODEL_CATALOG_IN_USE' ? 'hub.error.inUse' : code === 'INVALID_MODEL_CATALOG' || code === 'INVALID_MODEL_PROTOCOL' ? 'hub.error.invalid' : code === 'MODEL_KEY_REQUIRED_FOR_ENDPOINT' ? 'agent.models.newEndpointKey' : 'hub.error.failed'
}
export function useModelCatalog() {
  const [value, setValue] = useState<ModelCatalog | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [version, setVersion] = useState(0)
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/model-gateway/catalog', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setValue(normalizeCatalog(data)) }).catch(cause => { if (!abort.signal.aborted) setError(catalogFailure(cause)) })
    return () => abort.abort()
  }, [version])
  const save = async (next: ModelCatalog) => {
    if (busy) return false
    setBusy(true); setError('')
    try {
      const { data } = await api('PUT', '/agent/model-gateway/catalog', { revision: next.revision, sources: next.sources, models: next.models, drafts: next.drafts })
      if (live.current) { setValue(normalizeCatalog(data)); window.dispatchEvent(new Event(MODEL_CATALOG_CHANGED)) }
      return true
    } catch (cause) { if (live.current) setError(catalogFailure(cause)); return false }
    finally { if (live.current) setBusy(false) }
  }
  return { value, error, busy, save, retry: () => setVersion(value => value + 1) }
}
