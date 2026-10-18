import { useEffect, useState } from 'react'
import { App, AutoComplete, Button, Input, Spin, Switch } from 'antd'
import { api } from '../../api'
import { useCurrentNodeId } from '../cluster/node-url'
import { RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { modelFailure, saveAgentModels, type AgentModelSettings } from '../agent/agent-models'
import './agent-settings.css'

type RoleDraft = { baseUrl: string; model: string; images: boolean; apiKey: string; keyConfigured: boolean; contextWindow?: number | null; configuredContextWindow?: number | null }
type Draft = { connection: { baseUrl: string; apiKey: string; keyConfigured: boolean }; main: RoleDraft; worker: RoleDraft }
export function AgentSettings() {
  const node = useCurrentNodeId()
  return <AgentSettingsForm key={node || 'local'} />
}
function AgentSettingsForm() {
  const { t } = useI18n(), { message } = App.useApp()
  const [draft, setDraft] = useState<Draft | null>(null), [error, setError] = useState(''), [saving, setSaving] = useState(false)
  const [loadingRole, setLoadingRole] = useState(''), [catalogs, setCatalogs] = useState<Record<string, string[]>>({}), [version, setVersion] = useState(0)
  const hydrate = (data: AgentModelSettings) => setDraft({ connection: { ...(data.connection || data.main), apiKey: '' }, main: { ...data.main, apiKey: '' }, worker: { ...data.worker, apiKey: '' } })
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/model-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) hydrate(data) }).catch(e => { if (!abort.signal.aborted) setError(modelFailure(e, t)) })
    return () => abort.abort()
  }, [version, t])
  const update = (role: 'main' | 'worker', change: Partial<RoleDraft>) => setDraft(current => current ? { ...current, [role]: { ...current[role], ...change } } : current)
  const configuration = () => ({ connection: { baseUrl: draft!.connection.baseUrl.trim(), ...(draft!.connection.apiKey.trim() ? { apiKey: draft!.connection.apiKey.trim() } : {}) }, ...Object.fromEntries((['main', 'worker'] as const).map(role => [role, { model: draft![role].model.trim(), images: draft![role].images, contextWindow: draft![role].configuredContextWindow ?? null }])) })
  const catalog = async (role: 'main' | 'worker') => {
    if (!draft || loadingRole) return
    setLoadingRole(role); setError('')
    try { const { data } = await api('POST', '/agent/models', { role: 'main', configuration: configuration() }); setCatalogs({ main: data.models, worker: data.models }); message.success(t('agent.models.connected', { count: data.models.length })) }
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
    <fieldset disabled={saving}><legend>{t('agent.models.connection')}</legend><p className="agent-settings-hint">{t('agent.models.connectionHint')}</p>
      <label htmlFor={'agent-connection-url'}>{t('agent.models.baseUrl')}</label><Input id={'agent-connection-url'} aria-label={t('agent.models.baseUrl')} type="url" value={draft.connection.baseUrl} onChange={event => setDraft(current => current ? { ...current, connection: { ...current.connection, baseUrl: event.target.value }, main: { ...current.main, contextWindow: null, configuredContextWindow: null }, worker: { ...current.worker, contextWindow: null, configuredContextWindow: null } } : current)} placeholder="https://api.example.com/v1" required maxLength={2000} />
      <label htmlFor={'agent-connection-key'}>{t('agent.models.apiKey')}</label><Input.Password id={'agent-connection-key'} autoComplete="new-password" visibilityToggle={false} aria-label={t('agent.models.apiKey')} value={draft.connection.apiKey} onChange={event => setDraft(current => current ? { ...current, connection: { ...current.connection, apiKey: event.target.value } } : current)} placeholder={t(draft.connection.keyConfigured ? 'agent.models.keyKept' : 'agent.models.keyPlaceholder')} maxLength={4096} />
      <p className="agent-settings-hint">{t('agent.models.keyPrivacy')}</p>
      <Button loading={!!loadingRole} icon={<RefreshIcon size={16} />} onClick={() => { void catalog('main') }}>{t('agent.models.test')}</Button>
    </fieldset>
    {(['main', 'worker'] as const).map(role => <fieldset key={role} disabled={saving}>
      <legend>{t('agent.models.role.' + role)}</legend><p className="agent-settings-hint">{t('agent.models.roleHint.' + role)}</p>
      <label htmlFor={`agent-${role}-model`}>{t('agent.composer.model')}</label><div className="agent-settings-model"><AutoComplete id={`agent-${role}-model`} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.composer.model')} value={draft[role].model} onChange={value => update(role, { model: value, contextWindow: null, configuredContextWindow: null })} options={(catalogs[role] || []).map(value => ({ value }))} filterOption={(value, option) => !!option?.value.toLowerCase().includes(value.toLowerCase())}><Input required maxLength={200} placeholder={t('agent.models.modelPlaceholder')} /></AutoComplete></div>
      <details className="agent-model-advanced"><summary>{t('agent.models.advanced')}</summary><div className="agent-model-advanced-fields"><label htmlFor={`agent-${role}-window`}>{t('agent.models.contextWindow')}</label><Input id={`agent-${role}-window`} type="number" min={1} max={100000000} step={1} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.contextWindow')} value={draft[role].configuredContextWindow ?? ''} onChange={event => update(role, { configuredContextWindow: event.target.value ? Number(event.target.value) : null })} placeholder={t('agent.models.contextAuto')} />
      <p className="agent-settings-hint">{t('agent.models.contextHint')}{draft[role].contextWindow ? ' ' + t('agent.models.contextDetected', { count: draft[role].contextWindow }) : ''}</p>
      <label className="agent-settings-switch"><span>{t('agent.models.images')}</span><Switch checked={draft[role].images} onChange={value => update(role, { images: value })} aria-label={t('agent.models.role.' + role) + ' ' + t('agent.models.images')} /></label>
      <p className="agent-settings-hint">{t('agent.models.imagesHint')}</p></div></details>
    </fieldset>)}
    {error && <p className="agent-settings-error" role="alert">{error}</p>}
    <div className="agent-settings-save"><Button type="primary" htmlType="submit" loading={saving}>{t('agent.models.save')}</Button><span>{t('agent.models.applyHint')}</span></div>
  </form>
}
