import { usePageEffect } from '../../page-activity'
import { useAgentData } from '../agent/useAgentData'
import { loadAgentData } from '../agent/agent-data-cache'
import type { ModelCatalog, ModelDirectoryEntry } from './model-hub-api'
import { MODEL_CATALOG_CHANGED } from './model-hub-api'

export type GatewayModel = ModelDirectoryEntry
export type GatewayModelCatalog = { revision?: string; models: GatewayModel[]; refreshFailures?: string[] }

export const gatewayDirectoryPath = (revision?: string) => '/agent/model-gateway/models?all=true&refresh=true' + (revision ? '&revision=' + encodeURIComponent(revision) : '')
export const loadGatewayModels = (revision?: string) => loadAgentData<GatewayModelCatalog>(gatewayDirectoryPath(revision), 30_000)

export function useGatewayModelCatalog(revision: string | undefined, active: boolean) {
  const result = useAgentData<GatewayModelCatalog>(revision ? gatewayDirectoryPath(revision) : null, 30_000, 0, 'GET', active)
  const refresh = result.refresh
  usePageEffect(() => {
    window.addEventListener(MODEL_CATALOG_CHANGED, refresh)
    return () => window.removeEventListener(MODEL_CATALOG_CHANGED, refresh)
  }, [refresh])
  return { ...result, value: result.value?.revision === revision ? result.value : undefined }
}

export const prioritizeGatewayModels = <T extends { kind?: string }>(rows: T[]) => [...rows].sort((a, b) => Number(b.kind === 'aggregate') - Number(a.kind === 'aggregate'))
export const freeGatewayModel = (row: ModelDirectoryEntry) => row.freeOnly || row.pricing === 'confirmed-free'
export function configuredGatewayModels(catalog?: ModelCatalog, directory?: GatewayModelCatalog): ModelDirectoryEntry[] {
  const metadata = directory?.revision === catalog?.revision ? directory?.models || [] : []
  return prioritizeGatewayModels((catalog?.models || []).filter(model => !model.gatewayHidden).map(model => {
    const detail = metadata.find(row => row.configured && row.id === model.id)
    return { ...detail, id: model.id, name: model.name, gatewayAlias: model.gatewayAlias, kind: model.aggregate ? 'aggregate' : 'single', protocol: model.protocol, configured: true, enabled: model.enabled !== false, freeOnly: model.freeOnly === true, pricing: model.freeOnly ? 'free-only' : detail?.pricing || 'unknown', capabilities: detail?.capabilities || {}, candidates: model.candidates || [] }
  }))
}
