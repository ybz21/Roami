import { useEffect, useRef, useState } from 'react'
import type { RoutingStrategy } from './model-routing-api'
import { api } from '../../api'

export type ModelSource = { connector?: 'openrouter-free'; pluginDesktop?: boolean; pluginDesktopUnavailable?: boolean; pluginSourceId?: string; accountRoutingAvailable?: boolean; id: string; name: string; sourceKey?: string; baseUrl: string; protocol: string; authMode: string; skipTlsVerification?: boolean; hasKey?: boolean; apiKey?: string; headerNames?: string[]; headers?: Record<string, string> }
export type ModelCandidate = { sourceId: string; model: string }
export type CatalogModel = { id: string; aliases?: string[]; gatewayAlias?: string; gatewayHidden?: boolean; hideMembers?: boolean; name: string; protocol: string; strategy: 'fixed' | 'failover' | RoutingStrategy; aggregate?: boolean; enabled?: boolean; freeOnly?: boolean; allowPlan?: boolean; requireTools?: boolean; minContext?: number; cooldownSeconds?: number; onLimit?: boolean; onExhausted?: boolean; weights?: Record<string, number>; candidates: ModelCandidate[] }
export type ModelCatalog = { revision: string; sources: ModelSource[]; models: CatalogModel[]; drafts: CatalogModel[]; baseUrl: string; uses: Record<string, string[]>; canRestoreRoami?: boolean; roamiModels?: Record<string, string>; defaultModel?: string; qualifiedModelIds?: Record<string, string> }
export type ModelDirectoryEntry = { id: string; name: string; kind: string; protocol: string; gatewayAlias?: string; gatewayHidden?: boolean; configured: boolean; enabled: boolean; freeOnly: boolean; pricing?: string; capabilities: Record<string, { support: string; evidence: string; delivery: string }>; candidates?: ModelCandidate[]; contextWindow?: number; maxOutputTokens?: number; inputPrice?: number; outputPrice?: number; inputModalities?: string[]; outputModalities?: string[] }
const normalizeCatalog = (data: ModelCatalog): ModelCatalog => ({ ...data, sources: data.sources || [], models: data.models || [], drafts: data.drafts || [], uses: data.uses || {} })
export const MODEL_CATALOG_CHANGED = 'roami:model-catalog-changed'
export const modelProtocols = ['openai-completions', 'openai-responses', 'anthropic-messages']
export const openRouterConnection = { connector: 'openrouter-free', baseUrl: 'https://openrouter.ai/api/v1', protocol: 'openai-completions', authMode: 'bearer' } as const
export const sourceModelName = (source: Pick<ModelSource, 'sourceKey' | 'id'>, model: string) => (source.sourceKey?.trim() || source.id) + '/' + model
export const gatewayModelName = (model: Pick<CatalogModel, 'id' | 'gatewayAlias'>, catalog?: ModelCatalog | null) => model.gatewayAlias || catalog?.qualifiedModelIds?.[model.id] || model.id
export function gatewayModelNameTaken(name: string, current: string | null, models: CatalogModel[]) {
  return models.some(row => row.id !== current && (row.id === name || row.gatewayAlias === name || row.aliases?.includes(name)))
}
export function gatewayAliasError(model: CatalogModel, current: string | null, models: CatalogModel[]) {
  const alias = model.gatewayAlias?.trim()
  if (!alias) return ''
  if (alias === 'roami-default' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/.test(alias)) return 'hub.gatewayAliasInvalid'
  return alias === model.id || alias === current || model.aliases?.includes(alias) || gatewayModelNameTaken(alias, current, models) ? 'hub.gatewayAliasTaken' : ''
}
export function catalogFailure(cause: any): string {
  const code = cause?.apiError?.code || cause?.message
  if (code === 'INVALID_MODEL_SOURCE_HEADERS') return 'hub.headers.invalid'
  if (code === 'MODEL_HEADERS_REQUIRED_FOR_ENDPOINT') return 'hub.headers.newEndpoint'
  if (code === 'MODEL_SOURCE_KEY_REQUIRED') return 'hub.sourceKey.required'
  if (code === 'INVALID_MODEL_GATEWAY_ALIAS') return 'hub.gatewayAliasTaken'
  if (code === 'INVALID_MODEL_SOURCE_KEY') return 'hub.sourceKey.invalid'
  if (code === 'MODEL_SOURCE_KEY_IN_USE') return 'hub.sourceKey.inUse'
  return code === 'MODEL_GATEWAY_KEY_DISABLED' ? 'hub.error.connectionDisabled' : code === 'MODEL_CONFIGURATION_BUSY' ? 'agent.models.busy' : code === 'MODEL_CATALOG_CHANGED' || code === 'AGENT_CONFIG_CHANGED' ? 'hub.error.changed' : code === 'MODEL_ROUTE_CYCLE' ? 'pool.cycle' : code === 'MODEL_CATALOG_IN_USE' ? 'hub.error.inUse' : code === 'INVALID_MODEL_CATALOG' || code === 'INVALID_MODEL_PROTOCOL' ? 'hub.error.invalid' : code === 'MODEL_KEY_REQUIRED_FOR_ENDPOINT' ? 'agent.models.newEndpointKey' : 'hub.error.failed'
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
  const accept = (data:ModelCatalog) => { if(live.current){setValue(normalizeCatalog(data));window.dispatchEvent(new Event(MODEL_CATALOG_CHANGED))} }
  const save = async (next: ModelCatalog) => {
    if (busy) return false
    setBusy(true); setError('')
    try {
      const { data } = await api('PUT', '/agent/model-gateway/catalog', { revision: next.revision, sources: next.sources, models: next.models, drafts: next.drafts })
      accept(data)
      return true
    } catch (cause) { if (live.current) setError(catalogFailure(cause)); return false }
    finally { if (live.current) setBusy(false) }
  }
  return { value, error, busy, save, accept, retry: () => setVersion(value => value + 1) }
}
