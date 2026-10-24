import { useEffect, useRef, useState } from 'react'
import { Button, Checkbox, Input, InputNumber, Select, Spin, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useAgentData } from './useAgentData'
import Markdown from '../markdown/Markdown'
import './agent-improvement.css'
import PipelineRuns, { type PipelineOverview } from './PipelineRuns'
import ExperimentWorkflow, { type ExperimentStage, type ExperimentView } from './ExperimentWorkflow'

type Preferences = { revision: number; enabled: boolean; timezone: string; hour: number; daily_tokens: number; daily_episodes: number; cases_per_day: number; suite_id: string; machine_ids: string[]; auto_candidates: boolean; candidate_policy: Record<string, number> }
type Comparison = { pairs: number; quality_delta: number; paired_elapsed_ratio_p50: number | null; paired_success_token_ratio_p50: number | null; eligible_for_promotion: boolean; reasons: string[]; release_blockers: string[]; strata: { layer: string; category: string; n: number; baseline_passes: number; candidate_passes: number }[] }
type Cycle = { id: string; day: string; state: string; machine_id: string; report: { comparison?: Comparison; review?: { complete: boolean; expected_trials: number; metrics_reviewed: number; logs_reviewed: number }; counts?: Record<string, { executed: number; passed: number; verified_deliveries: number }> } | null }
type Request = { id: string; machine_id: string; state: string; error_code: string | null; cycle_id: string | null }
type ResearchSettings = { revision: number; enabled: boolean; model_tokens: number; model_seconds: number; max_attempts: number; observation_days: number }
type Preview = { cases: number; machines: number; episodes: number; reservation_tokens: number | null; next_run: string | null; blockers: string[]; codex_tokens_per_operation: number }
type Research = { reports?: { cycle_id: string; day: string; points: number; issueUrl: string | null }[]; review_coverage?: { cycle_id: string; reviewed: number }[]; model_cost?: { total_tokens: number | null }; settings: ResearchSettings; actions: { id: string; kind: string; state: string; error_code: string | null }[]; improvements: { id: string; title: string; state: string; reviewUrl?: string | null }[] }
type Overview = { pipeline?: PipelineOverview; research?: Research; preferences: Preferences; catalog: { machines: { id: string; label: string; mode: string }[]; suites: { id: string; count: number; splits: Record<string, number> }[] }; cycles: Cycle[]; requests: Request[]; releases: { seq: number; active: string | null; history: { seq: number; release_id: string | null; action: string; created_ms: number }[] } }

