import BackButton from '../../BackButton'
import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Button, Spin, Tabs } from 'antd'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { pollWhileVisible } from '../../../visible-poll'
import { BotIcon, PencilIcon } from '../../../icons'
import MobileSubPage from '../../MobileSubPage'
import { clearOkrMessageReference, readOkrMessageReference } from '../../agent/notification-destination'
import { getHashParams } from '../../../route-hash'
import { loadSwarmDirectory } from '../../swarm/swarm-directory'
import OkrConfiguration, { type SwarmOption } from './OkrConfiguration'
import { configurationOf, emptyConfiguration, projectPath, shanghaiDate, workspaceUpdated, type Configuration, type Workspace } from './okr-workspace'
import OkrDashboard from './OkrDashboard'
import OkrGoalMap from './OkrGoalMap'
import { useOkrView } from './okr-view'
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
  const { phone, size } = useLayout()
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [draft, setDraft] = useState<Configuration>(emptyConfiguration)
  const [editing, setEditing] = useState(false)
  const { mainPanel, setMainPanel } = useOkrView(projectId)
  const [fileRequest, setFileRequest] = useState<{ path: string; nonce: number }>()
  const reference = readOkrMessageReference()
  const [chatting, setChatting] = useState(!!reference)
  const [teamMainRequest, setTeamMainRequest] = useState('')
  useEffect(() => { if (reference) { if (mainPanel === 'activities') { setChatting(false); setTeamMainRequest(crypto.randomUUID()) } else setChatting(true) } }, [reference?.conversationId, reference?.messageId, mainPanel])
  const [incoming, setIncoming] = useState<Workspace | null>(null)
  const [busy, setBusy] = useState(false)
  const writing = useRef(false)
  const builderSeed = useRef('')
  const [error, setError] = useState('')
  const [errorDetail, setErrorDetail] = useState('')
  const [conflict, setConflict] = useState(false)
  const [swarms, setSwarms] = useState<SwarmOption[]>([])
  const [swarmError, setSwarmError] = useState(false)
  const rootPath = '/projects/' + encodeURIComponent(projectId) + '/okr'
  const hasDraft = editing
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
      if (!loaded) { const initialDraft = response.data ? configurationOf(response.data) : emptyConfiguration(); builderSeed.current = JSON.stringify(initialDraft); setDraft(initialDraft); setEditing(!response.data) }
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
  const day = (date: string) => new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Shanghai', dateStyle: 'medium' }).format(new Date(date + 'T00:00:00+08:00'))
  const save = () => {
    if (!draft.objective.trim() || !draft.metrics.length || !draft.keyResults.length || draft.startDate > draft.endDate || draft.metrics.some(m => !m.name.trim() || (m.source === 'github' && (!/^[\w.-]+\/[\w.-]+$/.test(m.repo || '') || !m.field))) || draft.keyResults.some(k => !k.title.trim() || !Number.isFinite(k.target) || !draft.metrics.some(m => m.id === k.metricId) || k.dueDate < draft.startDate || k.dueDate > draft.endDate) || (draft.initiatives || []).some(item => !item.title.trim() || !item.channel.trim() || item.keyResultIds.some(id => !draft.keyResults.some(kr => kr.id === id)))) {
      setError('okr.invalidConfiguration'); return
    }
    void mutate('PUT', '', configurationOf(draft), () => setEditing(false))
  }
  const back = () => navigate(fromOverview ? 'okr' : projectPath(workspace?.projectId || projectId))
  const title = projectName ? t('okr.projectTitle', { name: projectName }) : t('okr.title')
  const applyDiscussion = (next: Workspace) => {
    setWorkspace(next); setDraft(configurationOf(next)); setEditing(false); setIncoming(null); setConflict(false)
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
    setMainPanel('okr')
  }
  const openMain = () => {
    if (mainPanel === 'activities' && workspace?.swarm) { setChatting(false); setTeamMainRequest(crypto.randomUUID()) }
    else setChatting(true)
  }
  const selectPanel = (next: string) => {
    if (next === 'activities') { setChatting(false); setTeamMainRequest(crypto.randomUUID()) }
    setMainPanel(next)
  }
  const content = <div className="okr-detail-layout"><div className="okr-page okr-dashboard" data-view={mainPanel} data-dashboard={workspace?.dashboard?.html ? 'html' : 'widgets'} data-mobile-refresh-scroll>
    {!phone && <header className="tt-pagehead"><div className="okr-page-identity"><BackButton label={t(fromOverview ? 'okr.allObjectives' : 'okr.backProject')} onClick={back} /><h2>{title}</h2></div></header>}
    {error && <div className="okr-error" role="alert">
      <p>{t(error)}</p>
      {(conflict || !loaded || error === 'okr.loadFailed') && <Button disabled={busy} onClick={() => void reload()}>{t(conflict ? 'okr.loadLatest' : 'inbox.retry')}</Button>}
      {error === 'okr.filesPendingConflict' && <div className="okr-actions"><Button disabled={busy} onClick={() => openProjectFile('okr.json')}>{t('okr.tab.files')}</Button><Button loading={busy} disabled={busy} onClick={() => void mutate('POST', '/sync', {})}>{t('okr.confirmFiles')}</Button></div>}
      {errorDetail && <details><summary>{t('okr.errorDetails')}</summary><p>{errorDetail}</p></details>}
    </div>}
    {!loaded && !error && <Spin />}
    {incoming && <div className="okr-update" role="status"><span>{t('okr.discussionUpdated')}</span><Button onClick={() => { void readWorkspace().then(response => { if (response.data) applyDiscussion(response.data) }).catch(() => setError('okr.loadFailed')) }}>{t('okr.adoptUpdate')}</Button></div>}
    {loaded && <>
      <Tabs className="okr-work-tabs" tabBarExtraContent={workspace?.swarm ? undefined : { right: <Button type="primary" icon={<BotIcon />} aria-label={t('okr.chatOpen')} onClick={openMain}>{!phone && t('okr.chatOpen')}</Button> }} activeKey={mainPanel} onChange={selectPanel} items={[
        { key: 'okr', label: t('okr.tab.okr'), forceRender: true, children: editing ? <section className="okr-section"><OkrConfiguration value={draft} onChange={setDraft} onSave={save} onCancel={workspace ? () => setEditing(false) : undefined} busy={busy || conflict} swarms={swarms} swarmError={swarmError} onLoadSwarms={() => void loadSwarms()} /></section> : workspace && <>
          <section className="okr-objective-head"><div><p className="okr-goal-meta">{t('okr.period', { start: day(workspace.startDate), end: day(workspace.endDate) })}</p></div><Button icon={<PencilIcon />} onClick={() => { setDraft(configurationOf(workspace)); setEditing(true) }}>{t('okr.edit')}</Button></section>
          <OkrGoalMap workspace={workspace} />
        </> },
        { key: 'data', label: t('okr.tab.dashboard'), children: workspace ? <OkrDashboard workspace={workspace} active={mainPanel === 'data' && (!chatting || (!phone && size === 'large'))} onRefresh={() => { void refreshDiscussion() }} /> : <p className="okr-muted">{t('okr.confirmBeforeData')}</p> },
        { key: 'activities', label: t('okr.tab.activities'), children: mainPanel === 'activities' ? workspace?.swarm ? <div className="okr-activities"><Suspense fallback={<Spin />}><Swarm key={workspace.swarm} roles={workspace.team?.roles} embedded initialSwarm={workspace.swarm} openTerm={onSession} mainRequest={teamMainRequest} onRecipientChange={recipient => { if (recipient !== 'main' && reference) clearOkrMessageReference() }} renderMain={cid => <Suspense fallback={<Spin />}><OkrMainChat onSession={onSession} embedded expectedConversationId={cid} reference={reference} onClearReference={clearOkrMessageReference} projectId={projectId} projectDir={projectDir} workspace={workspace} draft={draft} onUpdated={() => { void refreshDiscussion() }} onClose={() => {}} /></Suspense>} onNav={() => setMainPanel('okr')} {...{ projectId: workspace.projectId, onManage: configureTeam }} /></Suspense></div> : <div className="okr-empty"><p>{t('okr.noSwarm')}</p><Button onClick={configureTeam}>{t('okr.edit')}</Button></div> : null },
        { key: 'memory', label: t('okr.teamMemory'), children: <Suspense fallback={<Spin />}><OkrProjectFiles key={projectDir + ':memory'} dir={projectDir ? projectDir.replace(/\/$/, '') + '/' + (workspace?.projectFiles?.root || '.roami/okr') + '/memory' : undefined} active={mainPanel === 'memory'} /></Suspense> },
        { key: 'files', label: t('okr.tab.files'), children: <Suspense fallback={<Spin />}><OkrProjectFiles key={projectDir} dir={projectDir} active={mainPanel === 'files'} openRequest={fileRequest} /></Suspense> },
      ]} />
    </>}
  </div>
    {chatting && loaded && <Suspense fallback={<Spin />}><OkrMainChat onSession={onSession} reference={reference} onClearReference={clearOkrMessageReference} projectId={projectId} projectDir={projectDir} workspace={workspace} draft={draft} onUpdated={() => { void refreshDiscussion() }} onClose={() => { setChatting(false); clearOkrMessageReference(); void refreshDiscussion() }} /></Suspense>}
  </div>
  return phone ? <MobileSubPage title={title} onBack={back} manageHistory={false} keepBottomNav>{content}</MobileSubPage> : content
}
