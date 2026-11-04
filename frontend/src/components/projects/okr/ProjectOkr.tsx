import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Button, Input, InputNumber, Select, Spin, Tabs, Segmented } from 'antd'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { pollWhileVisible } from '../../../visible-poll'
import { BotIcon, ChevronLeft, PencilIcon } from '../../../icons'
import MobileSubPage from '../../MobileSubPage'
import { getHashParams } from '../../../route-hash'
import { loadSwarmDirectory } from '../../swarm/swarm-directory'
import OkrConfiguration, { OkrField, type SwarmOption } from './OkrConfiguration'
import { configurationOf, dailyHistory, emptyConfiguration, projectPath, resultOverview, shanghaiDate, sourceObservations, workspaceUpdated, type Configuration, type Workspace } from './okr-workspace'
import OkrReviewEvidence from './OkrReviewEvidence'
import OkrResult from './OkrResult'
import OkrDashboard from './OkrDashboard'
import OkrInitiatives from './OkrInitiatives'
import OkrCurrentStatus from './OkrCurrentStatus'
import OkrTeamMemory from './OkrTeamMemory'
import { lazyRetry } from '../../lazy-retry'
import './project-okr.css'
import './okr-dashboard.css'
const Swarm = lazyRetry(() => import('../../swarm/Swarm'))
const OkrMainChat = lazyRetry(() => import('./OkrMainChat'))
const OkrProjectFiles = lazyRetry(() => import('./OkrProjectFiles'))

function navigate(path: string) {
  const query = getHashParams().toString()
  location.hash = '#/' + path + (query ? '?' + query : '')
}

