import { useEffect, useRef, useState } from 'react'
import { Button, Checkbox, Input, InputNumber, Select, Spin, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useAgentData } from './useAgentData'
import './agent-improvement.css'

type Preferences = { revision: number; enabled: boolean; timezone: string; hour: number; daily_tokens: number; daily_episodes: number; cases_per_day: number; suite_id: string; machine_ids: string[]; auto_candidates: boolean; candidate_policy: Record<string, number> }
type Comparison = { pairs: number; quality_delta: number; paired_elapsed_ratio_p50: number | null; paired_success_token_ratio_p50: number | null; eligible_for_promotion: boolean; reasons: string[]; release_blockers: string[]; strata: { layer: string; category: string; n: number; baseline_passes: number; candidate_passes: number }[] }
type Cycle = { id: string; day: string; state: string; machine_id: string; report: { comparison?: Comparison; review?: { complete: boolean; expected_trials: number; metrics_reviewed: number; logs_reviewed: number }; counts?: Record<string, { executed: number; passed: number; verified_deliveries: number }> } | null }
type Request = { id: string; machine_id: string; state: string; error_code: string | null; cycle_id: string | null }
type Research = { review_coverage?: { cycle_id: string; reviewed: number }[]; model_cost?: { total_tokens: number | null }; settings: { enabled: boolean }; actions: { id: string; kind: string; state: string; error_code: string | null }[]; improvements: { id: string; title: string; state: string }[] }
type Overview = { research?: Research; preferences: Preferences; catalog: { machines: { id: string; label: string; mode: string }[]; suites: { id: string; count: number; splits: Record<string, number> }[] }; cycles: Cycle[]; requests: Request[]; releases: { seq: number; active: string | null; history: { seq: number; release_id: string | null; action: string; created_ms: number }[] } }

