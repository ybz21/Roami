import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Input, InputNumber, Select, Spin } from 'antd'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { pollWhileVisible } from '../../../visible-poll'
import { ChevronLeft, PencilIcon, SwarmIcon } from '../../../icons'
import MobileSubPage from '../../MobileSubPage'
import { getHashParams } from '../../../route-hash'
import OkrConfiguration, { OkrField, type SwarmOption } from './OkrConfiguration'
import { configurationOf, dailyHistory, emptyConfiguration, keyResultEvidence, projectPath, shanghaiDate, sourceObservations, type Configuration, type Workspace } from './okr-workspace'
import OkrReviewEvidence from './OkrReviewEvidence'
import './project-okr.css'

function navigate(path: string) {
  const query = getHashParams().toString()
  location.hash = '#/' + path + (query ? '?' + query : '')
}

export default function ProjectOkr({ projectId }: { projectId: string }) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [draft, setDraft] = useState<Configuration>(emptyConfiguration)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const writing = useRef(false)
  const [error, setError] = useState('')
  const [errorDetail, setErrorDetail] = useState('')
  const [conflict, setConflict] = useState(false)
  const [swarms, setSwarms] = useState<SwarmOption[]>([])
  const [swarmError, setSwarmError] = useState(false)
  const [manualMetric, setManualMetric] = useState('')
  const [date, setDate] = useState(shanghaiDate)
  const [value, setValue] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const [summary, setSummary] = useState('')
  const [actions, setActions] = useState('')
  const rootPath = '/projects/' + encodeURIComponent(projectId) + '/okr'
  const observationSelection = useRef({ metricId: '', date })
  const hasDraft = editing || value !== null || note !== '' || summary !== '' || actions !== ''
    || manualMetric !== observationSelection.current.metricId || date !== observationSelection.current.date
  const live = useRef({ loaded, blocked: hasDraft || busy || conflict, workspace })
  live.current = { loaded, blocked: hasDraft || busy || conflict, workspace }
  const workspaceRead = useRef<{ controller: AbortController; promise: Promise<{ data: Workspace | null }> } | null>(null)
  const readWorkspace = useCallback((signal?: AbortSignal) => {
    if (workspaceRead.current && !workspaceRead.current.controller.signal.aborted) return workspaceRead.current.promise
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) controller.abort()
    const request = { controller, promise: null as Promise<{ data: Workspace | null }> | null }
    request.promise = api('GET', rootPath, undefined, { signal: controller.signal }).then(response => {
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError')
      return response
    }).finally(() => {
      signal?.removeEventListener('abort', abort)
      if (workspaceRead.current === request) workspaceRead.current = null
    })
    workspaceRead.current = request
    return request.promise
  }, [rootPath])
  useEffect(() => () => workspaceRead.current?.controller.abort(), [readWorkspace])
  const loadSwarms = useCallback(async () => {
    try {
      const response = await api('GET', '/swarms')
      const rows = Array.isArray(response) ? response : response.data || []
      setSwarms(rows.map((s: { id: string; name: string }) => ({ id: s.name, name: s.name })))
      setSwarmError(false)
    } catch { setSwarmError(true) }
  }, [])
  useEffect(() => { void loadSwarms() }, [loadSwarms])
  useEffect(() => {
    const controller = new AbortController()
    readWorkspace(controller.signal).then(response => {
      if (controller.signal.aborted) return
      setWorkspace(response.data)
      observationSelection.current.metricId = response.data?.metrics.find(m => m.source === 'manual')?.id || ''
      setManualMetric(observationSelection.current.metricId)
      setDraft(response.data ? configurationOf(response.data) : emptyConfiguration())
      setEditing(!response.data)
      setLoaded(true)
    }).catch(e => { if (!controller.signal.aborted) { setError('okr.loadFailed'); setErrorDetail(e.message) } })
    return () => controller.abort()
  }, [readWorkspace])
  useEffect(() => {
    if (!loaded) return
    let initialTick = !document.hidden
    const poll = pollWhileVisible(async signal => {
      // The initial read already populated this page; subsequent ticks use live draft guards.
      if (initialTick) { initialTick = false; return }
      if (live.current.blocked || writing.current) return
      const response = await readWorkspace(signal)
      if (signal.aborted || live.current.blocked || writing.current) return
      const next = response.data
      if (next && next.revision > (live.current.workspace?.revision || 0)) setWorkspace(next)
    }, 30_000)
    return poll.stop
  }, [loaded, readWorkspace])

  const reload = async () => {
    if (writing.current) return
    setBusy(true)
    try {
      const response = await readWorkspace()
      setWorkspace(response.data)
      if (!loaded) { observationSelection.current.metricId = response.data?.metrics.find(m => m.source === 'manual')?.id || ''; setManualMetric(observationSelection.current.metricId); setDraft(response.data ? configurationOf(response.data) : emptyConfiguration()); setEditing(!response.data) }
      setLoaded(true); setConflict(false); setError(''); setErrorDetail('')
    } catch (e) { setError('okr.loadFailed'); setErrorDetail((e as Error).message) }
    finally { setBusy(false) }
  }
  const mutate = async (method: string, suffix: string, body: object, success?: () => void) => {
    if (writing.current || conflict) return
    workspaceRead.current?.controller.abort()
    writing.current = true; setBusy(true); setError(''); setErrorDetail('')
    try {
      const response = await api(method, rootPath + suffix, { ...body, revision: workspace?.revision || 0 })
      setWorkspace(response.data)
      success?.()
    } catch (e) {
      const err = e as Error & { status?: number }
      if (err.status === 409) { setConflict(true); setError('okr.conflict') }
      else setError(err.status === 502 ? 'okr.collectFailed' : err.status === 400 ? 'okr.invalidRequest' : 'okr.writeFailed')
      setErrorDetail(err.message)
    } finally { writing.current = false; setBusy(false) }
  }
  const number = (n: number) => new Intl.NumberFormat(locale, { maximumSignificantDigits: 21 }).format(n)
  const day = (date: string) => new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Shanghai', dateStyle: 'medium' }).format(new Date(date + (date.length === 10 ? 'T00:00:00+08:00' : '')))
  const timestamp = (date: string) => new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(date))
  const save = () => {
    if (!draft.objective.trim() || !draft.metrics.length || !draft.keyResults.length || draft.startDate > draft.endDate || draft.metrics.some(m => !m.name.trim() || (m.source === 'github' && (!/^[\w.-]+\/[\w.-]+$/.test(m.repo || '') || !m.field))) || draft.keyResults.some(k => !k.title.trim() || !Number.isFinite(k.target) || !draft.metrics.some(m => m.id === k.metricId) || k.dueDate < draft.startDate || k.dueDate > draft.endDate)) {
      setError('okr.invalidConfiguration'); return
    }
    void mutate('PUT', '', configurationOf(draft), () => { setEditing(false); if (!workspace) { observationSelection.current.metricId = draft.metrics.find(m => m.source === 'manual')?.id || ''; setManualMetric(observationSelection.current.metricId) } })
  }
  const back = () => navigate(projectPath(workspace?.projectId || projectId))
  const manualMetrics = workspace?.metrics.filter(m => m.source === 'manual') || []
  const selectedManual = manualMetrics.find(m => m.id === manualMetric)
  const hasGithub = workspace?.metrics.some(m => m.source === 'github')
  const retiredObservations = (workspace?.observations || []).filter(o => !workspace.metrics.some(m => m.id === o.metricId))
  const content = <div className="okr-page" data-mobile-refresh-scroll>
    {!phone && <header className="tt-pagehead"><h2>{t('okr.title')}</h2><div className="acts"><Button icon={<ChevronLeft />} onClick={back}>{t('okr.backProject')}</Button></div></header>}
    {error && <div className="okr-error" role="alert">
      <p>{t(error)}</p>
      {(conflict || !loaded) && <Button disabled={busy} onClick={() => void reload()}>{t(conflict ? 'okr.loadLatest' : 'inbox.retry')}</Button>}
      {errorDetail && <details><summary>{t('okr.errorDetails')}</summary><p>{errorDetail}</p></details>}
    </div>}
    {!loaded && !error && <Spin />}
    {loaded && <>
      {workspace && <section className="okr-section">
        <div className="okr-section-head"><h2>{workspace.objective}</h2>{!editing && <Button icon={<PencilIcon />} onClick={() => { setDraft(configurationOf(workspace)); setEditing(true) }}>{t('okr.edit')}</Button>}</div>
        <p className="okr-muted">{t('okr.period', { start: day(workspace.startDate), end: day(workspace.endDate) })}</p>
        <p className="okr-muted">{t(workspace.autoCollect ? 'okr.autoEnabled' : 'okr.autoDisabled')}</p>
        {workspace.swarm && <a className="tt-act okr-swarm" href={'#/swarm/' + encodeURIComponent(workspace.swarm) + (getHashParams().toString() ? '?' + getHashParams().toString() : '')}><SwarmIcon />{t('okr.openSwarm')}</a>}
      </section>}
      {editing && <section className="okr-section"><OkrConfiguration value={draft} onChange={setDraft} onSave={save} onCancel={workspace ? () => setEditing(false) : undefined} busy={busy || conflict} swarms={swarms} swarmError={swarmError} onLoadSwarms={() => void loadSwarms()} /></section>}
      {workspace && <>
        <section className="okr-section"><h3>{t('okr.keyResults')}</h3>
          {workspace.keyResults.map(kr => {
            const metric = workspace.metrics.find(m => m.id === kr.metricId)
            const { baseline, latest, change } = keyResultEvidence(workspace, kr)
            return <article className="okr-result" key={kr.id}>
              <h4>{kr.title}</h4>
              <p>{t('okr.krTarget', { horizon: t('okr.horizon.' + kr.horizon), mode: t('okr.mode.' + kr.mode), target: number(kr.target), unit: metric?.unit || '', date: day(kr.dueDate) })}</p>
              {latest ? <dl className="okr-evidence">
                <div><dt>{t('okr.current', { metric: metric?.name || '' })}</dt><dd>{number(latest.value)} {metric?.unit}</dd></div>
                <div><dt>{t('okr.baseline', { date: day(baseline.date) })}</dt><dd>{number(baseline.value)}</dd></div>
                <div><dt>{t('okr.periodChange')}</dt><dd>{number(change)}</dd></div>
              </dl> : <p className="okr-muted">{t('okr.noEvidence')}</p>}
            </article>
          })}
        </section>
        <section className="okr-section"><h3>{t('okr.observations')}</h3>
          {hasGithub && <div className="okr-actions"><Button loading={busy} disabled={busy || conflict} onClick={() => void mutate('POST', '/collect', {})}>{t('okr.collect')}</Button><span className="okr-muted">{t('okr.collectHint')}</span></div>}
          {!!manualMetrics.length && <form onSubmit={e => { e.preventDefault(); if (selectedManual && value !== null && Number.isFinite(value)) void mutate('POST', '/observations', { metricId: selectedManual.id, date, value, note }, () => { observationSelection.current = { metricId: manualMetric, date }; setValue(null); setNote('') }) }}>
            <fieldset disabled={busy || conflict}>
              <div className="okr-grid">
                <OkrField label={t('okr.metric')}><Select disabled={busy || conflict} aria-label={t('okr.metric')} value={selectedManual?.id} options={manualMetrics.map(m => ({ value: m.id, label: m.name }))} onChange={setManualMetric} /></OkrField>
                <OkrField label={t('okr.date')}><input type="date" required min={workspace.startDate} max={workspace.endDate < shanghaiDate() ? workspace.endDate : shanghaiDate()} value={date} onChange={e => setDate(e.target.value)} /></OkrField>
                <OkrField label={t('okr.value')}><InputNumber aria-label={t('okr.value')} required value={value} onChange={v => setValue(v === null ? null : Number(v))} /></OkrField>
              </div>
              <OkrField label={t('okr.note')}><Input value={note} onChange={e => setNote(e.target.value)} /></OkrField>
              <Button htmlType="submit" disabled={busy || conflict || value === null || !selectedManual} loading={busy}>{t('okr.record')}</Button>
            </fieldset>
          </form>}
        </section>
        <section className="okr-section"><h3>{t('okr.history')}</h3>
          {workspace.metrics.map(metric => {
            const current = sourceObservations(workspace, metric)
            const rows = dailyHistory(current)
            const currentIds = new Set(current.map(o => o.id))
            const all = (workspace.observations || []).filter(o => o.metricId === metric.id)
            const old = all.filter(o => !currentIds.has(o.id))
            return <article className="okr-history" key={metric.id}>
              <h4>{metric.name}</h4>
              <p className="okr-muted">{metric.source === 'github' ? t('okr.githubSource', { repo: metric.repo || '', field: t('okr.github.' + metric.field) }) : t('okr.source.manual')}</p>
              {!rows.length && <p className="okr-muted">{t('okr.noEvidence')}</p>}
              {rows.map(row => <div className="okr-day" key={row.date}>
                <div className="okr-day-head"><time>{day(row.date)}</time><strong>{number(row.latest.value)} {metric.unit}</strong><span>{row.delta === null ? t('okr.deltaUnknown') : t('okr.dailyDelta', { value: number(row.delta) })}</span></div>
                <details><summary>{t('okr.versions', { count: number(row.versions.length) })}</summary>
                  {row.versions.slice().reverse().map(o => <div className="okr-version" key={o.id}><time>{timestamp(o.capturedAt)}</time><span>{number(o.value)} {metric.unit}</span><span>{t('okr.source.' + o.source)}</span>{o.note && <p>{o.note}</p>}</div>)}
                </details>
              </div>)}
              {!!old.length && <details><summary>{t('okr.previousSources')}</summary>{old.slice().reverse().map(o => <div className="okr-version" key={o.id}><time>{day(o.date)}</time><span>{number(o.value)}</span><code>{o.sourceKey}</code><time>{timestamp(o.capturedAt)}</time>{o.note && <p>{o.note}</p>}</div>)}</details>}
            </article>
          })}
          {!!retiredObservations.length && <details><summary>{t('okr.retiredMetrics')}</summary>{retiredObservations.slice().reverse().map(o => <div className="okr-version" key={o.id}><span>{t('okr.retiredMetric', { id: o.metricId })}</span><time>{day(o.date)}</time><span>{number(o.value)}</span><code>{o.sourceKey}</code><time>{timestamp(o.capturedAt)}</time>{o.note && <p>{o.note}</p>}</div>)}</details>}
        </section>
        <section className="okr-section"><h3>{t('okr.reviews')}</h3>
          <form onSubmit={e => { e.preventDefault(); if (summary.trim()) void mutate('POST', '/reviews', { summary, actions }, () => { setSummary(''); setActions('') }) }}>
            <fieldset disabled={busy || conflict}>
              <OkrField label={t('okr.reviewSummary')}><Input.TextArea required value={summary} onChange={e => setSummary(e.target.value)} autoSize={{ minRows: 3, maxRows: 8 }} /></OkrField>
              <OkrField label={t('okr.reviewActions')}><Input.TextArea value={actions} onChange={e => setActions(e.target.value)} autoSize={{ minRows: 2, maxRows: 8 }} /></OkrField>
              <Button htmlType="submit" disabled={busy || conflict || !summary.trim()} loading={busy}>{t('okr.submitReview')}</Button>
              <p className="okr-muted">{t('okr.reviewHint')}</p>
            </fieldset>
          </form>
          {!(workspace.reviews || []).length && <p className="okr-muted">{t('okr.noReviews')}</p>}
          {(workspace.reviews || []).slice().reverse().map(review => <article className="okr-review" key={review.id}><p>{review.summary}</p>{review.actions && <p>{review.actions}</p>}<p className="okr-muted">{t('okr.reviewEvidence', { date: timestamp(review.date), revision: number(review.evidenceRevision) })}</p>{workspace.revision > review.evidenceRevision + 1 && <p className="okr-muted">{t('okr.reviewUpdated')}</p>}<OkrReviewEvidence projectId={workspace.projectId} reviewId={review.id} /></article>)}
        </section>
      </>}
    </>}
  </div>
  return phone ? <MobileSubPage title={t('okr.title')} onBack={back} manageHistory={false} keepBottomNav>{content}</MobileSubPage> : content
}
