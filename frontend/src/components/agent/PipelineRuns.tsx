import { useEffect, useRef, useState } from 'react'
import { Button, Input, InputNumber, Select, Spin, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import Markdown from '../markdown/Markdown'
import { useAgentData } from './useAgentData'
import ExperimentWorkflow, { type ExperimentStage } from './ExperimentWorkflow'
import './pipeline-runs.css'

export type PipelineSettings = { revision: number; auto_publish: boolean; daily_tokens: number; generation_tokens: number; codex_tokens: number; output_tokens: number; main_output_tokens?: number | null; worker_output_tokens?: number | null; memory_output_tokens: number; main_model?: string | null; main_reasoning_effort?: string | null; worker_model?: string | null; worker_reasoning_effort?: string | null; memory_model?: string | null; memory_reasoning_effort?: string | null }
type Issue = { id: string; case_id: string; code: string; latest_status?: string; status?: string; latest_run_id?: string }
type Run = { id: string; mode: string; state: string; created_ms: number; updated_ms: number; summary: Record<string, number | null> | null; issue: { url: string; number: number } | null }
export type PipelineOverview = { settings: PipelineSettings; runs: Run[]; issues: Issue[]; publication?: { repository: string | null } }
type RunDetail = Run & { snapshot: { case_ids: string[]; baseline_run?: string; suite_hash?: string; [key: string]: unknown }; nodes: { node: ExperimentStage; attempt: number; state: string; config: unknown; started_ms: number | null; finished_ms: number | null; error_code: string | null }[]; cases: { case_id: string; state: string; passed: boolean; kind?: string; quality: number | null; metrics: { tokens: number | null; model_calls: number | null }; signals: string[]; tool_calls: number | null }[]; artifacts: { id: string; name: string; node: string; bytes: number; sha256: string }[]; issues: Issue[] }

export default function PipelineRuns({ data, view, node, runId = '', onRun, refresh, eligible }: { data?: PipelineOverview; view: string; node: string | null; runId?: string; onRun: (id: string) => void; refresh: () => void; eligible: boolean }) {
  const { t, locale } = useI18n()
  const [draft, setDraft] = useState<PipelineSettings | null>(null), [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(''), [error, setError] = useState('')
  const requestKey = useRef(''), active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => { if (data && !dirty) setDraft(current => current && current.revision > data.settings.revision ? current : data.settings) }, [data, dirty])
  const change = (patch: Partial<PipelineSettings>) => { setDirty(true); setDraft(value => value && ({ ...value, ...patch })) }
  const mutate = async (key: string, path: string, body?: unknown, method = 'POST') => {
    setBusy(key); setError('')
    try {
      const response = await api(method, (path.startsWith('/cancel/') ? '/agent/improvement/requests/' + path.slice(8) + '/cancel' : '/agent/improvement/pipeline' + path), body)
      if (!active.current) return
      if (key === 'save') { setDraft(response.data); setDirty(false) }
      if (key === 'start') { requestKey.current = ''; onRun(response.data.id) }
      refresh()
    } catch (e: any) { if (active.current) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { if (active.current) setBusy('') }
  }
  const start = (baseline?: string) => { requestKey.current ||= crypto.randomUUID(); void mutate('start', '/requests', { request_key: requestKey.current, ...(baseline ? { baseline_run: baseline } : {}) }) }
  const date = (value: number) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(value)
  if (!data || !draft) return null
  return <>
    {error && <p className="agent-rsi-error" role="alert">{t('agent.rsi.operationFailed', { code: error })}</p>}
    {view === 'workflow' && <section className="agent-rsi-section">
      <h3>{t('agent.pipeline.settings')}</h3>
      <p className="agent-rsi-muted">{data.publication?.repository ? t('agent.pipeline.repository', { name: data.publication.repository }) : t('agent.pipeline.configureRepository')}</p>
      <div className="agent-rsi-form pipeline-settings">
        <label>{t('agent.pipeline.autoPublish')}<Switch checked={draft.auto_publish} disabled={!!busy} onChange={auto_publish => change({ auto_publish })} /></label>
        {(['daily_tokens', 'generation_tokens', 'codex_tokens', 'memory_output_tokens'] as const).map(key => <label key={key}>{t('agent.pipeline.setting.' + key)}<InputNumber value={draft[key]} min={key === 'codex_tokens' ? 20000 : key === 'memory_output_tokens' ? 1024 : 10000} max={key === 'memory_output_tokens' ? 8192 : key === 'codex_tokens' ? 100000 : key === 'generation_tokens' ? 2000000 : 100000000} onChange={value => value != null && change({ [key]: value })} /></label>)}
        {(['main', 'worker', 'memory'] as const).map(role => <div className="pipeline-role-form" key={role}>
          <label>{t('agent.pipeline.setting.' + role + '_model')}<Input value={draft[`${role}_model`] || ''} placeholder={t('agent.pipeline.workerDefault')} onChange={event => change({ [`${role}_model`]: event.target.value || null })} /></label>
          {role !== 'memory' && <label>{t('agent.pipeline.setting.' + role + '_output_tokens')}<InputNumber value={draft[`${role}_output_tokens`]} min={512} max={1000000} placeholder={t('agent.pipeline.autoOutput')} onChange={value => change({ [`${role}_output_tokens`]: value })} /></label>}
          <label>{t('agent.pipeline.setting.' + role + '_reasoning_effort')}<Select value={draft[`${role}_reasoning_effort`] || ''} options={[{ value: '', label: t('agent.pipeline.workerDefault') }, ...['low', 'medium', 'high'].map(value => ({ value, label: t('agent.reasoning.' + value) }))]} onChange={value => change({ [`${role}_reasoning_effort`]: value || null })} /></label>
        </div>)}
      </div>
      <div className="agent-rsi-actions"><Button disabled={!dirty || !!busy} loading={busy === 'save'} onClick={() => void mutate('save', '/settings', draft, 'PUT')}>{t('agent.rsi.save')}</Button><Button disabled={dirty || !!busy || !eligible} loading={busy === 'start'} onClick={() => start()}>{t('agent.pipeline.startTen')}</Button></div>
      <p className="agent-rsi-muted">{t('agent.pipeline.diagnosticHint')}</p>
    </section>}
    {view === 'runs' && <section className="agent-rsi-section">
      {runId ? <>
        <button type="button" className="tt-act" onClick={() => onRun('')}>{t('agent.pipeline.allRuns')}</button>
        <PipelineRunDetail key={node + ':' + runId} runId={runId} onCancel={() => mutate('cancel', '/cancel/' + runId)} onRetry={() => mutate('resume', '/runs/' + runId + '/resume')} onPublish={() => mutate('publish', '/runs/' + runId + '/publish')} onRerun={() => start(runId)} busy={busy || (dirty ? 'dirty' : '')} refresh={refresh} />
      </> : <>
        <h3>{t('agent.pipeline.runs')}</h3>
        {!data.runs.length && <p className="agent-rsi-muted">{t('agent.pipeline.noRuns')}</p>}
        {data.runs.map(run => <div className="agent-rsi-row" key={run.id}><button type="button" className="agent-rsi-cycle" onClick={() => onRun(run.id)}><span>{t('agent.pipeline.mode.' + run.mode)}<small>{date(run.created_ms)}</small></span><span>{t('agent.pipeline.runState.' + run.state)}</span></button>{run.issue?.url?.startsWith('https://github.com/') && <a className="tt-act" href={run.issue.url} target="_blank" rel="noopener noreferrer">{t('agent.rsi.viewIssue')}</a>}</div>)}
      </>}
    </section>}
    {view === 'issues' && <section className="agent-rsi-section">
      <h3>{t('agent.pipeline.localIssues')}</h3><p className="agent-rsi-muted">{t('agent.pipeline.observationHint')}</p>
      {!data.issues.length && <p className="agent-rsi-muted">{t('agent.rsi.noFindings')}</p>}
      {data.issues.map(issue => <div className="pipeline-issue" key={issue.id}><span><strong>{signalLabel(t, issue.code)}</strong><small>{issue.case_id}</small></span><span data-observation={issue.latest_status}>{t('agent.pipeline.observation.' + (issue.latest_status || 'unverified'))}</span>{issue.latest_run_id && <button type="button" className="tt-act" onClick={() => onRun(issue.latest_run_id!)}>{t('agent.pipeline.viewRun')}</button>}</div>)}
    </section>}
  </>
}

function signalLabel(t: (key: string, vars?: Record<string, string | number>) => string, code: string) {
  if (code.startsWith('check:')) return t('agent.pipeline.check', { name: code.slice(6) })
  const key = 'agent.pipeline.signal.' + code
  const text = t(key)
  return text === key ? code : text
}

function PipelineRunDetail({ runId, onRetry, onPublish, onRerun, onCancel, busy, refresh }: { onCancel: () => Promise<void>; runId: string; onRetry: () => Promise<void>; onPublish: () => Promise<void>; onRerun: () => void; busy: string; refresh: () => void }) {
  const { t, locale } = useI18n()
  const [poll, setPoll] = useState(2000), [stage, setStage] = useState<ExperimentStage>('evaluate')
  const [file, setFile] = useState<{ name: string; text: string } | null>(null), [failed, setFailed] = useState(false)
  const chosen = useRef(''), mounted = useRef(true)
  const data = useAgentData<RunDetail>('/agent/improvement/pipeline/runs/' + encodeURIComponent(runId), 0, poll)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { setPoll(data.value && ['running', 'report_queued', 'reviewing', 'queued'].includes(data.value.state) ? 2000 : data.value?.state === 'awaiting_research' ? 30000 : 0) }, [data.value?.state])
  useEffect(() => { chosen.current = ''; setFile(null) }, [stage])
  const loadFile = async (id: string) => {
    chosen.current = id; setFailed(false)
    try { const response = await api('GET', '/agent/improvement/pipeline/runs/' + encodeURIComponent(runId) + '/artifacts/' + encodeURIComponent(id)); if (mounted.current && chosen.current === id) setFile(response.data) }
    catch { if (mounted.current && chosen.current === id) setFailed(true) }
  }
  if (data.loading) return <Spin />
  if (!data.value) return <p role="alert">{t('agent.rsi.loadFailed')} <Button onClick={data.refresh}>{t('agent.rsi.retry')}</Button></p>
  const value = data.value
  const latest = Object.fromEntries(value.nodes.map(node => [node.node, node]))
  const attempts = value.nodes.filter(node => node.node === stage)
  const selected = latest[stage]
  const number = (value: number | null | undefined) => value == null ? t('agent.rsi.unknown') : new Intl.NumberFormat(locale).format(value)
  const tasks = value.cases.filter(c => c.kind !== 'mechanism' && c.kind !== 'environment')
  const mechanisms = value.cases.filter(c => c.kind === 'mechanism')
  return <div className="pipeline-run-detail">
    <div className="agent-rsi-heading"><h3>{t('agent.pipeline.mode.' + value.mode)} · {new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(value.created_ms)}</h3><span>{t('agent.pipeline.runState.' + value.state)}</span></div>
    <div className="agent-rsi-summary"><div><span>{t('agent.pipeline.taskPassed')}</span><strong>{tasks.filter(c => c.passed).length}/{tasks.length}</strong></div><div><span>{t('agent.pipeline.mechanisms')}</span><strong>{mechanisms.filter(c => c.passed).length}/{mechanisms.length}</strong></div><div><span>{t('agent.pipeline.generationTokens')}</span><strong>{number(value.summary?.generation_tokens)}</strong></div></div>
    {(value.summary?.artifact_review_tokens === null || !!value.summary?.artifact_review_tokens) && <p className="agent-rsi-muted">{t('agent.pipeline.artifactTokens', { count: number(value.summary?.artifact_review_tokens) })}</p>}
    {value.summary?.codex_tokens !== undefined && <p className="agent-rsi-muted">{t('agent.pipeline.codexTokens', { count: number(value.summary.codex_tokens) })}</p>}
    <div className="agent-rsi-actions">{['running', 'queued'].includes(value.state) && <Button disabled={!!busy} onClick={async () => { await onCancel(); data.refresh() }}>{t('agent.rsi.cancel')}</Button>}<Button disabled={!!busy || ['running', 'queued', 'reviewing', 'report_queued'].includes(value.state)} onClick={onRerun}>{t('agent.pipeline.rerun')}</Button>{value.state === 'blocked' && <Button disabled={!!busy} onClick={async () => { await onRetry(); data.refresh() }}>{t('agent.pipeline.resumeReport')}</Button>}{value.issue?.url?.startsWith('https://github.com/') ? <a className="tt-act" href={value.issue.url} target="_blank" rel="noopener noreferrer">{t('agent.rsi.viewIssue')}</a> : value.artifacts.some(a => a.name === 'issue-plan.json') && <Button disabled={!!busy} onClick={async () => { await onPublish(); refresh(); data.refresh() }}>{t('agent.pipeline.publishIssue')}</Button>}</div>
    <ExperimentWorkflow stage={stage} view="workflow" onStage={setStage} onView={() => {}} states={Object.fromEntries(value.nodes.map(node => [node.node, node.state]))} tabs={false} caption={t('agent.pipeline.frozenRun')} stateLabel={state => t('agent.pipeline.nodeState.' + state)} />
    <section className="agent-rsi-section"><h4>{t('agent.experiment.stage.' + stage)}</h4><p>{t('agent.experiment.hint.' + stage)}</p><p>{t('agent.pipeline.currentState', { state: t('agent.pipeline.nodeState.' + (selected?.state || 'pending')) })}</p>
      <h4>{t('agent.pipeline.outputs')}</h4>
      {value.artifacts.filter(a => a.node === stage).length ? value.artifacts.filter(a => a.node === stage).map(artifact => <div className="agent-rsi-row" key={artifact.id}><span>{artifact.name}<small>{new Intl.NumberFormat(locale).format(artifact.bytes)} B</small></span><button type="button" className="tt-act" onClick={() => void loadFile(artifact.id)}>{t('agent.pipeline.openFile')}</button></div>) : <p className="agent-rsi-muted">{t('agent.pipeline.noOutput')}</p>}
      {failed && <p role="alert" className="agent-rsi-error">{t('agent.rsi.loadFailed')}</p>}
      {file && <div className="pipeline-artifact"><h4>{file.name}</h4>{file.name.endsWith('.md') ? <Markdown allowImages={false}>{file.text}</Markdown> : <pre>{file.text}</pre>}</div>}
      <details><summary>{t('agent.pipeline.snapshot')}</summary><pre className="pipeline-code">{JSON.stringify({ run: value.snapshot, node: selected?.config }, null, 2)}</pre></details>
      <details><summary>{t('agent.pipeline.attempts')}</summary>{attempts.map(attempt => <div className="agent-rsi-row" key={attempt.attempt}><span>{t('agent.pipeline.attempt', { count: attempt.attempt })}<small>{attempt.error_code}</small></span><span>{t('agent.pipeline.nodeState.' + attempt.state)}</span></div>)}</details>
    </section>
    <section className="agent-rsi-section"><h4>{t('agent.pipeline.recurrence')}</h4><p className="agent-rsi-muted">{t('agent.pipeline.observationHint')}</p>{value.issues.map(issue => <div className="pipeline-issue" key={issue.id}><span>{signalLabel(t, issue.code)}<small>{issue.case_id}</small></span><span data-observation={issue.status}>{t('agent.pipeline.observation.' + issue.status)}</span></div>)}{!value.issues.length && <p className="agent-rsi-muted">{t('agent.rsi.noFindings')}</p>}</section>
    <section className="agent-rsi-section"><h4>{t('agent.pipeline.caseResults')}</h4>{value.cases.map(c => <div className="pipeline-case" key={c.case_id}><span>{c.case_id}<small>{t('agent.pipeline.caseState.' + c.state)}</small></span><span>{t('agent.pipeline.caseUsage', { tokens: number(c.metrics.tokens), tools: number(c.tool_calls) })}</span><details><summary>{t('agent.pipeline.signals')}</summary>{c.signals.map(signal => <p key={signal}>{signalLabel(t, signal)}</p>)}</details></div>)}</section>
  </div>
}
