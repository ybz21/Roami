import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { usePageEffect } from '../../page-activity'
import { MODEL_CATALOG_CHANGED } from '../capabilities/model-hub-api'
import type { ModelChoice, ModelDirectoryEntry } from '../capabilities/ModelSelectionFields'
import { MODEL_SETTINGS_CHANGED, type AgentModelSettings } from './agent-models'
import { useAgentData } from './useAgentData'

export function useConversationModels(node: string | null, cid: string, role: 'main' | 'worker' = 'main') {
  const { t } = useI18n()
  const scope = JSON.stringify([node, cid, role]), current = useRef(scope)
  current.current = scope
  const settings = useAgentData<AgentModelSettings>('/agent/model-settings', 0)
  const directory = useAgentData<{ models: ModelDirectoryEntry[] }>('/agent/model-gateway/models', 0)
  const selection = useAgentData<ModelChoice>(cid ? '/agent/conversations/' + encodeURIComponent(cid) + '/model' : null, 0)
  const [saved, setSaved] = useState<{ scope: string; value: ModelChoice } | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState<any>(null)
  const saving = useRef(false)
  useEffect(() => { setBusy(false); setError(null); saving.current = false }, [scope])
  usePageEffect(() => {
    const changed = () => { directory.refresh(); settings.refresh() }
    window.addEventListener(MODEL_CATALOG_CHANGED, changed); window.addEventListener(MODEL_SETTINGS_CHANGED, changed)
    return () => { window.removeEventListener(MODEL_CATALOG_CHANGED, changed); window.removeEventListener(MODEL_SETTINGS_CHANGED, changed) }
  }, [directory.refresh, settings.refresh])
  const ready = !!selection.value && typeof selection.value.model === 'string' && typeof selection.value.freeOnly === 'boolean'
  const choice = saved?.scope === scope ? saved.value : selection.value || { model: 'auto', freeOnly: false }
  useEffect(() => { if (selection.value) setSaved(previous => previous?.scope === scope ? null : previous) }, [selection.value, scope])
  const available = (directory.value?.models || []).filter(model => model.configured && model.enabled && ['openai-completions', 'openai-responses', 'anthropic-messages'].includes(model.protocol))
  const base = settings.value?.[role]
  const resolved = ready && settings.value && base ? { ...settings.value, [role]: { ...base, model: choice.model, reasoningSupport: 'unsupported' as const, reasoningEffort: undefined } } : null
  const save = useCallback(async (value: ModelChoice) => {
    if (saving.current || !cid || !ready) return false
    const requested = scope
    saving.current = true; setBusy(true); setError(null)
    try {
      const { data } = await api('PUT', '/agent/conversations/' + encodeURIComponent(cid) + '/model', value)
      if (current.current !== requested) return false
      setSaved({ scope: requested, value: data }); selection.refresh()
      return true
    } catch (cause) { if (current.current === requested) setError(cause); return false }
    finally { if (current.current === requested) { saving.current = false; setBusy(false) } }
  }, [scope, cid, ready, selection.refresh])
  return {
    role, settings: resolved, models: ['auto', ...available.map(model => model.id)],
    modelNames: Object.fromEntries([['auto', t('modelSelection.auto')], ...available.map(model => [model.id, model.name])]), efforts: {},
    loading: settings.loading || directory.loading || selection.loading, busy, error: error || (directory.failed || selection.failed || settings.failed ? new Error('MODEL_GATEWAY_UNAVAILABLE') : null),
    load: async () => { directory.refresh(); settings.refresh(); if (cid) selection.refresh() },
    apply: (model: string, _effort: string) => save({ ...choice, model }), clearError: () => setError(null),
    choice, setFreeOnly: (freeOnly: boolean) => save({ ...choice, freeOnly }), directory: available,
  }
}
