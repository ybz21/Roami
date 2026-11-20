import { useEffect, useState } from 'react'
import { Alert, Checkbox, Select, Spin } from 'antd'
import { api } from '../../api'
import { useCurrentNodeId } from '../cluster/node-url'
import { useI18n } from '../../i18n'
import { freeGatewayModel, prioritizeGatewayModels } from './gateway-model-catalog'
import ModelCapabilities from './ModelCapabilities'
import { MODEL_CATALOG_CHANGED, type ModelDirectoryEntry } from './model-hub-api'
export type { ModelDirectoryEntry } from './model-hub-api'

export type ModelChoice = { model: string; freeOnly: boolean }
export const defaultModelChoice: ModelChoice = { model: 'auto', freeOnly: false }
export function modelChoiceRequest({ model, freeOnly }: ModelChoice) {
  return { ...(model !== 'auto' || freeOnly ? { model } : {}), freeOnly }
}
export const modelCapabilities = ['text', 'image', 'audio', 'video', 'tools', 'reasoning', 'structuredOutput', 'streaming'] as const

export default function ModelSelectionFields({ value, onChange, disabled = false, scope = 'session' }: {
  value: ModelChoice; onChange: (choice: ModelChoice) => void; disabled?: boolean; scope?: 'session' | 'task'
}) {
  const { t } = useI18n(), node = useCurrentNodeId()
  const [models, setModels] = useState<ModelDirectoryEntry[]>([]), [loading, setLoading] = useState(true), [failed, setFailed] = useState(false)
  const [kind, setKind] = useState(''), [capability, setCapability] = useState(''), [version, setVersion] = useState(0)
  useEffect(() => {
    const abort = new AbortController()
    const changed = () => setVersion(current => current + 1)
    window.addEventListener(MODEL_CATALOG_CHANGED, changed)
    setLoading(true); setFailed(false)
    void api('GET', '/agent/model-gateway/models', undefined, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) setModels(data.models || [])
    }).catch(() => { if (!abort.signal.aborted) setFailed(true) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => { abort.abort(); window.removeEventListener(MODEL_CATALOG_CHANGED, changed) }
  }, [node, version])
  const compatible = prioritizeGatewayModels(models.filter(model => model.configured && model.enabled && ['openai-completions', 'openai-responses', 'anthropic-messages'].includes(model.protocol)))
  const visible = compatible.filter(model => (!kind || model.kind === kind) && (!value.freeOnly || freeGatewayModel(model)) && (!capability || model.capabilities[capability]?.support === 'supported'))
  const selected = models.find(model => model.id === value.model)
  const options = [{ value: 'auto', label: t('modelSelection.auto') }, ...visible.map(model => ({ value: model.id, label: model.name + (model.freeOnly ? ' · ' + t('modelSelection.freePool') : '') }))]
  // A filter never silently replaces an already chosen route.
  if (value.model !== 'auto' && !visible.some(model => model.id === value.model)) options.push({ value: value.model, label: selected?.name || value.model })
  let issue = ''
  if (!loading && !failed && value.model !== 'auto') {
    if (!selected?.configured) issue = 'modelSelection.notConfigured'
    else if (!selected.enabled) issue = 'modelSelection.disabled'
    else if (value.freeOnly && !freeGatewayModel(selected)) issue = 'modelSelection.freeUnconfirmed'
  }
  return <div className="agent-settings-form">
    {failed && <Alert type="error" message={t('modelSelection.failed')} action={<button type="button" className="tt-act" onClick={() => setVersion(current => current + 1)}>{t('agent.retry')}</button>} />}
    <label className="agent-settings-field">{t('modelSelection.kind')}<Select aria-label={t('modelSelection.kind')} value={kind} disabled={disabled} onChange={setKind} options={['', 'single', 'aggregate'].map(value => ({ value, label: t('modelSelection.kind.' + (value || 'all')) }))} /></label>
    <label className="agent-settings-field">{t('modelSelection.capability')}<Select aria-label={t('modelSelection.capability')} value={capability} disabled={disabled} onChange={setCapability} options={[{ value: '', label: t('modelSelection.allCapabilities') }, ...modelCapabilities.map(name => ({ value: name, label: t('modelSelection.capability.' + name) }))]} /></label>
    <label className="agent-settings-field">{t('agent.composer.model')}<Select virtual={false} showSearch
      filterOption={(query, option) => [option?.value, option?.label].some(text => text?.toLowerCase().includes(query.toLowerCase()))}
      aria-label={t('agent.composer.model')} value={value.model} loading={loading} disabled={disabled || loading || failed}
      options={options} onChange={model => onChange({ ...value, model })} /></label>
    {selected && <ModelCapabilities model={selected} />}
    {issue && <Alert type="warning" message={t(issue)} />}
    <Checkbox checked={value.freeOnly} disabled={disabled} onChange={event => onChange({ ...value, freeOnly: event.target.checked })}>{t('modelSelection.freeOnly')}</Checkbox>
    {loading ? <Spin size="small" /> : <p className="agent-settings-hint">{t(value.freeOnly ? 'modelSelection.freeHint' : scope === 'task' ? 'modelSelection.taskScope' : 'modelSelection.scope')}</p>}
    {capability && <p className="agent-settings-hint">{t('modelSelection.advertisedHint')}</p>}
  </div>
}
