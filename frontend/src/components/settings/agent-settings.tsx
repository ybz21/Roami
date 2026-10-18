import { useEffect, useState } from 'react'
import { App, AutoComplete, Button, Input, Spin, Switch } from 'antd'
import { api } from '../../api'
import { useCurrentNodeId } from '../cluster/node-url'
import { RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { modelFailure, saveAgentModels, type AgentModelSettings } from '../agent/agent-models'
import './agent-settings.css'

type RoleDraft = { baseUrl: string; model: string; images: boolean; apiKey: string; keyConfigured: boolean; contextWindow?: number | null; configuredContextWindow?: number | null }
type Draft = { main: RoleDraft; worker: RoleDraft }
export function AgentSettings() {
  const node = useCurrentNodeId()
  return <AgentSettingsForm key={node || 'local'} />
}
function AgentSettingsForm() {
  const { t } = useI18n(), { message } = App.useApp()
  const [draft, setDraft] = useState<Draft | null>(null), [error, setError] = useState(''), [saving, setSaving] = useState(false)
  const [loadingRole, setLoadingRole] = useState(''), [catalogs, setCatalogs] = useState<Record<string, string[]>>({}), [version, setVersion] = useState(0)
  const hydrate = (data: AgentModelSettings) => setDraft({ main: { ...data.main, apiKey: '' }, worker: { ...data.worker, apiKey: '' } })
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/model-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) hydrate(data) }).catch(e => { if (!abort.signal.aborted) setError(modelFailure(e, t)) })
    return () => abort.abort()
  }, [version, t])
  const update = (role: 'main' | 'worker', change: Partial<RoleDraft>) => setDraft(current => current ? { ...current, [role]: { ...current[role], ...change } } : current)
  const configuration = () => Object.fromEntries((['main', 'worker'] as const).map(role => [role, { baseUrl: draft![role].baseUrl.trim(), model: draft![role].model.trim(), images: draft![role].images, contextWindow: draft![role].configuredContextWindow ?? null, ...(draft![role].apiKey.trim() ? { apiKey: draft![role].apiKey.trim() } : {}) }]))
  const catalog = async (role: 'main' | 'worker') => {
    if (!draft || loadingRole) return
    setLoadingRole(role); setError('')
    try { const { data } = await api('POST', '/agent/models', { role, configuration: { [role]: configuration()[role] } }); setCatalogs(current => ({ ...current, [role]: data.models })); message.success(t('agent.models.connected', { count: data.models.length })) }
    catch (e) { setError(modelFailure(e, t)) } finally { setLoadingRole('') }
  }
  const save = async () => {
    if (!draft || saving) return
    setSaving(true); setError('')
    try { hydrate(await saveAgentModels(configuration())); message.success(t('agent.models.saved')) }
    catch (e) { setError(modelFailure(e, t)) } finally { setSaving(false) }
  }
  if (!draft) return error ? <div role="alert"><p>{error}</p><Button onClick={() => setVersion(v => v + 1)}>{t('agent.retry')}</Button></div> : <Spin />
  return <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); void save() }}>
    {(['main', 'worker'] as const).map(role => <fieldset key={role} disabled={saving}>
      <legend>{t('agent.models.role.' + role)}</legend><p className="agent-settings-hint">{t('agent.models.roleHint.' + role)}</p>
      <label htmlFor={`agent-${role}-url`}>{t('agent.models.baseUrl')}</label><Input id={`agent-${role}-url`} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.baseUrl')} type="url" value={draft[role].baseUrl} onChange={event => update(role, { baseUrl: event.target.value })} placeholder="https://api.example.com/v1" required maxLength={2000} />
      <label htmlFor={`agent-${role}-key`}>{t('agent.models.apiKey')}</label><Input.Password id={`agent-${role}-key`} autoComplete="new-password" visibilityToggle={false} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.apiKey')} value={draft[role].apiKey} onChange={event => update(role, { apiKey: event.target.value })} placeholder={t(draft[role].keyConfigured ? 'agent.models.keyKept' : 'agent.models.keyPlaceholder')} maxLength={4096} />
      <p className="agent-settings-hint">{t('agent.models.keyPrivacy')}</p>
      <label htmlFor={`agent-${role}-model`}>{t('agent.composer.model')}</label><div className="agent-settings-model"><AutoComplete id={`agent-${role}-model`} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.composer.model')} value={draft[role].model} onChange={value => update(role, { model: value, contextWindow: null, configuredContextWindow: null })} options={(catalogs[role] || []).map(value => ({ value }))} filterOption={(value, option) => !!option?.value.toLowerCase().includes(value.toLowerCase())}><Input required maxLength={200} placeholder={t('agent.models.modelPlaceholder')} /></AutoComplete><Button loading={loadingRole === role} disabled={!!loadingRole && loadingRole !== role} icon={<RefreshIcon size={16} />} onClick={() => { void catalog(role) }}>{t('agent.models.test')}</Button></div>
      <label htmlFor={`agent-${role}-window`}>{t('agent.models.contextWindow')}</label><Input id={`agent-${role}-window`} type="number" min={1} max={100000000} step={1} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.contextWindow')} value={draft[role].configuredContextWindow ?? ''} onChange={event => update(role, { configuredContextWindow: event.target.value ? Number(event.target.value) : null })} placeholder={t('agent.models.contextAuto')} />
      <p className="agent-settings-hint">{t('agent.models.contextHint')}{draft[role].contextWindow ? ' ' + t('agent.models.contextDetected', { count: draft[role].contextWindow }) : ''}</p>
      <label className="agent-settings-switch"><span>{t('agent.models.images')}</span><Switch checked={draft[role].images} onChange={value => update(role, { images: value })} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.images')} /></label>
      <p className="agent-settings-hint">{t('agent.models.imagesHint')}</p>
    </fieldset>)}
    {error && <p className="agent-settings-error" role="alert">{error}</p>}
    <div className="agent-settings-save"><Button type="primary" htmlType="submit" loading={saving}>{t('agent.models.save')}</Button><span>{t('agent.models.applyHint')}</span></div>
  </form>
}
