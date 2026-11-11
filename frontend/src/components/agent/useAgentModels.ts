import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { MODEL_CATALOG_CHANGED, type ModelCatalog } from '../capabilities/model-hub-api'
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
  const [models, setModels] = useState<string[]>([])
  const [efforts, setEfforts] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false)
  const [error, setError] = useState<any>(null), [version, setVersion] = useState(0)
  const endpoint = settings?.[role]?.baseUrl
  const catalog = useAgentData<ModelCatalog>('/agent/model-gateway/catalog', 30_000)
  const refreshCatalog = catalog.refresh
  useEffect(() => { window.addEventListener(MODEL_CATALOG_CHANGED, refreshCatalog); return () => window.removeEventListener(MODEL_CATALOG_CHANGED, refreshCatalog) }, [refreshCatalog])
  // An identical model ID at another provider does not identify this gateway's route.
  const throughGateway = !!catalog.value?.baseUrl && endpoint?.replace(/\/$/, '') === catalog.value.baseUrl.replace(/\/$/, '') + '/v1'
  const gatewayModels = catalog.value?.models || []
  const additionalModels = throughGateway ? [] : gatewayModels.filter(model => {
    if (model.strategy !== 'fixed' || model.candidates?.length !== 1) return true
    const candidate = model.candidates[0]
    const source = catalog.value?.sources?.find(source => source.id === candidate.sourceId)
    return !models.includes(candidate.model) || source?.baseUrl.replace(/\/$/, '') !== endpoint?.replace(/\/$/, '')
  })
  const modelNames = Object.fromEntries((throughGateway ? gatewayModels : additionalModels).map(model => [throughGateway ? model.id : gatewayChoice + model.id, model.name]))
  const refresh = useCallback(() => setVersion(v => v + 1), [])
  useEffect(() => { window.addEventListener(MODEL_SETTINGS_CHANGED, refresh); return () => window.removeEventListener(MODEL_SETTINGS_CHANGED, refresh) }, [refresh])
  useEffect(() => {
    const abort = new AbortController()
    const revision = settingsRevision.current
    if (loadedNode.current !== scope) { setSettings(null); setModels([]); setEfforts({}); setError(null); setLoading(false); setBusy(false); loadedNode.current = scope }
    void api('GET', '/agent/model-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted && revision === settingsRevision.current) setSettings(data) }).catch(e => { if (!abort.signal.aborted && revision === settingsRevision.current) setError(e) })
    return () => abort.abort()
  }, [scope, version])
  const load = async () => {
    if (loadingRef.current) return
    const requestedEpoch = epoch.current
    loadingRef.current = true
    setLoading(true); setError(null)
    if (!settings) refresh()
    try { const { data } = await api('GET', '/agent/models' + (role === 'worker' ? '?role=worker' : '')); if (epoch.current === requestedEpoch) { setModels(data.models); setEfforts(data.reasoningEfforts || {}) } }
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
  const choices = throughGateway && gatewayModels.length ? gatewayModels.map(model => model.id) : [...models, ...additionalModels.map(model => gatewayChoice + model.id)]
  return { role, settings, models: choices, modelNames, efforts, loading, busy, error, load, apply, clearError: () => setError(null) }
}
