import { useEffect, useRef, useState } from 'react'
import { Button, ConfigProvider, Input, InputNumber, Select, Spin, Switch } from 'antd'
import { modelSettingsHref } from '../settings/model-settings-route'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { ChevronLeft, GearIcon, PlayIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import Markdown from '../markdown/Markdown'
import { useAgentData } from './useAgentData'
import RsiRunResults from './RsiRunResults'
import { initialResultsView, type CaseDefinition, type IssueDefinition, type RunRecord } from './rsi-history'
import type { WorkflowArtifact, WorkflowStage } from './RsiWorkflow'
import './rsi-workspace.css'

type Overview = {
  preferences: { revision: number; enabled: boolean; hour: number; timezone: string; machine_ids: string[]; suite_id: string; [key: string]: unknown }
  research: { settings: { revision: number; enabled: boolean; [key: string]: unknown } }
  pipeline: { settings: { revision: number; auto_publish: boolean; [key: string]: unknown }; runs: { id: string; state: string; created_ms: number; mode: string }[] }
  catalog: { suites: { id: string; count: number }[]; machines: { id: string; label: string }[] }
}
type Results = { runs: RunRecord[]; cases: CaseDefinition[]; issues: IssueDefinition[]; history_complete: boolean }
const activeStates = new Set(['queued', 'running', 'reviewing', 'report_queued'])
const tabs = ['workflow', 'overview', 'issues'] as const
type Tab = typeof tabs[number]

export default function RsiWorkspace({ node, runId = '', onRun }: { node: string | null; runId?: string; onRun?: (id: string) => void }) {
  const { t, locale } = useI18n(), { phone } = useLayout()
  const [tab, setTab] = useState<Tab>('overview'), [selection, setSelection] = useState(() => ({ ...initialResultsView, runId, baselineId: '' }))
  const [stage, setStage] = useState<WorkflowStage | null>(null), [poll, setPoll] = useState(0)
  const overview = useAgentData<Overview>('/agent/improvement', 5000, poll)
  const live = overview.value
  const selectedId = runId || (selection.runId.length === 64 ? selection.runId : live?.pipeline.runs[0]?.id) || ''
  const runState = live?.pipeline.runs.find(run => run.id === selectedId)?.state
  const detail = useAgentData<Results>(selectedId ? '/agent/improvement/pipeline/runs/' + encodeURIComponent(selectedId) + '/results' : null, 0, runState && activeStates.has(runState) ? 2000 : 0)
  const [settingsOpen, setSettingsOpen] = useState(false), [draft, setDraft] = useState<Overview | null>(null), [dirty, setDirty] = useState(false)
  const models = useAgentData<{ proxy?: { dailyLimit: number | null; currency: string } }>('/agent/model-settings', 0, 0, 'GET', settingsOpen)
  const [artifact, setArtifact] = useState<{ name: string; text?: string } | null>(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState('')
  const scope = useRef(node); scope.current = node
  const pending = useRef(new Map<string, string>()), starting = useRef(false), mounted = useRef(true)
  const acknowledged = useRef<Overview | null>(null)
  const selectionRef = useRef(selection); selectionRef.current = selection
  const baselineInitialized = useRef('')
  useEffect(() => { if (detail.value && baselineInitialized.current !== selectedId) { const index = detail.value.runs.findIndex(run => run.id === selectedId); if (index < 0) return; baselineInitialized.current = selectedId; setSelection(current => ({ ...current, runId: selectedId, baselineId: current.baselineId || detail.value!.runs[index - 1]?.id || '' })) } }, [detail.value, selectedId])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { setPoll(live?.pipeline.runs.some(run => activeStates.has(run.state)) ? 2000 : live?.preferences.enabled ? 30000 : 0) }, [live])
  useEffect(() => { if (live && !dirty) { setDraft(live); acknowledged.current = live } }, [live, dirty])
  useEffect(() => { if (selectedId) setSelection(value => value.runId === selectedId ? value : { ...value, runId: selectedId, baselineId: '' }) }, [selectedId])
  const chosen = useRef(selectedId); chosen.current = selectedId
  useEffect(() => { setArtifact(null); setError('') }, [selectedId, node])
  const mutate = async (key: string, path: string, value?: unknown, method = 'POST') => {
    const owner = node
    setBusy(key); setError('')
    try {
      const response = await api(method, '/agent/improvement' + path, value)
      if (mounted.current && scope.current === owner) { overview.refresh(); detail.refresh() }
      return response.data
    } catch (e: any) { if (mounted.current && scope.current === owner) setError(e.apiError?.code || 'RSI_OPERATION_FAILED'); throw e }
    finally { if (mounted.current && scope.current === owner) setBusy('') }
  }
  const openArtifact = async (value: WorkflowArtifact) => {
    if (!value.artifactId) { setArtifact({ name: value.name, text: value.text }); return }
    const owner = node, run = selectedId
    setBusy('artifact'); setError('')
    try {
      const response = await api('GET', '/agent/improvement/pipeline/runs/' + encodeURIComponent(value.runId || run) + '/artifacts/' + encodeURIComponent(value.artifactId))
      if (mounted.current && scope.current === owner && chosen.current === run) setArtifact(response.data)
    } catch { if (scope.current === owner) setError('RSI_ARTIFACT_UNAVAILABLE') }
    finally { if (scope.current === owner) setBusy('') }
  }
  const save = async () => {
    if (!draft || !acknowledged.current) return
    const owner = node
    setBusy('save'); setError('')
    try {
      const sections = [
        { path: '/preferences', value: draft.preferences, previous: acknowledged.current.preferences, update: (value: any) => { acknowledged.current = { ...acknowledged.current!, preferences: value }; setDraft(current => current && ({ ...current, preferences: value })) } },
        { path: '/pipeline/settings', value: draft.pipeline.settings, previous: acknowledged.current.pipeline.settings, update: (value: any) => { acknowledged.current = { ...acknowledged.current!, pipeline: { ...acknowledged.current!.pipeline, settings: value } }; setDraft(current => current && ({ ...current, pipeline: { ...current.pipeline, settings: value } })) } },
        { path: '/research', value: Object.fromEntries(['revision', 'enabled', 'model_seconds', 'max_attempts', 'observation_days'].map(key => [key, draft.research.settings[key]])), previous: Object.fromEntries(['revision', 'enabled', 'model_seconds', 'max_attempts', 'observation_days'].map(key => [key, acknowledged.current!.research.settings[key]])), update: (value: any) => { acknowledged.current = { ...acknowledged.current!, research: { ...acknowledged.current!.research, settings: value } }; setDraft(current => current && ({ ...current, research: { ...current.research, settings: value } })) } },
      ]
      for (const section of sections) {
        if (JSON.stringify(section.value) === JSON.stringify(section.previous)) continue
        const response = await api('PUT', '/agent/improvement' + section.path, section.value)
        if (!mounted.current || scope.current !== owner) return
        section.update(response.data)
      }
      if (scope.current === owner) { setDirty(false); setSettingsOpen(false); overview.refresh() }
    } catch (e: any) { if (scope.current === owner) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { if (scope.current === owner) setBusy('') }
  }
  const start = async (full: boolean, baseline = '') => {
    if (starting.current || busy || dirty) return
    const owner = node
    starting.current = true; setBusy('run'); setError('')
    const signature = JSON.stringify([full, baseline, draft?.preferences.suite_id, full ? draft?.preferences.machine_ids : []])
    const key = pending.current.get(signature) || crypto.randomUUID()
    pending.current.set(signature, key)
    let result: { id: string } | null = null
    try {
      if (full && draft) {
        for (const machine_id of draft.preferences.machine_ids) {
          const response = await api('POST', '/agent/improvement/requests', { machine_id, request_key: key })
          result ||= response.data
        }
      } else result = (await api('POST', '/agent/improvement/pipeline/requests', { request_key: key, ...(baseline ? { baseline_run: baseline } : {}) })).data
      pending.current.delete(signature)
      if (mounted.current && scope.current === owner && result) { setSelection({ ...initialResultsView, runId: result.id, baselineId: selectedId }); onRun?.(result.id); overview.refresh() }
    } catch (error: any) { if (mounted.current && scope.current === owner) setError(error.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { starting.current = false; if (mounted.current && scope.current === owner) setBusy('') }
  }
  const changePreferences = (value: Partial<Overview['preferences']>) => { setDirty(true); setDraft(current => current && ({ ...current, preferences: { ...current.preferences, ...value } })) }
  const changePipeline = (auto_publish: boolean) => { setDirty(true); setDraft(current => current && ({ ...current, pipeline: { ...current.pipeline, settings: { ...current.pipeline.settings, auto_publish } } })) }
  const changeResearch = (enabled: boolean) => { setDirty(true); setDraft(current => current && ({ ...current, research: { ...current.research, settings: { ...current.research.settings, enabled } } })) }
  const select = (update: Parameters<typeof setSelection>[0]) => {
    const previous = selectionRef.current
    const next = typeof update === 'function' ? update(previous) : update
    selectionRef.current = next; setSelection(next)
    if (next.runId !== previous.runId) onRun?.(next.runId)
  }
  const proxy = models.value?.proxy
  const modelLink = () => { location.hash = modelSettingsHref('proxy') }
  const settings = draft ? <ConfigProvider componentDisabled={!!busy}>
    <div className="rsi-scroll"><div className="rsi-content">
      {error && <p role="alert" className="rsi-danger">{t('agent.rsi.operationFailed', { code: error })}</p>}
      <section className="rsi-section"><div className="rsi-setting-toggle"><span><strong>{t('agent.rsiPrototype.schedule')}</strong></span><Switch checked={draft.preferences.enabled} aria-label={t('agent.rsiPrototype.schedule')} onChange={enabled => changePreferences({ enabled })} /></div>{draft.preferences.enabled && <div className="rsi-form-grid"><label>{t('agent.rsi.hour')}<InputNumber min={0} max={23} value={draft.preferences.hour} onChange={hour => hour != null && changePreferences({ hour })} /></label><label>{t('agent.rsi.timezone')}<Input value={draft.preferences.timezone} onChange={event => changePreferences({ timezone: event.target.value })} /></label></div>}</section>
      <section className="rsi-section"><h3>{t('agent.rsiPrototype.scope')}</h3><div className="rsi-form-grid"><label>{t('agent.rsi.suite')}<Select value={draft.preferences.suite_id || undefined} options={live?.catalog.suites.map(value => ({ value: value.id, label: value.id + ' · ' + value.count }))} onChange={suite_id => changePreferences({ suite_id })} /></label><label>{t('agent.rsi.machines')}<Select mode="multiple" value={draft.preferences.machine_ids} options={live?.catalog.machines.map(value => ({ value: value.id, label: value.label }))} onChange={machine_ids => changePreferences({ machine_ids })} /></label></div>{!live?.catalog.suites.length && <Button disabled={!!busy} onClick={() => void mutate('prepare', '/prepare').catch(() => {})}>{t('agent.rsi.prepare')}</Button>}{!live?.catalog.machines.length && <Button disabled={!!busy} onClick={() => void mutate('machine', '/machines', { id: 'local-container', label: t('agent.rsi.localMachine'), mode: 'container' }).catch(() => {})}>{t('agent.rsi.addLocal')}</Button>}</section>
      <section className="rsi-section"><h3>{t('agent.rsiPrototype.workflow')}</h3><div className="rsi-setting-toggle"><span>{t('agent.rsiPrototype.autoRepair')}</span><Switch checked={draft.research.settings.enabled} aria-label={t('agent.rsiPrototype.autoRepair')} onChange={changeResearch} /></div><div className="rsi-setting-toggle"><span>{t('agent.rsiPrototype.autoIssue')}</span><Switch checked={draft.pipeline.settings.auto_publish} aria-label={t('agent.rsiPrototype.autoIssue')} onChange={changePipeline} /></div></section>
      <section className="rsi-section"><h3>{t('agent.rsiPrototype.modelsBudget')}</h3><p className="rsi-muted">{t('agent.rsiPrototype.sharedHint')}</p><div className="rsi-budget-note"><span>{models.failed ? t('agent.rsi.loadFailed') : !models.value ? t('common.loading') : proxy?.dailyLimit == null ? t('agent.proxy.unlimited') : new Intl.NumberFormat(locale, { style: 'currency', currency: proxy.currency }).format(proxy.dailyLimit)}</span><Button onClick={modelLink}>{t('agent.rsiPrototype.modelPage')}</Button></div></section>
    </div></div>
    <footer className="rsi-savebar"><span className="rsi-muted">{dirty ? t('agent.rsiPrototype.unsaved') : ''}</span><Button disabled={!!busy} onClick={() => { setDraft(acknowledged.current); setDirty(false); setSettingsOpen(false) }}>{t('agent.rsiPrototype.cancel')}</Button><Button type="primary" loading={busy === 'save'} disabled={!dirty || !!busy} onClick={() => void save()}>{t('agent.rsi.save')}</Button></footer>
  </ConfigProvider> : <div className="rsi-content">{overview.failed ? <p role="alert">{t('agent.rsi.loadFailed')}<Button onClick={overview.refresh}>{t('agent.rsi.retry')}</Button></p> : <Spin />}</div>
  const artifactContent = artifact && <div className="rsi-scroll"><div className="rsi-content"><section className="rsi-section"><h3>{artifact.name}</h3>{artifact.name.endsWith('.md') ? <Markdown allowImages={false}>{artifact.text || ''}</Markdown> : <pre className="rsi-artifact-preview">{artifact.text}</pre>}</section></div></div>
  const data = detail.value
  const record = data?.runs.find(run => run.id === selectedId)
  const publication = record?.publication?.url
  const runs = data?.runs.map(run => ({ ...run, time: typeof run.time === 'number' ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(run.time) : run.time })) || []
  return <div className="rsi-workspace">
    <div className="rsi-main">
      {(error || overview.failed || detail.failed) && <p className="rsi-danger" role="alert">{error ? t('agent.rsi.error.' + error).startsWith('agent.rsi.error.') ? t('agent.rsi.operationFailed', { code: error }) : t('agent.rsi.error.' + error) : t('agent.rsi.loadFailed')}<Button onClick={() => { overview.refresh(); detail.refresh() }}>{t('agent.rsi.retry')}</Button></p>}
      {(!phone && settingsOpen) || (!phone && artifact) ? <><header className="rsi-pagehead rsi-return-head"><button type="button" className="rsi-back" aria-label={t('common.back')} onClick={() => { if (artifact) setArtifact(null); else setSettingsOpen(false) }}><ChevronLeft size={20} /></button><strong>{artifact ? t('agent.rsiPrototype.artifactTitle') : t('agent.rsiPrototype.settings')}</strong></header>{artifact ? artifactContent : settings}</> : <>
        <header className={phone ? "rsi-live-actions" : "tt-pagehead rsi-live-head"}>{!phone && <h2>{t('agent.rsiPrototype.title')}</h2>}<div className="acts">{selectedId && selectedId !== live?.pipeline.runs[0]?.id && <Button onClick={() => { const id = live?.pipeline.runs[0]?.id; if (id) { setSelection({ ...initialResultsView, runId: id, baselineId: selectedId }); onRun?.(id) } }}>{t('agent.rsiResults.latestRun')}</Button>}{record?.rawState === 'blocked' && <Button disabled={!!busy} onClick={() => void mutate('resume', '/pipeline/runs/' + selectedId + '/resume').catch(() => {})}>{t('agent.rsi.retry')}</Button>}{publication?.startsWith('https://github.com/') && <a href={publication} target="_blank" rel="noopener noreferrer">{t('agent.rsi.viewIssue')}</a>}<Button icon={<GearIcon size={16} />} onClick={() => setSettingsOpen(true)}>{t('agent.rsiPrototype.settings')}</Button><Button disabled={!!busy || dirty} icon={<PlayIcon />} onClick={() => void start(false)}>{t('agent.pipeline.startTen')}</Button><Button type="primary" disabled={!!busy || dirty || !live?.preferences.machine_ids.length} loading={busy === 'run'} onClick={() => void start(true)}>{t('agent.rsiPrototype.full')}</Button></div></header>
        <nav className="rsi-tabs" role="tablist" aria-label={t('agent.rsiPrototype.title')}>{tabs.map((value, index) => <button type="button" key={value} role="tab" id={'live-rsi-tab-' + value} aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} onClick={() => setTab(value)} onKeyDown={event => { if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : -1) + 3) % 3]; setTab(next); document.getElementById('live-rsi-tab-' + next)?.focus() }}>{t('agent.rsiResults.' + (value === 'workflow' ? 'workflowTab' : value === 'overview' ? 'runResults' : 'issueTab'))}</button>)}</nav>
        <div className="rsi-scroll" role="tabpanel" aria-labelledby={'live-rsi-tab-' + tab}><div className="rsi-content rsi-content-results">{data && !data.history_complete && <p className="rsi-muted">{t('agent.rsiResults.historyPartial')}</p>}{record?.blocker && <div className="rsi-budget-note" role="status"><span>{t(record.blocker === 'MODEL_PROXY_DAILY_LIMIT' ? 'agent.proxy.limitReached' : record.blocker === 'MODEL_PROXY_CURRENCY_MISMATCH' ? 'agent.proxy.currencyMismatch' : 'agent.rsiPrototype.usageUnknownHint')}</span><Button onClick={modelLink}>{t('agent.rsiPrototype.modelPage')}</Button></div>}{overview.loading || detail.loading ? <Spin /> : data ? <RsiRunResults issueActions={record && <div className="rsi-results-actions"><Button disabled={!!busy || dirty || !record.scope.length} onClick={() => void start(false, record.id)}>{t('agent.pipeline.rerun')}</Button>{!publication && Object.values(record.workflow || {}).some(node => node.artifacts.some(artifact => artifact.name === 'issue-plan.json')) && <Button disabled={!!busy} onClick={() => void mutate('publish', '/pipeline/runs/' + selectedId + '/publish').catch(() => {})}>{t('agent.pipeline.publishIssue')}</Button>}</div>} view={tab} scenario="live" progress={0} runs={runs} cases={data.cases} issues={data.issues} stopped={false} onStop={() => void mutate('cancel', '/requests/' + selectedId + '/cancel').catch(() => {})} state={{ ...selection, runId: selectedId }} setState={select} workflowStage={stage} onStage={setStage} onArtifact={value => void openArtifact(value)} onView={setTab} /> : <section className="rsi-empty"><p>{t('agent.rsiResults.noResults')}</p><Button onClick={() => setSettingsOpen(true)}>{t('agent.rsiPrototype.settings')}</Button></section>}</div></div>
      </>}
    </div>
    {phone && settingsOpen && <MobileSubPage title={t('agent.rsiPrototype.settings')} onBack={() => setSettingsOpen(false)} search={false} keepBottomNav>{settings}</MobileSubPage>}
    {phone && artifact && <MobileSubPage title={t('agent.rsiPrototype.artifactTitle')} onBack={() => setArtifact(null)} search={false}>{artifactContent}</MobileSubPage>}
  </div>
}
