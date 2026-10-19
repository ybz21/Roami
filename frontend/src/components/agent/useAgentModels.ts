import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { MODEL_SETTINGS_CHANGED, saveAgentModels, type AgentModelSettings } from './agent-models'

export function useAgentModels(node: string | null) {
  const currentNode = useRef(node)
  const loadedNode = useRef(node)
  currentNode.current = node
  const [settings, setSettings] = useState<AgentModelSettings | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [efforts, setEfforts] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false)
  const [error, setError] = useState<any>(null), [version, setVersion] = useState(0)
  const refresh = useCallback(() => setVersion(v => v + 1), [])
  useEffect(() => { window.addEventListener(MODEL_SETTINGS_CHANGED, refresh); return () => window.removeEventListener(MODEL_SETTINGS_CHANGED, refresh) }, [refresh])
  useEffect(() => {
    const abort = new AbortController()
    if (loadedNode.current !== node) { setSettings(null); setModels([]); setEfforts({}); setError(null); setLoading(false); setBusy(false); loadedNode.current = node }
    void api('GET', '/agent/model-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setSettings(data) }).catch(() => {})
    return () => abort.abort()
  }, [node, version])
  const load = async () => {
    if (loading) return
    const requestedNode = node
    setLoading(true); setError(null)
    try { const { data } = await api('GET', '/agent/models'); if (currentNode.current === requestedNode) { setModels(data.models); setEfforts(data.reasoningEfforts || {}) } }
    catch (e) { if (currentNode.current === requestedNode) setError(e) } finally { if (currentNode.current === requestedNode) setLoading(false) }
  }
  const configure = async (change: { model?: string; reasoningEffort?: string | null }) => {
    if (busy) return false
    const requestedNode = node
    setBusy(true); setError(null)
    try { const saved = await saveAgentModels({ main: change }); if (currentNode.current !== requestedNode) return false; setSettings(saved); return true }
    catch (e) { if (currentNode.current === requestedNode) setError(e); return false } finally { if (currentNode.current === requestedNode) setBusy(false) }
  }
  const apply = (model: string, effort: string) => model.trim() ? configure({ model: model.trim(), reasoningEffort: effort === 'default' ? null : effort }) : Promise.resolve(false)
  return { settings, models, efforts, loading, busy, error, load, apply }
}
