import { usePageEffect } from '../../page-activity'
import { useAgentData } from '../agent/useAgentData'
import { MODEL_CATALOG_CHANGED } from './model-hub-api'

export type CapabilityFact = { support: 'supported' | 'unsupported' | 'unknown'; evidence: string; delivery: string }
export type GatewayModel = {
  id: string; name: string; kind: 'single' | 'aggregate'; configured: boolean; enabled: boolean; freeOnly: boolean
  protocol: string; pricing: string; contextWindow?: number; maxOutputTokens?: number
  inputModalities?: string[]; outputModalities?: string[]; inputPrice?: number; outputPrice?: number
  capabilities: Record<string, CapabilityFact>; candidates: { sourceId: string; model: string }[]
}
export type GatewayModelCatalog = { revision: string; models: GatewayModel[]; refreshFailures: string[] }

export function useGatewayModelCatalog(revision: string | undefined, active: boolean) {
  const result = useAgentData<GatewayModelCatalog>(revision ? '/agent/model-gateway/models?all=true&refresh=true&revision=' + encodeURIComponent(revision) : null, 5 * 60_000, 0, 'GET', active)
  const refresh = result.refresh
  usePageEffect(() => {
    window.addEventListener(MODEL_CATALOG_CHANGED, refresh)
    return () => window.removeEventListener(MODEL_CATALOG_CHANGED, refresh)
  }, [refresh])
  return { ...result, value: result.value?.revision === revision ? result.value : undefined }
}
