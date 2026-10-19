import { useSettingsDraft } from './settings-draft'
import { useEffect, useRef, useState } from 'react'
import { App, Button, Input, Select, Spin, Switch } from 'antd'
import { api } from '../../api'
import { useCurrentNodeId } from '../cluster/node-url'
import { RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { modelFailure, saveAgentModels, type AgentModelSettings } from '../agent/agent-models'
import { genericReasoningEfforts, reasoningValue } from '../agent/agent-reasoning'
import './agent-settings.css'

type Draft = { connection: { baseUrl: string; apiKey: string; keyConfigured: boolean }; main: AgentModelSettings['main']; worker: AgentModelSettings['worker'] }
const settingsDraft = (data: AgentModelSettings): Draft => ({ connection: { ...(data.connection || data.main), apiKey: '' }, main: { ...data.main }, worker: { ...data.worker } })
const modelConfiguration = (draft: Draft) => ({ connection: { baseUrl: draft.connection.baseUrl.trim(), ...(draft.connection.apiKey.trim() ? { apiKey: draft.connection.apiKey.trim() } : {}) }, ...Object.fromEntries((['main', 'worker'] as const).map(role => [role, { model: draft[role].model.trim(), images: draft[role].images, contextWindow: draft[role].configuredContextWindow ?? null, reasoningEffort: draft[role].reasoningEffort ?? null }])) })

export function AgentSettings() {
  const node = useCurrentNodeId()
  return <AgentSettingsForm key={node || 'local'} />
}
function AgentSettingsForm() {
  const { t } = useI18n(), { message } = App.useApp()
  const [draft, setDraft] = useState<Draft | null>(null), [saved, setSaved] = useState<AgentModelSettings | null>(null)
  const [error, setError] = useState(''), [saving, setSaving] = useState(false), [version, setVersion] = useState(0)
  const [efforts, setEfforts] = useState<Record<string, string[]>>({}), [models, setModels] = useState<string[] | null>(null)
  const [loadingModels, setLoadingModels] = useState(false), [catalogError, setCatalogError] = useState(''), [queries, setQueries] = useState({ main: '', worker: '' })
  const catalogRequest = useRef<AbortController | null>(null)
  const hydrate = (data: AgentModelSettings) => {
    setSaved(data); setDraft(settingsDraft(data)); setQueries({ main: '', worker: '' })
    setEfforts(current => ({ ...current, [data.main.model]: data.main.reasoningEfforts || genericReasoningEfforts, [data.worker.model]: data.worker.reasoningEfforts || genericReasoningEfforts }))
  }
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/model-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) hydrate(data) }).catch(e => { if (!abort.signal.aborted) setError(modelFailure(e, t)) })
    return () => abort.abort()
  }, [version])
  useEffect(() => () => catalogRequest.current?.abort(), [])
  const invalidateCatalog = () => { catalogRequest.current?.abort(); setModels(null); setEfforts({}); setCatalogError(''); setLoadingModels(false); setQueries({ main: '', worker: '' }) }
  const update = (role: 'main' | 'worker', change: Partial<AgentModelSettings['main']>) => setDraft(current => current ? { ...current, [role]: { ...current[role], ...change } } : current)
  const catalog = async () => {
    if (!draft || loadingModels || saving) return
    const abort = new AbortController(); catalogRequest.current = abort
    setLoadingModels(true); setCatalogError('')
    try {
      const { data } = await api('POST', '/agent/models', { role: 'main', configuration: modelConfiguration(draft) }, { signal: abort.signal })
      if (!abort.signal.aborted) { setModels(data.models); setEfforts(data.reasoningEfforts || {}) }
    } catch (e) { if (!abort.signal.aborted) setCatalogError(modelFailure(e, t)) }
    finally { if (!abort.signal.aborted) setLoadingModels(false) }
  }
  const save = async () => {
    if (!draft || saving || loadingModels) return
    setSaving(true); setError('')
    try { hydrate(await saveAgentModels(modelConfiguration(draft))); message.success(t('agent.models.saved')) }
    catch (e) { setError(modelFailure(e, t)) } finally { setSaving(false) }
  }
  const draftNotice = useSettingsDraft('agent-models', draft, saved ? settingsDraft(saved) : null, setDraft, !!draft && !!saved)
  if (!draft) return error ? <div role="alert"><p>{error}</p><Button onClick={() => setVersion(v => v + 1)}>{t('agent.retry')}</Button></div> : <Spin />
  const dirty = !!saved && JSON.stringify(modelConfiguration(draft)) !== JSON.stringify(modelConfiguration(settingsDraft(saved)))
  return <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); void save() }}>
    {draftNotice}
    <fieldset className="agent-settings-connection" disabled={saving}>
      <legend>{t('agent.models.connection')}</legend><p className="agent-settings-hint">{t('agent.models.connectionHint')}</p>
      <div className="agent-settings-connection-fields">
        <div className="agent-settings-field"><label htmlFor="agent-connection-url">{t('agent.models.baseUrl')}</label><Input id="agent-connection-url" type="url" value={draft.connection.baseUrl} onChange={event => { invalidateCatalog(); setDraft(current => current ? { ...current, connection: { ...current.connection, baseUrl: event.target.value }, main: { ...current.main, contextWindow: null, configuredContextWindow: null, reasoningEffort: null }, worker: { ...current.worker, contextWindow: null, configuredContextWindow: null, reasoningEffort: null } } : current) }} placeholder="https://api.example.com/v1" required maxLength={2000} /></div>
        <div className="agent-settings-field"><label htmlFor="agent-connection-key">{t('agent.models.apiKey')}</label><Input.Password id="agent-connection-key" autoComplete="new-password" visibilityToggle={false} value={draft.connection.apiKey} onChange={event => { invalidateCatalog(); setDraft(current => current ? { ...current, connection: { ...current.connection, apiKey: event.target.value } } : current) }} placeholder={t(draft.connection.keyConfigured ? 'agent.models.keyKept' : 'agent.models.keyPlaceholder')} maxLength={4096} /></div>
      </div>
      <div className="agent-settings-catalog"><Button loading={loadingModels} disabled={saving || !draft.connection.baseUrl.trim()} icon={<RefreshIcon size={16} />} onClick={() => { void catalog() }}>{t('agent.models.test')}</Button><span role="status">{models !== null ? t('agent.models.catalogReady', { count: models.length }) : t('agent.models.catalogHint')}</span></div>
      {catalogError && <p className="agent-settings-error" role="alert">{catalogError}</p>}
      <p className="agent-settings-hint">{t('agent.models.keyPrivacy')}</p>
    </fieldset>
    <div className="agent-settings-roles">{(['main', 'worker'] as const).map(role => {
      const query = queries[role].trim(), names = Array.from(new Set([...(draft[role].model ? [draft[role].model] : []), ...(models || [])]))
      const options = names.filter(name => name.toLowerCase().includes(query.toLowerCase())).map(value => ({ value, label: value, title: value }))
      if (query && !names.includes(query)) options.push({ value: query, label: t('agent.models.use', { name: query }), title: query })
      return <fieldset className="agent-settings-role" key={role} disabled={saving}>
        <legend>{t('agent.models.role.' + role)}</legend><p className="agent-settings-hint">{t('agent.models.roleHint.' + role)}</p>
        <div className="agent-settings-field"><label htmlFor={`agent-${role}-model`}>{t('agent.composer.model')}</label><Select id={`agent-${role}-model`} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.composer.model')} showSearch popupClassName="agent-model-settings-options" virtual={false} disabled={saving} loading={loadingModels} value={draft[role].model || undefined} searchValue={queries[role]} filterOption={false} optionLabelProp="value" options={options} placeholder={t('agent.models.selectPlaceholder')} notFoundContent={t('agent.models.catalogEmpty')} onSearch={value => setQueries(current => ({ ...current, [role]: value.slice(0, 200) }))} onOpenChange={open => { setQueries(current => ({ ...current, [role]: '' })); if (open && models === null) void catalog() }} onChange={value => { update(role, { model: value, contextWindow: null, configuredContextWindow: null, reasoningEffort: null }); setQueries(current => ({ ...current, [role]: '' })) }} /></div>
        <div className="agent-settings-field"><label htmlFor={`agent-${role}-effort`}>{t('agent.reasoning.title')}</label><Select id={`agent-${role}-effort`} disabled={saving} virtual={false} aria-label={t('agent.reasoning.roleLabel', { role: t('agent.models.role.' + role) })} value={reasoningValue(draft[role].reasoningEffort)} options={['default', ...(efforts[draft[role].model] || genericReasoningEfforts)].map(value => ({ value, label: t('agent.reasoning.' + value) }))} onChange={value => update(role, { reasoningEffort: value === 'default' ? null : value })} /></div>
        <details className="agent-model-advanced"><summary>{t('agent.models.advanced')}</summary><div className="agent-model-advanced-fields"><label htmlFor={`agent-${role}-window`}>{t('agent.models.contextWindow')}</label><Input id={`agent-${role}-window`} disabled={saving} type="number" min={1} max={100000000} step={1} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.contextWindow')} value={draft[role].configuredContextWindow ?? ''} onChange={event => update(role, { configuredContextWindow: event.target.value ? Number(event.target.value) : null })} placeholder={t('agent.models.contextAuto')} />
          <p className="agent-settings-hint">{t('agent.models.contextHint')}{draft[role].contextWindow ? ' ' + t('agent.models.contextDetected', { count: draft[role].contextWindow }) : ''}</p>
          <label className="agent-settings-switch"><span>{t('agent.models.images')}</span><Switch disabled={saving} checked={draft[role].images} onChange={value => update(role, { images: value })} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.images')} /></label><p className="agent-settings-hint">{t('agent.models.imagesHint')}</p></div></details>
      </fieldset>
    })}</div>
    <p className="agent-settings-hint">{t('agent.reasoning.hint')}</p>
    {error && <p className="agent-settings-error" role="alert">{error}</p>}
    <div className="agent-settings-save"><span role="status">{t(dirty ? 'agent.models.unsaved' : 'agent.models.savedState')}</span><Button disabled={!dirty || saving || loadingModels} onClick={() => { if (saved) { invalidateCatalog(); hydrate(saved); setError('') } }}>{t('agent.models.discard')}</Button><Button type="primary" htmlType="submit" loading={saving} disabled={!dirty || loadingModels || !draft.main.model.trim() || !draft.worker.model.trim()}>{t('agent.models.save')}</Button><small>{t('agent.models.applyHint')}</small></div>
  </form>
}
