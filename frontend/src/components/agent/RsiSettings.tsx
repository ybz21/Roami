import { useEffect, useRef, useState } from 'react'
import { modelSettingsHref } from '../settings/model-settings-route'
import { Button, Input, InputNumber, Select, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import type { Overview, Preferences, ResearchSettings } from './AgentImprovement'
import type { PipelineSettings } from './PipelineRuns'
import { RsiOperationError } from './RsiOperationError'

type Configuration = { preferences: Preferences; pipeline: PipelineSettings; research?: ResearchSettings }
const configuration = (value: Overview): Configuration => ({ preferences: { ...value.preferences, cases_per_day: 60 }, pipeline: value.pipeline!.settings, research: value.research?.settings })
const newerConfiguration = (current: Configuration, incoming: Configuration): Configuration => ({
  preferences: incoming.preferences.revision >= current.preferences.revision ? incoming.preferences : current.preferences,
  pipeline: incoming.pipeline.revision >= current.pipeline.revision ? incoming.pipeline : current.pipeline,
  research: !current.research || incoming.research && incoming.research.revision >= current.research.revision ? incoming.research : current.research,
})
const preferencePayload = ({ daily_tokens: _tokens, daily_episodes: _episodes, ...value }: Preferences) => value
const pipelinePayload = (value: PipelineSettings) => Object.fromEntries(Object.entries(value).filter(([key]) => key === 'revision' || key === 'auto_publish' || key.endsWith('_model') || key.endsWith('_reasoning_effort')))
const researchPayload = (value: ResearchSettings) => ({ revision: value.revision, enabled: value.enabled, max_attempts: value.max_attempts, observation_days: value.observation_days })
const payload = (key: keyof Configuration, value: any) => key === 'preferences' ? preferencePayload(value) : key === 'pipeline' ? pipelinePayload(value) : researchPayload(value)

export function RsiSettings({ value, refresh, onDirtyChange, disabled = false }: { disabled?: boolean; value: Overview; refresh: () => void; onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(() => configuration(value)), [saved, setSaved] = useState(() => configuration(value))
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const dirtyKeys = (['preferences', 'pipeline', 'research'] as const).filter(key => draft[key] && JSON.stringify(payload(key, draft[key])) !== JSON.stringify(payload(key, saved[key])))
  const locked = busy || disabled
  const dirty = dirtyKeys.length > 0, editing = useRef(false), mounted = useRef(true)
  editing.current = dirty || locked
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { if (!editing.current) { const next = configuration(value); setDraft(current => newerConfiguration(current, next)); setSaved(current => newerConfiguration(current, next)) } }, [value])
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  const change = <K extends keyof Configuration>(key: K, patch: Partial<NonNullable<Configuration[K]>>) => setDraft(current => ({ ...current, [key]: { ...current[key], ...patch } }))
  const save = async () => {
    if (!dirty || locked) return
    setBusy(true); setError('')
    let next = draft
    try {
      for (const key of dirtyKeys) {
        const path = key === 'pipeline' ? '/pipeline/settings' : key === 'research' ? '/research' : '/preferences'
        const response = await api('PUT', '/agent/improvement' + path, payload(key, next[key]))
        if (!mounted.current) return
        next = { ...next, [key]: { ...next[key], ...response.data } }
        const accepted = next[key]
        setDraft(next); setSaved(current => ({ ...current, [key]: accepted }))
      }
      refresh()
    } catch (e: any) { if (mounted.current) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { if (mounted.current) setBusy(false) }
  }
  return <form className="rsi-settings" onSubmit={event => { event.preventDefault(); void save() }}>
    <fieldset disabled={locked} className="agent-rsi-section">
      <div className="agent-rsi-heading"><h3>{t('agent.rsi.schedule')}</h3><Switch aria-label={t('agent.rsi.enabled')} checked={draft.preferences.enabled} disabled={locked} onChange={enabled => change('preferences', { enabled })} /></div>
      <div className="agent-rsi-form">
        <label>{t('agent.rsi.suite')}<Select value={draft.preferences.suite_id || undefined} disabled={locked} virtual={false} options={value.catalog.suites.map(suite => ({ value: suite.id, label: suite.id }))} onChange={suite_id => change('preferences', { suite_id })} /></label>
        <label>{t('agent.rsi.machines')}<Select mode="multiple" value={draft.preferences.machine_ids} disabled={locked} virtual={false} options={value.catalog.machines.map(machine => ({ value: machine.id, label: machine.label }))} onChange={machine_ids => change('preferences', { machine_ids })} /></label>
        <label>{t('agent.rsi.hour')}<InputNumber min={0} max={23} value={draft.preferences.hour} disabled={locked} onChange={hour => hour != null && change('preferences', { hour })} /></label>
        <label>{t('agent.rsi.timezone')}<Input value={draft.preferences.timezone} disabled={locked} onChange={event => change('preferences', { timezone: event.target.value })} /></label>
      </div>
      <p className="agent-rsi-muted">{t('agent.rsi.dailyScope')}</p>
    </fieldset>
    <fieldset disabled={locked} className="agent-rsi-section">
      <h3>{t('agent.rsi.automation')}</h3>
      <label className="rsi-switch-row"><span>{t('agent.pipeline.autoPublish')}</span><Switch checked={draft.pipeline.auto_publish} disabled={locked} onChange={auto_publish => change('pipeline', { auto_publish })} /></label>
      {value.pipeline?.publication?.repository && <p className="agent-rsi-muted">{t('agent.pipeline.repository', { name: value.pipeline.publication.repository })}</p>}
      {draft.research && <label className="rsi-switch-row"><span>{t('agent.experiment.automate')}</span><Switch checked={draft.research.enabled} disabled={locked} onChange={enabled => change('research', { enabled })} /></label>}
      <details className="rsi-advanced"><summary>{t('agent.rsi.advanced')}</summary><div className="agent-rsi-form">
        <label className="rsi-switch-row"><span>{t('agent.rsi.autoCandidates')}</span><Switch checked={draft.preferences.auto_candidates} disabled={locked} onChange={auto_candidates => change('preferences', { auto_candidates })} /></label>
        {draft.research && <><label>{t('agent.experiment.attempts')}<InputNumber min={1} max={3} value={draft.research.max_attempts} disabled={locked} onChange={max_attempts => max_attempts != null && change('research', { max_attempts })} /></label><label>{t('agent.experiment.observationDays')}<InputNumber min={2} max={14} value={draft.research.observation_days} disabled={locked} onChange={observation_days => observation_days != null && change('research', { observation_days })} /></label></>}
      </div></details>
    </fieldset>
    <details className="agent-rsi-section rsi-advanced"><summary>{t('agent.rsi.modelOverrides')}</summary>
      <p className="agent-rsi-muted">{t('agent.rsi.modelDefaults')} <a href={modelSettingsHref('models')}>{t('agent.rsi.modelSettings')}</a></p>
      <fieldset disabled={locked} className="rsi-models">{(['main', 'worker', 'memory'] as const).map(role => <div className="pipeline-role-form" key={role}>
        <label>{t('agent.pipeline.setting.' + role + '_model')}<Input value={draft.pipeline[`${role}_model`] || ''} disabled={locked} placeholder={t('agent.pipeline.workerDefault')} onChange={event => change('pipeline', { [`${role}_model`]: event.target.value || null })} /></label>
        <label>{t('agent.pipeline.setting.' + role + '_reasoning_effort')}<Select value={draft.pipeline[`${role}_reasoning_effort`] || ''} disabled={locked} virtual={false} options={[{ value: '', label: t('agent.pipeline.workerDefault') }, ...['low', 'medium', 'high'].map(effort => ({ value: effort, label: t('agent.reasoning.' + effort) }))]} onChange={effort => change('pipeline', { [`${role}_reasoning_effort`]: effort || null })} /></label>
      </div>)}</fieldset>
    </details>
    <RsiOperationError code={error} />
    <div className="agent-settings-save"><span role="status">{t(dirty ? 'agent.models.unsaved' : 'agent.models.savedState')}</span><Button disabled={!dirty || locked} onClick={() => { setDraft(saved); setError(''); refresh() }}>{t('agent.models.discard')}</Button><Button type="primary" htmlType="submit" disabled={!dirty || disabled} loading={busy}>{t('agent.rsi.save')}</Button></div>
  </form>
}