export default function AgentImprovement({ node }: { node: string | null }) {
  const { t, locale } = useI18n()
  const [poll, setPoll] = useState(0)
  const data = useAgentData<Overview>('/agent/improvement', 0, poll)
  const [draft, setDraft] = useState<Preferences | null>(null), [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(''), [error, setError] = useState('')
  const [selected, setSelected] = useState<string[]>([]), [detail, setDetail] = useState('')
  const scope = useRef(node); scope.current = node
  useEffect(() => { setDraft(null); setDirty(false); setSelected([]); setDetail(''); setError('') }, [node])
  useEffect(() => { if (data.value && !dirty) setDraft({ ...data.value.preferences, cases_per_day: 60 }) }, [data.value, dirty])
  useEffect(() => {
    const active = data.value?.requests.some(r => ['queued', 'running', 'cancelling'].includes(r.state)) || data.value?.research?.actions.some(a => ['queued', 'running'].includes(a.state))
    setPoll(active ? 2000 : (data.value?.preferences.enabled || data.value?.research?.settings.enabled) ? 30000 : 0)
  }, [data.value])
  const change = (patch: Partial<Preferences>) => { setDirty(true); setDraft(value => value && ({ ...value, ...patch })) }
  const mutate = async (key: string, path: string, body?: unknown, method = 'POST') => {
    const owner = node
    setBusy(key); setError('')
    try {
      await api(method, '/agent/improvement' + path, body)
      if (scope.current === owner) { if (key === 'save') setDirty(false); data.refresh() }
    } catch (e: any) { if (scope.current === owner) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { if (scope.current === owner) setBusy('') }
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
  return <div className="agent-rsi">
    <div className="agent-rsi-summary" aria-label={t('agent.rsi.results')}>
      <div><span>{t('agent.rsi.quality')}</span><strong>{latest ? number(latest.quality_delta) : t('agent.rsi.unknown')}</strong></div>
      <div><span>{t('agent.rsi.elapsed')}</span><strong>{ratio(latest?.paired_elapsed_ratio_p50)}</strong></div>
      <div><span>{t('agent.rsi.tokens')}</span><strong>{ratio(latest?.paired_success_token_ratio_p50)}</strong></div>
    </div>
    {(error || data.failed) && <p className="agent-rsi-error" role="alert">{errorText.startsWith('agent.rsi.error.') ? t('agent.rsi.operationFailed', { code: error }) : errorText || t('agent.rsi.loadFailed')}</p>}
    <section className="agent-rsi-section">
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
        <Button type="primary" loading={busy === 'save'} disabled={!dirty || !!busy} onClick={() => mutate('save', '/preferences', draft, 'PUT')}>{t('agent.rsi.save')}</Button>
        <Button disabled={dirty || !!busy || !draft.machine_ids.length || !draft.daily_tokens} onClick={() => { void (async () => { for (const machine_id of draft.machine_ids) await mutate('run', '/requests', { machine_id, request_key: key() }) })() }}>{t('agent.rsi.run')}</Button>
        {!value.catalog.suites.length && <Button loading={busy === 'prepare'} disabled={!!busy} onClick={() => mutate('prepare', '/prepare')}>{t('agent.rsi.prepare')}</Button>}
        {!value.catalog.machines.length && <Button disabled={!!busy} onClick={() => mutate('machine', '/machines', { id: 'local-container', label: t('agent.rsi.localMachine'), mode: 'container' })}>{t('agent.rsi.addLocal')}</Button>}
      </div>
      {!draft.daily_tokens && <p className="agent-rsi-muted">{t('agent.rsi.budgetHint')}</p>}
    </section>
    {!!value.requests.length && <section className="agent-rsi-section"><h3>{t('agent.rsi.execution')}</h3>{value.requests.map(request => <div className="agent-rsi-row" key={request.id}><span>{value.catalog.machines.find(m => m.id === request.machine_id)?.label || request.machine_id}<small>{state(request.state)}{request.error_code && t('agent.rsi.failureCode', { code: request.error_code })}</small></span>{['queued', 'running'].includes(request.state) && <button type="button" className="tt-act" disabled={!!busy} onClick={() => mutate('cancel', '/requests/' + request.id + '/cancel')}>{t('agent.rsi.cancel')}</button>}</div>)}</section>}
    {value.research && (value.research.settings.enabled || !!value.research.improvements.length) && <section className="agent-rsi-section">
      <h3>{t('agent.rsi.research')}</h3>
      {!value.research.improvements.length && <p className="agent-rsi-muted">{t('agent.rsi.noFindings')}</p>}
      {value.research.improvements.map(item => <div className="agent-rsi-row" key={item.id}><span>{item.title}<small>{state(item.state)}</small></span></div>)}
      <details><summary>{t('agent.rsi.researchSteps')}</summary>{value.research.model_cost && <p className="agent-rsi-muted">{t('agent.rsi.researchTokens', { count: value.research.model_cost.total_tokens == null ? t('agent.rsi.unknown') : number(value.research.model_cost.total_tokens) })}</p>}{value.research.actions.map(action => <div className="agent-rsi-row" key={action.id}><span>{t('agent.rsi.stage.' + action.kind)}<small>{state(action.state)}{action.error_code && t('agent.rsi.failureCode', { code: action.error_code })}</small></span>{['blocked', 'waiting_budget'].includes(action.state) && <button type="button" className="tt-act" disabled={!!busy} onClick={() => mutate('resume', '/research/' + action.id + '/resume')}>{t('agent.rsi.retry')}</button>}</div>)}</details>
    </section>}
    <section className="agent-rsi-section">
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
    </section>
    <section className="agent-rsi-section"><div className="agent-rsi-heading"><h3>{t('agent.rsi.releases')}</h3>{value.releases.active && <Button disabled={!!busy} onClick={() => mutate('rollback', '/rollback', { expected_seq: value.releases.seq, request_key: key() })}>{t('agent.rsi.rollback')}</Button>}</div><p className="agent-rsi-muted">{value.releases.active ? t('agent.rsi.activeHint') : t('agent.rsi.baselineHint')}</p>{value.releases.history.map(release => <div className="agent-rsi-row" key={release.seq}><span>{t('agent.rsi.action.' + release.action)}<small>{new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(release.created_ms))}</small></span><code>{release.release_id?.slice(0, 12) || t('agent.rsi.baseline')}</code></div>)}</section>
  </div>
}
