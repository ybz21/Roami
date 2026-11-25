import { usePageEffect } from '../../page-activity'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { MODEL_CATALOG_CHANGED, type ModelCatalog, type ModelDirectoryEntry } from '../capabilities/model-hub-api'
import { configuredGatewayModels, gatewayDirectoryPath, loadGatewayModels, selectableGatewayModels } from '../capabilities/gateway-model-catalog'
import { agentDataKey, invalidateAgentData } from './agent-data-cache'
import { useAgentData } from './useAgentData'
import { MODEL_SETTINGS_CHANGED, saveAgentModels, type AgentModelSettings } from './agent-models'

const gatewayChoice = 'gateway:'

export function useAgentModels(node: string | null, role: 'main' | 'worker' = 'main') {
  const scope = JSON.stringify([node, role])
  const currentNode = useRef(scope)
  const loadedNode = useRef(scope)
  const epoch = useRef(0), loadingRef = useRef(false), savingRef = useRef(false)
  const settingsRevision = useRef(0)
  if (currentNode.current !== scope) { currentNode.current = scope; epoch.current++; loadingRef.current = false; savingRef.current = false }
  const [settings, setSettings] = useState<AgentModelSettings | null>(null)
  const [directory, setDirectory] = useState<{ revision?: string; models: ModelDirectoryEntry[]; refreshFailures?: string[] }>({ models: [] })
  const [directoryFailed, setDirectoryFailed] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [efforts, setEfforts] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false)
  const [error, setError] = useState<any>(null), [version, setVersion] = useState(0)
  const endpoint = settings?.[role]?.baseUrl
  const catalog = useAgentData<ModelCatalog>('/agent/model-gateway/catalog', 30_000)
  const refreshCatalog = catalog.refresh
  usePageEffect(() => { const changed = () => { invalidateAgentData(agentDataKey(gatewayDirectoryPath(catalog.value?.revision))); refreshCatalog() }; window.addEventListener(MODEL_CATALOG_CHANGED, changed); return () => window.removeEventListener(MODEL_CATALOG_CHANGED, changed) }, [refreshCatalog, catalog.value?.revision])
  // An identical model ID at another provider does not identify this gateway's route.
  const throughGateway = !!catalog.value?.baseUrl && endpoint?.replace(/\/$/, '') === catalog.value.baseUrl.replace(/\/$/, '') + '/v1'
  const gatewayModels = catalog.value?.models || []
  const additionalModels = throughGateway ? [] : gatewayModels
  const modelNames = Object.fromEntries((throughGateway ? gatewayModels : additionalModels).map(model => [throughGateway ? model.id : gatewayChoice + model.id, model.name]))
  const refresh = useCallback(() => setVersion(v => v + 1), [])
  usePageEffect(() => { window.addEventListener(MODEL_SETTINGS_CHANGED, refresh); return () => window.removeEventListener(MODEL_SETTINGS_CHANGED, refresh) }, [refresh])
  useEffect(() => {
    const abort = new AbortController()
    const revision = settingsRevision.current
    if (loadedNode.current !== scope) { setSettings(null); setModels([]); setDirectory({ models: [] }); setDirectoryFailed(false); setEfforts({}); setError(null); setLoading(false); setBusy(false); loadedNode.current = scope }
    void api('GET', '/agent/model-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted && revision === settingsRevision.current) setSettings(data) }).catch(e => { if (!abort.signal.aborted && revision === settingsRevision.current) setError(e) })
    return () => abort.abort()
  }, [scope, version])
  const load = async () => {
    if (loadingRef.current) return
    const requestedEpoch = epoch.current
    loadingRef.current = true
    refreshCatalog(); refresh()
    setLoading(true); setError(null)
    try {
      const results = await Promise.allSettled([Array.isArray(catalog.value?.models) ? Promise.resolve({ data: { models: [], reasoningEfforts: {} } }) : api('GET', '/agent/models' + (role === 'worker' ? '?role=worker' : '')), loadGatewayModels(catalog.value?.revision)])
      if (epoch.current !== requestedEpoch) return
      const [provider, gateway] = results
      if (gateway.status === 'fulfilled') { setDirectory({ revision: gateway.value.revision, models: gateway.value.models || [] }); setDirectoryFailed(!!gateway.value.refreshFailures?.length) } else setDirectoryFailed(true)
      if (provider.status === 'fulfilled') { setModels(provider.value.data.models || []); setEfforts(provider.value.data.reasoningEfforts || {}) }
      else if (!gatewayModels.length) throw provider.reason
    }
    catch (e) { if (epoch.current === requestedEpoch) setError(e) } finally { if (epoch.current === requestedEpoch) { loadingRef.current = false; setLoading(false) } }
  }
  const configure = async (change: { model?: string; reasoningEffort?: string | null }) => {
    if (savingRef.current) return false
    const requestedEpoch = epoch.current
    savingRef.current = true
    settingsRevision.current++
    setBusy(true); setError(null)
    const gatewaySelection = change.model?.startsWith(gatewayChoice) && additionalModels.some(model => gatewayChoice + model.id === change.model)
    try {
      let saved: AgentModelSettings
      if (gatewaySelection) {
        await api('POST', '/agent/model-gateway/catalog/roles', { role, model: change.model!.slice(gatewayChoice.length), revision: catalog.value!.revision })
        const { data } = await api('GET', '/agent/model-settings')
        saved = data
        window.dispatchEvent(new Event(MODEL_SETTINGS_CHANGED))
        window.dispatchEvent(new Event(MODEL_CATALOG_CHANGED))
      } else saved = await saveAgentModels({ [role]: change })
      if (epoch.current !== requestedEpoch) return false
      if (saved[role]?.baseUrl !== settings?.[role]?.baseUrl) { setModels([]); setEfforts({}) }
      setSettings(saved); return true
    }
    catch (e) { if (epoch.current === requestedEpoch) { setError(e); if (gatewaySelection) refreshCatalog() } return false } finally { if (epoch.current === requestedEpoch) { savingRef.current = false; setBusy(false) } }
  }
  const apply = (model: string, effort: string) => model.trim() ? configure({ model: model.trim(), reasoningEffort: effort === 'default' ? null : effort }) : Promise.resolve(false)
  const catalogAvailable = Array.isArray(catalog.value?.models)
  const currentModel = settings?.[role]?.model || ''
  const currentRouteId = throughGateway && currentModel === 'roami-default' ? catalog.value?.defaultModel : currentModel
  const currentRoute = gatewayModels.find(model => throughGateway ? model.id === currentRouteId || !!currentRouteId && model.aliases?.includes(currentRouteId) : !model.aggregate && model.candidates?.length === 1 && model.candidates[0].model === currentModel && catalog.value?.sources?.find(source => source.id === model.candidates[0].sourceId)?.baseUrl?.replace(/\/+$/, '') === endpoint?.replace(/\/+$/, ''))
  const selectedOption = currentRoute ? throughGateway ? currentRoute.id : gatewayChoice + currentRoute.id : currentModel
  const choices = catalogAvailable ? selectableGatewayModels(catalog.value).map(model => throughGateway ? model.id : gatewayChoice + model.id) : models
  const modelDetails: Record<string, ModelDirectoryEntry> = {}
  const configured = configuredGatewayModels(catalog.value, directory)
  for (const model of gatewayModels) {
    const detail = configured.find(row => row.id === model.id)
    if (detail) for (const id of throughGateway ? [model.id, ...(model.aliases || [])] : [gatewayChoice + model.id]) modelDetails[id] = detail
  }
  const modelKinds: Record<string, 'native' | 'aggregate'> = Object.fromEntries(catalog.value ? models.map(id => [id, 'native']) : [])
  for (const entry of throughGateway ? gatewayModels : additionalModels) {
    for (const id of throughGateway ? [entry.id, ...(entry.aliases || [])] : [gatewayChoice + entry.id]) modelKinds[id] = entry.aggregate ? 'aggregate' : 'native'
  }
  if (throughGateway && catalog.value?.defaultModel && modelKinds[catalog.value.defaultModel]) modelKinds['roami-default'] = modelKinds[catalog.value.defaultModel]
  return { role, settings, models: choices, modelNames, modelKinds, modelDetails, directoryFailed, retryDirectory: load, catalogAvailable, selectedOption, efforts, loading, busy, error, load, apply, clearError: () => setError(null) }
}