export default function ProjectOkr({ projectId, projectName, projectDir, fromOverview = false, onSession = () => {} }: { projectId: string; projectName?: string; projectDir?: string; fromOverview?: boolean; onSession?: (id: string) => void }) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [draft, setDraft] = useState<Configuration>(emptyConfiguration)
  const [editing, setEditing] = useState(false)
  const [panel, setPanel] = useState('overview')
  const [mainPanel, setMainPanel] = useState('board')
  const [fileRequest, setFileRequest] = useState<{ path: string; nonce: number }>()
  const [chatting, setChatting] = useState(false)
  const [incoming, setIncoming] = useState<Workspace | null>(null)
  const [busy, setBusy] = useState(false)
  const writing = useRef(false)
  const builderSeed = useRef('')
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
  const [memoryDraft, setMemoryDraft] = useState(false)
  const rootPath = '/projects/' + encodeURIComponent(projectId) + '/okr'
  const observationSelection = useRef({ metricId: '', date })
  const hasDraft = editing || memoryDraft || value !== null || note !== '' || summary !== '' || actions !== ''
    || manualMetric !== observationSelection.current.metricId || date !== observationSelection.current.date
  const live = useRef({ loaded, blocked: hasDraft || busy || conflict, workspace, emptyBuilder: false })
  live.current = { loaded, blocked: hasDraft || busy || conflict, workspace, emptyBuilder: !workspace && editing && builderSeed.current === JSON.stringify(configurationOf(draft)) }
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
      const rows = await loadSwarmDirectory()
      setSwarms(rows.filter(s => !s.archived).map(s => ({ id: s.id, name: s.name })))
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
      const initialDraft = response.data ? configurationOf(response.data) : emptyConfiguration(); builderSeed.current = JSON.stringify(initialDraft); setDraft(initialDraft)
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
      if (workspaceUpdated(live.current.workspace, next)) setWorkspace(next)
    }, 30_000)
    return poll.stop
  }, [loaded, readWorkspace])

  const reload = async () => {
    if (writing.current) return
    setBusy(true)
    try {
      const response = await readWorkspace()
      setWorkspace(response.data)
      if (!loaded) { observationSelection.current.metricId = response.data?.metrics.find(m => m.source === 'manual')?.id || ''; setManualMetric(observationSelection.current.metricId); const initialDraft = response.data ? configurationOf(response.data) : emptyConfiguration(); builderSeed.current = JSON.stringify(initialDraft); setDraft(initialDraft); setEditing(!response.data) }
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
      const err = e as Error & { status?: number; apiError?: { code?: string } }
      if (err.status === 409 && (err.message === 'OKR_FILES_PENDING' || err.apiError?.code === 'OKR_FILES_PENDING')) {
        setError('okr.filesPendingConflict')
        setWorkspace(current => current?.projectFiles ? { ...current, projectFiles: { ...current.projectFiles, pendingChanges: true } } : current)
      } else if (err.status === 409) { setConflict(true); setError('okr.conflict') }
      else setError(err.status === 502 ? 'okr.collectFailed' : err.status === 400 ? 'okr.invalidRequest' : 'okr.writeFailed')
      setErrorDetail(err.message)
    } finally { writing.current = false; setBusy(false) }
  }
  const number = (n: number) => new Intl.NumberFormat(locale, { maximumSignificantDigits: 21 }).format(n)
  const day = (date: string) => new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Shanghai', dateStyle: 'medium' }).format(new Date(date + (date.length === 10 ? 'T00:00:00+08:00' : '')))
  const timestamp = (date: string) => new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(date))
  const save = () => {
    if (!draft.objective.trim() || !draft.metrics.length || !draft.keyResults.length || draft.startDate > draft.endDate || draft.metrics.some(m => !m.name.trim() || (m.source === 'github' && (!/^[\w.-]+\/[\w.-]+$/.test(m.repo || '') || !m.field))) || draft.keyResults.some(k => !k.title.trim() || !Number.isFinite(k.target) || !draft.metrics.some(m => m.id === k.metricId) || k.dueDate < draft.startDate || k.dueDate > draft.endDate) || (draft.initiatives || []).some(item => !item.title.trim() || !item.channel.trim() || item.keyResultIds.some(id => !draft.keyResults.some(kr => kr.id === id)))) {
      setError('okr.invalidConfiguration'); return
    }
    void mutate('PUT', '', configurationOf(draft), () => { setEditing(false); if (!workspace) { observationSelection.current.metricId = draft.metrics.find(m => m.source === 'manual')?.id || ''; setManualMetric(observationSelection.current.metricId) } })
  }
  const back = () => navigate(fromOverview ? 'okr' : projectPath(workspace?.projectId || projectId))
  const title = projectName ? t('okr.projectTitle', { name: projectName }) : t('okr.title')
  const manualMetrics = workspace?.metrics.filter(m => m.source === 'manual') || []
  const selectedManual = manualMetrics.find(m => m.id === manualMetric)
  const hasGithub = workspace?.metrics.some(m => m.source === 'github')
  const retiredObservations = (workspace?.observations || []).filter(o => !workspace.metrics.some(m => m.id === o.metricId))
  const results = workspace?.keyResults.map(kr => resultOverview(workspace, kr)) || []
  const applyDiscussion = (next: Workspace) => {
    setWorkspace(next); setDraft(configurationOf(next)); setEditing(false); setIncoming(null); setConflict(false)
    if (!workspace) { observationSelection.current.metricId = next.metrics.find(metric => metric.source === 'manual')?.id || ''; setManualMetric(observationSelection.current.metricId) }
  }
  const refreshDiscussion = async () => {
    try {
      const { data: next } = await readWorkspace()
      if (!workspaceUpdated(live.current.workspace, next)) return
      const emptyBuilder = live.current.emptyBuilder
      if (live.current.blocked && !emptyBuilder) setIncoming(current => current && current.revision > next.revision ? current : next)
      else applyDiscussion(next)
    } catch (e) { setError('okr.loadFailed'); setErrorDetail((e as Error).message) }
  }
  const openProjectFile = (relative?: string) => {
    if (projectDir && workspace?.projectFiles && relative) setFileRequest({ path: projectDir.replace(/\/$/, '') + '/' + workspace.projectFiles.root + '/' + relative, nonce: Date.now() })
    setMainPanel('files')
  }
  const configureTeam = () => {
    if (workspace && !editing) { setDraft(configurationOf(workspace)); setEditing(true) }
    setMainPanel('board'); setPanel('overview')
  }
  const content = <div className="okr-detail-layout"><div className="okr-page okr-dashboard" data-view={mainPanel} data-mobile-refresh-scroll>
    {!phone && <header className="tt-pagehead"><h2>{title}</h2><div className="acts"><Button icon={<ChevronLeft />} onClick={back}>{t(fromOverview ? 'okr.allObjectives' : 'okr.backProject')}</Button></div></header>}
    {error && <div className="okr-error" role="alert">
      <p>{t(error)}</p>
      {(conflict || !loaded || error === 'okr.loadFailed') && <Button disabled={busy} onClick={() => void reload()}>{t(conflict ? 'okr.loadLatest' : 'inbox.retry')}</Button>}
      {error === 'okr.filesPendingConflict' && <div className="okr-actions"><Button disabled={busy} onClick={() => openProjectFile('okr.json')}>{t('okr.tab.files')}</Button><Button loading={busy} disabled={busy} onClick={() => void mutate('POST', '/sync', {})}>{t('okr.confirmFiles')}</Button></div>}
      {errorDetail && <details><summary>{t('okr.errorDetails')}</summary><p>{errorDetail}</p></details>}
    </div>}
    {!loaded && !error && <Spin />}
    {incoming && <div className="okr-update" role="status"><span>{t('okr.discussionUpdated')}</span><Button onClick={() => { void readWorkspace().then(response => { if (response.data) applyDiscussion(response.data) }).catch(() => setError('okr.loadFailed')) }}>{t('okr.adoptUpdate')}</Button></div>}
    {loaded && <>
      <Tabs className="okr-work-tabs" activeKey={mainPanel} onChange={setMainPanel} items={[
        { key: 'board', label: t('okr.tab.board'), children: <>
          <div className="okr-board-toolbar"><Segmented value={panel} onChange={value => setPanel(String(value))} options={[{ value: 'overview', label: t('okr.tab.okr') }, { value: 'data', label: t('okr.tab.dashboard') }, { value: 'review', label: t('okr.tab.status') }]} /><Button type="primary" icon={<BotIcon />} onClick={() => setChatting(true)}>{t('okr.chatOpen')}</Button></div>
          <Tabs className="okr-inner-tabs" activeKey={panel} onChange={setPanel} tabBarStyle={{ display: 'none' }} items={[
        { key: 'overview', label: t('okr.tab.okr'), forceRender: true, children: editing ? <section className="okr-section"><OkrConfiguration value={draft} onChange={setDraft} onSave={save} onCancel={workspace ? () => setEditing(false) : undefined} busy={busy || conflict} swarms={swarms} swarmError={swarmError} onLoadSwarms={() => void loadSwarms()} /></section> : workspace && <>
          <section className="okr-objective-head">
            <div><h2>{workspace.objective}</h2><div className="okr-goal-meta"><span>{t('okr.period', { start: day(workspace.startDate), end: day(workspace.endDate) })}</span></div></div>
            <Button icon={<PencilIcon />} onClick={() => { setDraft(configurationOf(workspace)); setEditing(true) }}>{t('okr.edit')}</Button>
          </section>
          <section className="okr-board"><h3>{t('okr.keyResults')}</h3><div className="okr-results">{results.map(kr => <OkrResult key={kr.id} result={kr} />)}</div></section>
          <OkrInitiatives workspace={workspace} />
          {workspace.projectFiles && <section className="okr-section"><div className="okr-section-head"><div><h3>{t('okr.projectConfiguration')}</h3><p className="okr-muted">{workspace.projectFiles.root}</p></div><Button onClick={() => openProjectFile('okr.json')}>{t('okr.tab.files')}</Button></div>{workspace.projectFiles.pendingChanges && <div className="okr-actions"><span>{t('okr.pendingFiles')}</span><Button loading={busy} disabled={busy || conflict} onClick={() => void mutate('POST', '/sync', {})}>{t('okr.confirmFiles')}</Button></div>}</section>}
        </> },
        { key: 'data', label: t('okr.tab.dashboard'), forceRender: true, children: workspace ? <>
          <OkrDashboard workspace={workspace} onReview={() => setPanel('review')} onConfigure={() => { setDraft(configurationOf(workspace)); setEditing(true); setPanel('overview') }} onSource={workspace.projectFiles ? metricId => openProjectFile('connectors/' + metricId + '/connector.json') : undefined} />
          <p className="okr-muted">{t(workspace.autoCollect ? 'okr.autoEnabled' : 'okr.autoDisabled')}</p>
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
        </> : <p className="okr-muted">{t('okr.confirmBeforeData')}</p> },
        { key: 'review', label: t('okr.tab.status'), forceRender: true, children: workspace ? <>
        {panel === 'review' && mainPanel === 'board' && <OkrCurrentStatus swarm={workspace.swarm} onActivities={() => setMainPanel('activities')} onConfigure={configureTeam} />}
        <OkrTeamMemory workspace={workspace} onUpdated={next => setWorkspace(current => current && current.revision > next.revision ? current : next)} onFiles={() => openProjectFile(workspace.projectFiles?.teamMemoryFile)} onDraftChange={setMemoryDraft} />
        <section className="okr-section"><h3>{t('okr.reviews')}</h3>

          {!(workspace.reviews || []).length && <p className="okr-muted">{t('okr.noReviews')}</p>}
          {(workspace.reviews || []).slice().reverse().map(review => <article className="okr-review" key={review.id}><p>{review.summary}</p>{review.actions && <p>{review.actions}</p>}<p className="okr-muted">{t('okr.reviewEvidence', { date: timestamp(review.date), revision: number(review.evidenceRevision) })}</p>{workspace.revision > review.evidenceRevision + 1 && <p className="okr-muted">{t('okr.reviewUpdated')}</p>}<OkrReviewEvidence projectId={workspace.projectId} reviewId={review.id} /></article>)}
          <form onSubmit={e => { e.preventDefault(); if (summary.trim()) void mutate('POST', '/reviews', { summary, actions }, () => { setSummary(''); setActions('') }) }}>
            <fieldset disabled={busy || conflict}>
              <OkrField label={t('okr.reviewSummary')}><Input.TextArea required value={summary} onChange={e => setSummary(e.target.value)} autoSize={{ minRows: 3, maxRows: 8 }} /></OkrField>
              <OkrField label={t('okr.reviewActions')}><Input.TextArea value={actions} onChange={e => setActions(e.target.value)} autoSize={{ minRows: 2, maxRows: 8 }} /></OkrField>
              <Button htmlType="submit" disabled={busy || conflict || !summary.trim()} loading={busy}>{t('okr.submitReview')}</Button>
              <p className="okr-muted">{t('okr.reviewHint')}</p>
            </fieldset>
          </form>
        </section>
        </> : <p className="okr-muted">{t('okr.confirmBeforeStatus')}</p> },
          ]} />
        </> },
        { key: 'activities', label: t('okr.tab.activities'), children: mainPanel === 'activities' ? workspace?.swarm ? <div className="okr-activities"><Suspense fallback={<Spin />}><Swarm key={workspace.swarm} embedded initialSwarm={workspace.swarm} openTerm={onSession} onNav={() => setMainPanel('board')} {...{ projectId: workspace.projectId, onManage: configureTeam }} /></Suspense></div> : <div className="okr-empty"><p>{t('okr.noSwarm')}</p><Button onClick={configureTeam}>{t('okr.edit')}</Button></div> : null },
        { key: 'files', label: t('okr.tab.files'), children: <Suspense fallback={<Spin />}><OkrProjectFiles key={projectDir} dir={projectDir} bundleRoot={workspace?.projectFiles?.root} active={mainPanel === 'files'} openRequest={fileRequest} /></Suspense> },
      ]} />
    </>}
  </div>
    {chatting && <Suspense fallback={<Spin />}><OkrMainChat projectId={projectId} projectDir={projectDir} workspace={workspace} draft={draft} onUpdated={() => { void refreshDiscussion() }} onClose={() => { setChatting(false); void refreshDiscussion() }} /></Suspense>}
  </div>
  return phone ? <MobileSubPage title={title} onBack={back} manageHistory={false} keepBottomNav>{content}</MobileSubPage> : content
}
