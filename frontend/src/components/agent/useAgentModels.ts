import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { MODEL_SETTINGS_CHANGED, saveAgentModels, type AgentModelSettings } from './agent-models'

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
    try { const saved = await saveAgentModels({ [role]: change }); if (epoch.current !== requestedEpoch) return false; setSettings(saved); return true }
    catch (e) { if (epoch.current === requestedEpoch) setError(e); return false } finally { if (epoch.current === requestedEpoch) { savingRef.current = false; setBusy(false) } }
  }
  const apply = (model: string, effort: string) => model.trim() ? configure({ model: model.trim(), reasoningEffort: effort === 'default' ? null : effort }) : Promise.resolve(false)
  return { role, settings, models, efforts, loading, busy, error, load, apply, clearError: () => setError(null) }
}