export default function AgentImprovement({ node, workflow = false, runId = '', onRun }: { node: string | null; workflow?: boolean; runId?: string; onRun?: (id: string) => void }) {
  const { t, locale } = useI18n()
  const [stage, setStage] = useState<ExperimentStage>('evaluate')
  const [view, setView] = useState<ExperimentView>(runId ? 'runs' : 'workflow')
  useEffect(() => { if (runId) setView('runs') }, [runId])
  const [researchDraft, setResearchDraft] = useState<ResearchSettings | null>(null)
  const [researchDirty, setResearchDirty] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [poll, setPoll] = useState(0)
  const data = useAgentData<Overview>('/agent/improvement', 0, poll)
  const [draft, setDraft] = useState<Preferences | null>(null), [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(''), [error, setError] = useState('')
  const [selected, setSelected] = useState<string[]>([]), [detail, setDetail] = useState('')
  const [documents, setDocuments] = useState<Record<string, string>>({})
  const pendingRun = useRef(''), running = useRef(false), mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const scope = useRef(node); scope.current = node
  useEffect(() => { setDraft(null); setDirty(false); setSelected([]); setDetail(''); setError(''); setDocuments({}); setResearchDraft(null); setResearchDirty(false); setPreview(null); setStage('evaluate'); setView(runId ? 'runs' : 'workflow'); pendingRun.current = '' }, [node])
  useEffect(() => { if (data.value && !dirty) setDraft({ ...data.value.preferences, cases_per_day: 60 }) }, [data.value, dirty])
  useEffect(() => {
    const pipelineActive = data.value?.pipeline?.runs.some(r => ['running', 'queued', 'reviewing', 'report_queued'].includes(r.state))
    const active = pipelineActive || data.value?.requests.some(r => ['queued', 'running', 'cancelling'].includes(r.state)) || data.value?.research?.actions.some(a => ['queued', 'running'].includes(a.state))
    setPoll(active ? 2000 : (data.value?.preferences.enabled || data.value?.research?.settings.enabled) ? 30000 : 0)
  }, [data.value])
  useEffect(() => { if (data.value?.research && !researchDirty) setResearchDraft(data.value.research.settings) }, [data.value, researchDirty])
  const change = (patch: Partial<Preferences>) => { pendingRun.current = ''; setPreview(null); setDirty(true); setDraft(value => value && ({ ...value, ...patch })) }
  const loadReport = async (cycleId: string) => {
    const owner = node
    setBusy('report'); setError('')
    try {
      const response = await api('GET', '/agent/improvement/cycles/' + encodeURIComponent(cycleId))
      if (typeof response.data?.review_document !== 'string') throw new Error('missing report')
      if (scope.current === owner) setDocuments(current => ({ ...current, [cycleId]: response.data.review_document }))
    } catch { if (scope.current === owner) setError('RSI_REVIEW_REPORT_UNAVAILABLE') }
    finally { if (scope.current === owner) setBusy('') }
  }
  const mutate = async (key: string, path: string, body?: unknown, method = 'POST') => {
    const owner = node
    setBusy(key); setError('')
    try {
      await api(method, '/agent/improvement' + path, body)
      if (scope.current === owner) { if (key === 'save') setDirty(false); if (key === 'research-save') setResearchDirty(false); setPreview(null); data.refresh() }
    } catch (e: any) { if (scope.current === owner) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { if (scope.current === owner) setBusy('') }
  }
  const loadPreview = async () => {
    const owner = node
    setBusy('preview'); setError('')
    try { const response = await api('POST', '/agent/improvement/preview'); if (scope.current === owner) setPreview(response.data) }
    catch (e: any) { if (scope.current === owner) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { if (scope.current === owner) setBusy('') }
  }
  const run = async () => {
    if (running.current || !draft) return
    const owner = node, request_key = pendingRun.current || crypto.randomUUID()
    pendingRun.current = request_key; running.current = true
    setBusy('run'); setError('')
    try {
      for (const machine_id of draft.machine_ids) {
        if (!mounted.current || scope.current !== owner) return
        await api('POST', '/agent/improvement/requests', { machine_id, request_key })
      }
      if (scope.current === owner) pendingRun.current = ''
    } catch (e: any) { if (scope.current === owner) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { running.current = false; if (mounted.current && scope.current === owner) { setBusy(''); data.refresh() } }
  }
  const number = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)
  const ratio = (value: number | null | undefined) => value == null ? t('agent.rsi.unknown') : new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(value - 1)
  const state = (value: string) => t('agent.rsi.state.' + value)
  const key = () => crypto.randomUUID()
  if (data.loading) return <Spin />
  if (data.failed && !data.value) return <div className="agent-rsi-error"><p>{t('agent.rsi.loadFailed')}</p><Button onClick={data.refresh}>{t('agent.rsi.retry')}</Button></div>
  const value = data.value
  if (!value || !draft) return null
  const latest = value.cycles.find(c => c.report?.comparison)?.report?.comparison
  const chosen = value.cycles.filter(c => selected.includes(c.id))
  const selectedCycle = value.cycles.find(c => c.id === detail)
  const errorText = error ? t('agent.rsi.error.' + error, {}) : ''
  const changeResearch = (patch: Partial<ResearchSettings>) => { setPreview(null); setResearchDirty(true); setResearchDraft(current => current && ({ ...current, ...patch })) }
  const showWorkflow = !workflow || view === 'workflow'
  const showRuns = !workflow || view === 'runs'
  const showIssues = !workflow || view === 'issues'
  const actions = (workflow && value.pipeline ? [] : value.research?.actions)?.filter(action => (stage === 'observe' ? action.kind === 'activate' : stage === 'issue' ? ['issue', 'sync_issue'].includes(action.kind) : action.kind === stage)) || []
  return <div className="agent-rsi">
    {workflow && (dirty || researchDirty) && <p role="status" className="agent-rsi-muted">{t('agent.experiment.unsaved')}</p>}
    {workflow && <ExperimentWorkflow stage={stage} view={view} onStage={setStage} onView={setView} states={{}} />}
    {workflow && <PipelineRuns data={value.pipeline} view={view} node={node} runId={runId} onRun={id => { setView('runs'); if (onRun) onRun(id); else location.hash = '#/settings/experiments/rsi' + (id ? '/' + encodeURIComponent(id) : '') }} refresh={data.refresh} eligible={!dirty && !!draft.suite_id && !!draft.machine_ids.length} />}
    {workflow && showWorkflow && stage !== 'evaluate' && <section className="agent-rsi-section agent-experiment-config">
      <h3>{t('agent.experiment.stage.' + stage)}</h3>
      <p className="agent-rsi-muted">{t('agent.experiment.hint.' + stage)}</p>
      {researchDraft && <>
        {['review', 'issue', 'repair'].includes(stage) && <div>{t('agent.experiment.executor')}: <strong>Codex</strong></div>}
        {stage === 'review' && <div className="agent-rsi-form">
          <label>{t('agent.experiment.automate')}<Switch checked={researchDraft.enabled} disabled={!!busy} onChange={enabled => changeResearch({ enabled })} /></label>
          <label>{t('agent.experiment.operationTokens')}<InputNumber min={10000} max={100000} value={researchDraft.model_tokens} onChange={model_tokens => model_tokens != null && changeResearch({ model_tokens })} /></label>
          <label>{t('agent.experiment.operationSeconds')}<InputNumber min={10} max={600} value={researchDraft.model_seconds} onChange={model_seconds => model_seconds != null && changeResearch({ model_seconds })} /></label>
        </div>}
        {stage === 'repair' && <label>{t('agent.experiment.attempts')}<InputNumber min={1} max={3} value={researchDraft.max_attempts} onChange={max_attempts => max_attempts != null && changeResearch({ max_attempts })} /></label>}
        {stage === 'observe' && <label>{t('agent.experiment.observationDays')}<InputNumber min={2} max={14} value={researchDraft.observation_days} onChange={observation_days => observation_days != null && changeResearch({ observation_days })} /></label>}
        {['review', 'repair', 'observe'].includes(stage) && <div><Button type="primary" disabled={!researchDirty || !!busy} loading={busy === 'research-save'} onClick={() => { const { revision, enabled, model_tokens, model_seconds, max_attempts, observation_days } = researchDraft; void mutate('research-save', '/research', { revision, enabled, model_tokens, model_seconds, max_attempts, observation_days }, 'PUT') }}>{t('agent.rsi.save')}</Button></div>}
      </>}
      {!actions.length && <p className="agent-rsi-muted">{t('agent.experiment.idle')}</p>}
      {actions.map(action => <div className="agent-rsi-row" key={action.id}><span>{state(action.state)}{action.error_code && <small>{t('agent.rsi.failureCode', { code: action.error_code })}</small>}</span>{['blocked', 'waiting_budget'].includes(action.state) && <Button disabled={!!busy} onClick={() => void mutate('resume', '/research/' + action.id + '/resume')}>{t('agent.rsi.retry')}</Button>}</div>)}
    </section>}
    {(!workflow || (showRuns && !value.pipeline)) && <>
    <div className="agent-rsi-summary" aria-label={t('agent.rsi.results')}>
      <div><span>{t('agent.rsi.quality')}</span><strong>{latest ? number(latest.quality_delta) : t('agent.rsi.unknown')}</strong></div>
      <div><span>{t('agent.rsi.elapsed')}</span><strong>{ratio(latest?.paired_elapsed_ratio_p50)}</strong></div>
      <div><span>{t('agent.rsi.tokens')}</span><strong>{ratio(latest?.paired_success_token_ratio_p50)}</strong></div>
    </div>
    </>}
    {(error || data.failed) && <p className="agent-rsi-error" role="alert">{errorText.startsWith('agent.rsi.error.') ? t('agent.rsi.operationFailed', { code: error }) : errorText || t('agent.rsi.loadFailed')}</p>}
    {showWorkflow && (!workflow || stage === 'evaluate') && <section className="agent-rsi-section">
      <div className="agent-rsi-heading"><h3>{t('agent.rsi.schedule')}</h3><Switch checked={draft.enabled} aria-label={t('agent.rsi.enabled')} onChange={enabled => change({ enabled })} disabled={!!busy} /></div>
      <div className="agent-rsi-form">
        <label>{t('agent.rsi.suite')}<Select value={draft.suite_id || undefined} onChange={suite_id => change({ suite_id })} options={value.catalog.suites.map(s => ({ value: s.id, label: t('agent.rsi.suiteCount', { name: s.id, count: number(s.count) }) }))} /></label>
        <label>{t('agent.rsi.machines')}<Select mode="multiple" value={draft.machine_ids} onChange={machine_ids => change({ machine_ids })} options={value.catalog.machines.map(m => ({ value: m.id, label: m.label }))} /></label>
        <label>{t('agent.rsi.hour')}<InputNumber min={0} max={23} value={draft.hour} onChange={hour => hour != null && change({ hour })} /></label>
        <label>{t('agent.rsi.timezone')}<Input value={draft.timezone} onChange={e => change({ timezone: e.target.value })} /></label>
        <label>{t('agent.rsi.dailyTokens')}<InputNumber min={0} max={100000000} value={draft.daily_tokens} onChange={daily_tokens => daily_tokens != null && change({ daily_tokens })} /></label>
        <label>{t('agent.rsi.dailyEpisodes')}<InputNumber min={0} max={10000} value={draft.daily_episodes} onChange={daily_episodes => daily_episodes != null && change({ daily_episodes })} /></label>
        <label>{t('agent.rsi.dailyCases')}<InputNumber value={60} readOnly /></label>
        <Checkbox checked={draft.auto_candidates} onChange={e => change({ auto_candidates: e.target.checked })}>{t('agent.rsi.autoCandidates')}</Checkbox>
        {!draft.auto_candidates && <details><summary>{t('agent.rsi.candidatePolicy')}</summary>{Object.entries({ memory_recall_limit: 8, memory_recall_tokens: 2000, tool_directory_page_size: 10, keep_recent_tokens: 20000 }).map(([name, fallback]) => <label key={name}>{t('agent.rsi.parameter.' + name)}<InputNumber min={1} value={draft.candidate_policy[name] ?? fallback} onChange={next => next != null && change({ candidate_policy: { ...draft.candidate_policy, [name]: next } })} /></label>)}</details>}
      </div>
      <div className="agent-rsi-actions">
        {workflow && <Button loading={busy === 'preview'} disabled={dirty || researchDirty || !!busy} onClick={() => void loadPreview()}>{t('agent.experiment.preview')}</Button>}
        <Button type="primary" loading={busy === 'save'} disabled={!dirty || !!busy} onClick={() => mutate('save', '/preferences', draft, 'PUT')}>{t('agent.rsi.save')}</Button>
        <Button loading={busy === 'run'} disabled={dirty || researchDirty || !!busy || !draft.machine_ids.length || !draft.daily_tokens} onClick={() => void run()}>{t('agent.rsi.run')}</Button>
        {!value.catalog.suites.length && <Button loading={busy === 'prepare'} disabled={!!busy} onClick={() => mutate('prepare', '/prepare')}>{t('agent.rsi.prepare')}</Button>}
        {!value.catalog.machines.length && <Button disabled={!!busy} onClick={() => mutate('machine', '/machines', { id: 'local-container', label: t('agent.rsi.localMachine'), mode: 'container' })}>{t('agent.rsi.addLocal')}</Button>}
      </div>
      {!draft.daily_tokens && <p className="agent-rsi-muted">{t('agent.rsi.budgetHint')}</p>}
    </section>}
    {workflow && showWorkflow && preview && <section className="agent-rsi-section" aria-label={t('agent.experiment.preview')}>
      <dl className="agent-experiment-preview">{Object.entries({ cases: number(preview.cases), machines: number(preview.machines), episodes: number(preview.episodes), reservation: preview.reservation_tokens == null ? t('agent.rsi.unknown') : number(preview.reservation_tokens), nextRun: preview.next_run ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: draft.timezone }).format(new Date(preview.next_run)) : t('agent.experiment.scheduleOff'), operationTokens: number(preview.codex_tokens_per_operation) }).map(([name, text]) => <div key={name}><dt>{t('agent.experiment.preview.' + name)}</dt><dd>{text}</dd></div>)}</dl>
      <p className="agent-rsi-muted">{t('agent.experiment.previewHint')}</p>
      {!!preview.blockers.length && <ul>{preview.blockers.map(code => <li key={code}>{t('agent.rsi.error.' + code).startsWith('agent.rsi.error.') ? t('agent.rsi.operationFailed', { code }) : t('agent.rsi.error.' + code)}</li>)}</ul>}
    </section>}
    {showRuns && !value.pipeline && !!value.requests.length && <section className="agent-rsi-section"><h3>{t('agent.rsi.execution')}</h3>{value.requests.map(request => <div className="agent-rsi-row" key={request.id}><span>{value.catalog.machines.find(m => m.id === request.machine_id)?.label || request.machine_id}<small>{state(request.state)}{request.error_code && t('agent.rsi.failureCode', { code: request.error_code })}</small></span>{['queued', 'running'].includes(request.state) && <button type="button" className="tt-act" disabled={!!busy} onClick={() => mutate('cancel', '/requests/' + request.id + '/cancel')}>{t('agent.rsi.cancel')}</button>}</div>)}</section>}
    {showIssues && value.research && (workflow || value.research.settings.enabled || !!value.research.improvements.length || !!value.research.reports?.length) && <section className="agent-rsi-section">
      <h3>{t('agent.rsi.research')}</h3>
      {value.research.reports?.map(report => <div key={report.cycle_id}>
        <div className="agent-rsi-row"><span>{t('agent.rsi.periodReport', { date: report.day, count: report.points })}</span>{report.issueUrl?.startsWith('https://github.com/') && <a className="tt-act" href={report.issueUrl} target="_blank" rel="noopener noreferrer">{t('agent.rsi.viewIssue')}</a>}</div>
        <details><summary>{t('agent.rsi.reviewDocument')}</summary>{documents[report.cycle_id] ? <Markdown allowImages={false}>{documents[report.cycle_id]}</Markdown> : <Button loading={busy === 'report'} disabled={!!busy} onClick={() => void loadReport(report.cycle_id)}>{t('agent.rsi.loadReport')}</Button>}</details>
      </div>)}
      {!value.research.improvements.length && <p className="agent-rsi-muted">{t('agent.rsi.noFindings')}</p>}
      {value.research.improvements.map(item => <div className="agent-rsi-row" key={item.id}><span>{item.title}<small>{state(item.state)}</small></span>{item.reviewUrl?.startsWith('https://github.com/') && <a className="tt-act" href={item.reviewUrl} target="_blank" rel="noopener noreferrer">{t('agent.rsi.reviewPullRequest')}</a>}</div>)}
      <details><summary>{t('agent.rsi.researchSteps')}</summary>{value.research.model_cost && <p className="agent-rsi-muted">{t('agent.rsi.researchTokens', { count: value.research.model_cost.total_tokens == null ? t('agent.rsi.unknown') : number(value.research.model_cost.total_tokens) })}</p>}{value.research.actions.map(action => <div className="agent-rsi-row" key={action.id}><span>{t('agent.rsi.stage.' + action.kind)}<small>{state(action.state)}{action.error_code && t('agent.rsi.failureCode', { code: action.error_code })}</small></span>{['blocked', 'waiting_budget'].includes(action.state) && <button type="button" className="tt-act" disabled={!!busy} onClick={() => mutate('resume', '/research/' + action.id + '/resume')}>{t('agent.rsi.retry')}</button>}</div>)}</details>
    </section>}
    {showRuns && !value.pipeline && <section className="agent-rsi-section">
      <div className="agent-rsi-heading"><h3>{t('agent.rsi.cycles')}</h3>{!!selected.length && <Button disabled={!!busy || chosen.some(c => c.state !== 'completed')} onClick={() => mutate('release', '/releases', { cycle_ids: selected, expected_seq: value.releases.seq, request_key: key() })}>{t('agent.rsi.publish')}</Button>}</div>
      {!value.cycles.length && <p className="agent-rsi-muted">{t('agent.rsi.empty')}</p>}
      {value.cycles.map(cycle => <div className="agent-rsi-row" key={cycle.id}>
        <Checkbox aria-label={t('agent.rsi.selectCycle', { date: cycle.day })} checked={selected.includes(cycle.id)} onChange={e => setSelected(items => e.target.checked ? [...items, cycle.id] : items.filter(i => i !== cycle.id))} />
        <button type="button" className="agent-rsi-cycle" aria-expanded={detail === cycle.id} onClick={() => setDetail(detail === cycle.id ? '' : cycle.id)}><span>{new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(cycle.day + 'T12:00:00Z'))}<small>{cycle.machine_id}</small></span><span>{state(cycle.state)}</span></button>
      </div>)}
      {selectedCycle && <div className="agent-rsi-detail"><h4>{t('agent.rsi.comparison')}</h4>
        {selectedCycle.report?.review && <p>{t(selectedCycle.report.review.complete ? 'agent.rsi.reviewComplete' : 'agent.rsi.reviewIncomplete')}{' '}{t('agent.rsi.reviewCoverage', { metrics: selectedCycle.report.review.metrics_reviewed, logs: selectedCycle.report.review.logs_reviewed, total: selectedCycle.report.review.expected_trials })}</p>}
        {value.research?.settings.enabled && selectedCycle.report?.review && <p>{t('agent.rsi.semanticCoverage', { count: value.research.review_coverage?.find(r => r.cycle_id === selectedCycle.id)?.reviewed || 0, total: selectedCycle.report.review.expected_trials })}</p>}
        {selectedCycle.report?.comparison ? <><dl>{Object.entries(selectedCycle.report.counts || {}).map(([arm, counts]) => <div key={arm}><dt>{t('agent.rsi.arm.' + arm)}</dt><dd>{t('agent.rsi.passCount', { passed: number(counts.passed), total: number(counts.executed), deliveries: number(counts.verified_deliveries) })}</dd></div>)}</dl><p>{selectedCycle.report.comparison.eligible_for_promotion ? t('agent.rsi.eligible') : t('agent.rsi.ineligible')}</p><ul>{selectedCycle.report.comparison.reasons.map(reason => <li key={reason}>{t('agent.rsi.reason.' + reason)}</li>)}</ul><details><summary>{t('agent.rsi.evidence')}</summary><code>{selectedCycle.id}</code><ul>{selectedCycle.report.comparison.release_blockers.map((reason, i) => <li key={i}>{reason}</li>)}</ul></details></> : <p>{t('agent.rsi.noResult')}</p>}
      </div>}
    </section>}
    {showRuns && !value.pipeline && <section className="agent-rsi-section"><div className="agent-rsi-heading"><h3>{t('agent.rsi.releases')}</h3>{value.releases.active && <Button disabled={!!busy} onClick={() => mutate('rollback', '/rollback', { expected_seq: value.releases.seq, request_key: key() })}>{t('agent.rsi.rollback')}</Button>}</div><p className="agent-rsi-muted">{value.releases.active ? t('agent.rsi.activeHint') : t('agent.rsi.baselineHint')}</p>{value.releases.history.map(release => <div className="agent-rsi-row" key={release.seq}><span>{t('agent.rsi.action.' + release.action)}<small>{new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(release.created_ms))}</small></span><code>{release.release_id?.slice(0, 12) || t('agent.rsi.baseline')}</code></div>)}</section>}
  </div>
}
