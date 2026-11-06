import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { nodeApi, useCurrentNodeId } from '../cluster/node-url'
import { App, Button, Spin } from 'antd'
import { api } from '../../api'
import { useSessionOverview } from '../../session-overview'
import { useAgentData } from '../agent/useAgentData'
import { useAgentThread } from '../agent/useAgentThread'
import { useLayout } from '../../layout'
import { useI18n } from '../../i18n'
import { ChevronLeft, CloseIcon, UserIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import Markdown from '../markdown/Markdown'
import { taskExecutor, type TaskDetail } from '../agent/agent-task-protocol'
import { openAgentPage } from '../agent/agent-page-route'
import { useSwarmSnapshot } from './useSwarmSnapshot'
import SwarmStudio from './SwarmStudio'
import SwarmConversations from './SwarmConversations'
import SwarmMainChat from './SwarmMainChat'
import SwarmMemberChat from './SwarmMemberChat'
import { matchesSwarmTaskFilter, swarmTaskFilters, type SwarmTaskFilter } from './swarm-task-filter'
import ConversationComposer from '../chat/ConversationComposer'
import SwarmMemberDetails from './SwarmMemberDetails'
import { swarmRoleMembers, swarmMember, type SwarmRoleBinding, type SwarmTeamMember } from './swarm-members'
import TeamMemory from './TeamMemory'
import LegacySwarmHistory from './LegacySwarmHistory'
import ExternalAcceptance from './ExternalAcceptance'
import { artifactPreviewHref } from '../agent/artifact-preview-route'
import { swarmStateToken, type SwarmSnapshot, type SwarmWork } from './swarm-protocol'
import './swarm.css'

function State({ state }: { state: string }) {
  const { t } = useI18n()
  return <span className="swarm-state" style={{ color: `var(${swarmStateToken(state)})` }}>{t(`swarm.managed.state.${state}`)}</span>
}
export default function ManagedSwarm({ id, onBack, openTerm, embedded = false, projectId, onManage, renderMain, mainRequest, roles }: { id: string; onBack: () => void; openTerm: (id: string) => void; embedded?: boolean; projectId?: string; onManage?: () => void; renderMain?: (id: string) => ReactNode; mainRequest?: number; roles?: SwarmRoleBinding[] }) {
  const { data, error, missing, refresh } = useSwarmSnapshot(id), { t } = useI18n(), { phone } = useLayout(), { message, modal } = App.useApp()
  const panelKey = 'roami.swarm.panel.v2:' + nodeApi('/agent/swarms/' + id)
  const [selected, setSelected] = useState('main'), [tab, setTab] = useState(() => localStorage.getItem(panelKey) === 'board' ? 'board' : 'chat'), [detail, setDetail] = useState<string | null>(null), [busy, setBusy] = useState(false)
  const [recipient, setRecipient] = useState('main')
  const sceneKey = panelKey + ':scene:' + (phone ? 'phone' : 'desktop')
  const [sceneChoice, setSceneChoice] = useState<Record<string, boolean>>({})
  const studioOpen = sceneChoice[sceneKey] ?? (localStorage.getItem(sceneKey) ? localStorage.getItem(sceneKey) === 'on' : !phone)
  const taskList = useRef<HTMLUListElement>(null), taskScroll = useRef(0)
  const showWorkspace = (open: boolean) => { if (taskList.current) taskScroll.current = taskList.current.scrollTop; localStorage.setItem(sceneKey, open ? 'on' : 'off'); setSceneChoice(current => ({ ...current, [sceneKey]: open })) }
  const [memberDetail, setMemberDetail] = useState<string | null>(null)
  const roster = useMemo(() => data ? swarmRoleMembers(data, roles, projectId) : null, [data?.members, data?.work, data?.memberProtocol, data?.id, data?.target.projectId, roles, projectId])
  const members = roster?.members || [], currentMembers = roster?.current || []
  const [includeHistory, setIncludeHistory] = useState(false)
  const filterKey = panelKey + ':tasks'
  const [taskFilter, setTaskFilter] = useState<SwarmTaskFilter>(() => { const saved = localStorage.getItem(filterKey); return swarmTaskFilters.includes(saved as SwarmTaskFilter) ? saved as SwarmTaskFilter : 'active' })
  const filterTasks = (value: SwarmTaskFilter) => { setTaskFilter(value); localStorage.setItem(filterKey, value); taskScroll.current = 0 }
  const boardWork = data?.work.filter(work => !roster?.configured || includeHistory || currentMembers.some(member => member.work?.id === work.id)) || []
  const filteredWork = boardWork.filter(work => matchesSwarmTaskFilter(work, taskFilter))
  const [memoryOpen, setMemoryOpen] = useState(false), [teamOpen, setTeamOpen] = useState(false)
  const controlKey = useRef<{ action: string; revision: number; key: string } | null>(null)
  useEffect(() => { localStorage.setItem(panelKey, tab) }, [tab, panelKey])
  useEffect(() => { if (mainRequest) { setRecipient('main'); setSelected('main'); setMemberDetail(null); setDetail(null); setTeamOpen(false) } }, [mainRequest])
  const switchTab = (next: string) => {
    if (taskList.current) taskScroll.current = taskList.current.scrollTop
    setTab(next)
  }
  useLayoutEffect(() => { if (taskList.current) taskList.current.scrollTop = taskScroll.current }, [tab, detail, studioOpen])
  const workspaceVisible = studioOpen && !teamOpen && !(phone && detail)
  const sceneVisible = tab === 'chat' && workspaceVisible
  const sceneActive = !data?.archived && sceneVisible && !memoryOpen
  const sceneSessions = useSessionOverview(sceneActive)
  const node = useCurrentNodeId()
  const mainThread = useAgentThread(sceneActive ? data?.mainConversationId || '' : '', '', node)
  const liveMain = mainThread.view?.turns.find(turn => ['queued', 'running'].includes(turn.state))
  const mainState = data?.paused ? 'idle' : liveMain?.state === 'queued' ? 'preparing' : liveMain?.state === 'running' ? 'running' : mainThread.view ? mainThread.view.turns[0]?.state === 'failed' ? 'failed' : 'idle' : 'unknown'
  const nativeSessions = useAgentData<{ taskId: string; revision: number; lifecycle: string }[]>(data?.work.some(item => item.executor === 'native' && item.task_id) ? '/agent/native-sessions' : null, 5000, 10000, 'GET', sceneActive)
  const nodes = useMemo(() => data ? [{ id: 'main', name: 'Roami Main', executor: 'roami', main: true, state: mainState }, ...currentMembers.filter(member => (!member.registered?.instance || ['idle', 'assigned'].includes(member.registered.instance.state)) && (member.registered?.instance?.state === 'idle' || member.work?.task_id && (member.executor === 'native'
    ? !nativeSessions.failed && nativeSessions.value?.some(session => session.taskId === member.work!.task_id && session.revision === member.work!.revision && session.lifecycle === 'open')
    : !sceneSessions.failed && sceneSessions.value.some(session => session.name === member.work!.attempt?.sessionId && !session.dormant && session.agent === member.executor)))).map(member => ({ id: member.id, name: member.name, executor: member.executor, state: member.state }))] : [], [currentMembers, mainState, nativeSessions.value, nativeSessions.failed, sceneSessions.value, sceneSessions.failed])
  const control = async (action: string) => {
    if (!data) return
    if (!controlKey.current || controlKey.current.action !== action || controlKey.current.revision !== data.revision) controlKey.current = { action, revision: data.revision, key: crypto.randomUUID() }
    setBusy(true)
    try { await api('POST', `/agent/swarms/${encodeURIComponent(id)}/control`, { action, expectedRevision: data.revision, commandKey: controlKey.current.key }); controlKey.current = null; await refresh() }
    catch { message.error(t('swarm.managed.actionFailed')) } finally { setBusy(false) }
  }
  if (!data && missing && projectId) return <LegacySwarmHistory projectId={projectId} onManage={onManage || onBack} />
  if (!data) return <div className="swarm-loading">{missing ? <><p role="alert">{t('swarm.managed.relinkTeam')}</p><button type="button" className="tt-act" onClick={onBack}>{t('swarm.managed.selectTeam')}</button></> : error ? <><p role="alert">{t('swarm.managed.unavailable')}</p><button type="button" className="tt-act" onClick={() => void refresh()}>{t('agent.retry')}</button></> : <Spin />}</div>
  if (roster?.configured && (data.target.projectId !== projectId || data.memberProtocol !== 1)) return <p role="alert" className="swarm-stream-error">{t('swarm.member.registryUnavailable')}</p>
  const inspectedMember = members.find(member => member.id === memberDetail)
  const work = data.work.find(item => item.id === detail)
  const openWork = (item: SwarmWork) => { setMemberDetail(null); setSelected(swarmMember(members, item.id)?.id || item.id); setDetail(item.id); switchTab('board'); showWorkspace(true) }
  const openChat = (requested: string) => { const id = swarmMember(members, requested)?.id || requested; setMemberDetail(null); setSelected(id); setRecipient(id); setDetail(null); setTeamOpen(false) }
  const view = <div className="swarm-work-detail">
    {work && <>{!phone && <div className="swarm-panel-head"><h3>{work.title}</h3><button type="button" className="tt-act" aria-label={t('common.close')} onClick={() => setDetail(null)}><CloseIcon /></button></div>}<State state={work.state} />
      {work.evidence?.verification?.state === 'missing' && <p role="status">{t('swarm.managed.evidenceMissing')}</p>}
      {Boolean(work.evidence?.artifacts.length) && <section><h4>{t('swarm.managed.outputs')}</h4>{work.evidence!.artifacts.map(item => <p key={item.id}><a href={artifactPreviewHref(item.id)} target={phone ? undefined : '_blank'} rel="noopener noreferrer">{item.name}</a></p>)}</section>}
      {work.attempt?.summary && <details><summary>{t('swarm.managed.report')}</summary><Markdown>{work.attempt.summary}</Markdown></details>}
      {work.state === 'waiting_user' && work.deliverables?.some(item => item.kind === 'external_action') && <ExternalAcceptance key={work.id + ':' + work.revision} work={work} onAccepted={refresh} />}
      <details className="swarm-description"><summary>{t('swarm.managed.instructions')}</summary><Markdown>{work.goal}</Markdown><h4>{t('swarm.managed.acceptance')}</h4><Markdown>{work.acceptance}</Markdown></details>
      {work.dispatch_error && <p role="alert">{t(work.dispatch_error === 'SWARM_DEPENDENCY_NOT_VERIFIED' ? 'swarm.managed.dependencyBlocked' : 'swarm.managed.dispatchFailed')}</p>}
      {work.dependencies.length > 0 && <section><h4>{t('swarm.managed.dependencies')}</h4>{work.dependencies.map(dep => <p key={dep.upstreamId}>{data.work.find(item => item.id === dep.upstreamId)?.title}</p>)}</section>}
      <div className="swarm-detail-actions">{work.task_id && <button type="button" className="tt-act" onClick={() => openAgentPage('tasks', work.task_id!)}>{t('swarm.managed.openTask')}</button>}</div>
    </>}
  </div>
  const inspectMember = (id: string) => { setMemberDetail(id); setDetail(null); setTeamOpen(false) }
  const selectMember = (id: string) => { if (id === 'main' || id === 'group') openChat(id); else if (swarmMember(members, id)) openChat(swarmMember(members, id)!.id); if (phone) showWorkspace(false) }
  const studio = <SwarmStudio compactHeader active={sceneActive} nodes={nodes} selected={selected} onSelect={selectMember} />
  const memberView = inspectedMember && <SwarmMemberDetails key={nodeApi('/agent/swarms/' + id) + ':' + inspectedMember.id} swarmId={id} member={inspectedMember} compact={phone} onClose={() => setMemberDetail(null)} />
  const currentMember = swarmMember(members, recipient)
  const directory = <SwarmConversations members={currentMembers} historical={roster?.historical} unbound={roster?.unbound} selected={recipient} onSelect={openChat} />
  const controls = <details className="swarm-controls"><summary>{t('common.more')}</summary><div className="swarm-control-menu">{phone && currentMember?.registered && <button type="button" className="tt-act" onClick={() => inspectMember(currentMember.id)}>{t('swarm.member.details')}</button>}{tab === 'board' && Boolean(roster?.historical.length) && <button type="button" className="tt-act" aria-pressed={includeHistory} onClick={() => setIncludeHistory(value => !value)}>{t('swarm.member.includeHistory')}</button>}<button type="button" className="tt-act" disabled={busy || data.archived} onClick={() => void control(data.paused ? 'resume' : 'pause')}>{t(data.paused ? 'swarm.managed.resume' : 'swarm.managed.pause')}</button><button type="button" className="tt-act" onClick={() => { void refresh().then(() => { setDetail(null); setMemberDetail(null); setTeamOpen(false); setMemoryOpen(true) }) }}>{t('swarm.managed.memory')}</button><button type="button" className="tt-act danger" disabled={busy || data.archived} onClick={() => modal.confirm({ title: t('swarm.managed.stopTitle'), content: t('swarm.managed.stopHint'), onOk: () => control('stop') })}>{t('swarm.managed.stop')}</button><button type="button" className="tt-act" disabled={busy || data.archived} onClick={() => void control('archive')}>{t('swarm.archive')}</button></div></details>
  const workspace = <div className="swarm-workbench">
    <nav className="swarm-tabs" aria-label={t('swarm.managed.workspace')}>
      {['chat', 'board'].map(key => <button type="button" key={key} aria-pressed={tab === key} onClick={() => switchTab(key)}>{t(key === 'chat' ? 'swarm.managed.tab.studio' : 'swarm.managed.tab.board')}</button>)}
    </nav>
    {tab === 'board' && !work && <div className="swarm-task-filters" role="group" aria-label={t('agent.task.filter.label')}>{swarmTaskFilters.map(value => <button type="button" key={value} aria-pressed={taskFilter === value} onClick={() => filterTasks(value)}>{t('agent.task.filter.' + value)}</button>)}</div>}
    {tab === 'chat' ? studio : !phone && work ? view : !filteredWork.length ? <p className="swarm-note" role="status">{t(taskFilter === 'all' && !boardWork.length ? 'swarm.managed.planning' : 'agent.task.filter.empty')}</p> : <ul ref={taskList} className="swarm-task-list" aria-label={t('swarm.managed.tab.board')}>
      {filteredWork.map(item => <li key={item.id}><button type="button" className="swarm-task-row" aria-pressed={detail === item.id} onClick={() => openWork(item)}><strong>{item.title}</strong><small>{swarmMember(members, item.id)?.name || item.member_name}</small><State state={item.state} /></button></li>)}
    </ul>}
  </div>
  return <div className="swarm-managed" data-embedded={embedded} data-team-open={teamOpen}>
    {!embedded && <header className="tt-pagehead"><div className="swarm-page-identity">{!phone && <button type="button" className="tt-act" onClick={onBack} aria-label={t('common.back')}><ChevronLeft /></button>}<h2>{data.name}</h2>{data.paused && <span className="swarm-note">{t('swarm.managed.paused')}</span>}</div><div className="acts">{controls}</div></header>}
    {error && <div className="swarm-stream-error" role="status">{t('swarm.managed.reconnecting')}</div>}
    {data.archived && <p className="swarm-note">{t('swarm.managed.archived')}</p>}

    {(!memoryOpen || phone) && <>
      <div className="swarm-conversation-workspace" data-scene={!phone && workspaceVisible}>
        {!phone && directory}
        <section className="swarm-conversation-pane" data-recipient={recipient} aria-label={t('swarm.conversation.chat')}>
          <header className="swarm-conversation-head">
            {phone && <button type="button" className="tt-act" aria-label={t('swarm.conversation.list')} onClick={() => setTeamOpen(true)}><UserIcon />{t('swarm.conversation.chat')}</button>}
            <div><strong>{recipient === 'main' ? t('swarm.conversation.main') : recipient === 'group' ? t('swarm.managed.tab.chat') : currentMember?.name || t('swarm.member.recipientUnavailable')}</strong>{phone && <small>{recipient === 'main' ? t('swarm.conversation.mainRole') : currentMember ? <State state={currentMember.state} /> : null}</small>}</div>
            <button type="button" className="tt-act" aria-expanded={studioOpen} onClick={() => showWorkspace(!studioOpen)}>{t('swarm.workspace.open')}</button>{embedded && controls}
            {currentMember && !phone && <div className="swarm-detail-actions"><State state={currentMember.state} />{currentMember.registered && <button type="button" className="tt-act" onClick={() => inspectMember(currentMember.id)}>{t('swarm.member.details')}</button>}</div>}
          </header>
          {memberView && !phone ? memberView : recipient === 'main' ? data.mainConversationId ? renderMain ? renderMain(data.mainConversationId) : <SwarmMainChat key={nodeApi('/agent/conversations/' + data.mainConversationId)} conversationId={data.mainConversationId} projectId={data.target?.projectId} onSent={refresh} /> : <p role="alert" className="swarm-note">{t('swarm.relations.mainUnavailable')}</p> : currentMember?.registered && (currentMember.registered.instance || currentMember.executor !== 'native') ? <SwarmMemberChat key={nodeApi('/agent/swarms/' + data.id) + ':' + currentMember.id} data={data} member={currentMember} onMain={() => openChat('main')} onSession={openTerm} onChanged={refresh} /> : <SwarmChat members={members} key={nodeApi('/agent/swarms/' + data.id) + ':' + recipient} data={data} recipient={recipient} selected={selected} onSelect={openChat} onWork={openWork} onSession={openTerm} onSent={refresh} />}
        </section>
        {!phone && workspaceVisible && <aside className="swarm-collaboration-pane" aria-label={t('swarm.workspace.open')}>{workspace}</aside>}
      </div>
    </>}

    {memoryOpen && (phone ? <MobileSubPage title={t('swarm.managed.memory')} onBack={() => setMemoryOpen(false)}><TeamMemory data={data} onReload={refresh} onSaved={async () => { await refresh(); setMemoryOpen(false) }} /></MobileSubPage> : <><div className="swarm-panel-head"><strong>{t('swarm.managed.memory')}</strong><button type="button" className="tt-act" aria-label={t('common.close')} onClick={() => setMemoryOpen(false)}><CloseIcon /></button></div><TeamMemory data={data} onReload={refresh} onSaved={async () => { await refresh(); setMemoryOpen(false) }} /></>)}
    {phone && workspaceVisible && !memoryOpen && <MobileSubPage title={t('swarm.workspace.open')} onBack={() => showWorkspace(false)}>{workspace}</MobileSubPage>}
    {phone && teamOpen && <MobileSubPage title={t('swarm.conversation.list')} onBack={() => setTeamOpen(false)}>{directory}</MobileSubPage>}
    {phone && inspectedMember && <MobileSubPage title={inspectedMember.name} onBack={() => setMemberDetail(null)}>{memberView}</MobileSubPage>}
    {phone && work && <MobileSubPage title={work.title} onBack={() => setDetail(null)}>{view}</MobileSubPage>}
  </div>
}

function SwarmChat({ data, members, recipient, selected, onSelect, onWork, onSession, onSent }: { data: SwarmSnapshot; members: SwarmTeamMember[]; recipient: string; selected: string; onSelect: (id: string) => void; onWork: (item: SwarmWork) => void; onSession: (id: string) => void; onSent: () => Promise<void> }) {
  const { t, locale } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const sessions = useSessionOverview(!data.archived)
  const latestSessions = useRef(sessions); latestSessions.current = sessions
  const legacyKey = 'roami.swarm.draft:' + nodeApi('/agent/swarms/' + data.id)
  const storageKey = legacyKey + ':thread:' + recipient
  const [saved] = useState(() => { try { const value = localStorage.getItem(storageKey); if (value) return JSON.parse(value); const legacy = JSON.parse(localStorage.getItem(legacyKey) || '{}'); const previous = legacy.scope || legacy.recipient || 'group'; const destination = previous === 'main' ? 'group' : swarmMember(members, previous)?.id || previous; return destination === recipient ? legacy : {} } catch { return {} } })
  const scope = recipient
  const [opening, setOpening] = useState(false)
  const alive = useRef(true), openingRef = useRef(false), latestScope = useRef(scope); latestScope.current = scope
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const [draft, setDraft] = useState<string>(saved.draft || ''), [sending, setSending] = useState(false)
  const sendKey = useRef<{ key: string; payload: string; body?: { text: string; workId?: string; taskRevision?: number | null } }>(saved.pending || { key: crypto.randomUUID(), payload: '' })
  useEffect(() => { localStorage.setItem(storageKey, JSON.stringify({ draft, scope, pending: sendKey.current })) }, [draft, scope, sending, storageKey])
  const editDraft = (text: string) => setDraft(text)
  const chooseRecipient = (id: string) => onSelect(swarmMember(members, id)?.id || id)
  const messages = useMemo(() => [
    ...data.posts.map(post => {
      const work = post.taskId ? data.work.find(item => item.task_id === post.taskId) : undefined
      const author = work && ['human', 'main'].includes(post.author) ? t(post.author === 'main' ? 'swarm.chat.forwardedTo' : 'swarm.chat.sentTo', { name: work.member_name }) : post.author === 'human' ? t('swarm.chat.you') : post.author === 'main' ? 'Roami Main' : post.author
      return { id: 'post:' + post.id, taskId: post.taskId, author, text: post.text, time: post.createdMs, pending: post.deliveryState === 'pending', mainTurn: post.mainTurn?.conversationId === data.mainConversationId ? post.mainTurn : undefined, work }
    }),
    ...data.mainMessages.filter(item => item.text).map(item => ({ id: item.id, taskId: undefined as string | null | undefined, author: 'Roami Main', text: item.text, time: item.createdMs, pending: false, mainTurn: undefined, work: undefined as SwarmWork | undefined })),
  ].sort((a, b) => a.time - b.time), [data.posts, data.mainMessages, data.work, data.mainConversationId, t])
  const currentMember = swarmMember(members, scope)
  const currentWork = currentMember?.work?.task_id ? currentMember.work : undefined
  const latestMember = useRef(currentMember); latestMember.current = currentMember
  const latestProject = useRef(data.target?.projectId); latestProject.current = data.target?.projectId
  const latestMain = useRef(data.mainConversationId); latestMain.current = data.mainConversationId
  const missingRecipient = scope !== 'group' && scope !== 'main' && !currentMember
  const unavailableRecipient = missingRecipient || Boolean(currentMember?.registered?.workId && !currentMember.work)
  const unavailableSession = Boolean(currentMember?.registered?.instance && ['closed', 'closing', 'unknown'].includes(currentMember.registered.instance.state))
  const latestWork = useRef(currentWork); latestWork.current = currentWork
  const thread = currentMember?.id || scope
  const visibleMessages = messages.filter(item => thread === 'group' || thread === 'main' && !item.taskId || Boolean(currentWork && item.taskId === currentWork.task_id))
  const chatLog = useRef<HTMLDivElement>(null), followLatest = useRef(true), lastThread = useRef(thread)
  const lastMessage = visibleMessages[visibleMessages.length - 1]
  const latestMessage = lastMessage ? lastMessage.id + ':' + (lastMessage.mainTurn?.state || '') : ''
  useLayoutEffect(() => {
    if (lastThread.current !== thread) { lastThread.current = thread; followLatest.current = true }
    if (followLatest.current && chatLog.current) chatLog.current.scrollTop = chatLog.current.scrollHeight
  }, [thread, latestMessage])
  const enterConversation = async () => {
    if (!currentWork?.task_id || openingRef.current) return
    openingRef.current = true; setOpening(true)
    const taskId = currentWork.task_id, requestedScope = scope, requestedRevision = currentWork.revision, requestedRun = currentWork.attempt?.runId, requestedMember = currentMember!.id, requestedInstance = currentMember?.registered?.instance ? { ...currentMember.registered.instance } : undefined, requestedExecutor = currentMember?.executor, requestedNode = nodeApi('/agent/swarms/' + data.id), requestedProject = data.target?.projectId, requestedMain = data.mainConversationId
    const fallback = () => {
      if (!alive.current || latestScope.current !== requestedScope || nodeApi('/agent/swarms/' + data.id) !== requestedNode || latestMember.current?.id !== requestedMember) return
      if (latestWork.current?.task_id) openAgentPage('tasks', latestWork.current.task_id)
    }
    try {
      const response = await api('GET', '/agent/tasks/' + encodeURIComponent(taskId))
      const detail: TaskDetail = response.data
      if (!alive.current || latestScope.current !== requestedScope || nodeApi('/agent/swarms/' + data.id) !== requestedNode) return
      const observed = latestWork.current
      if (!observed || latestMember.current?.id !== requestedMember || latestMember.current?.executor !== requestedExecutor) return
      const instance = latestMember.current.registered?.instance
      if (instance?.id !== requestedInstance?.id || instance?.conversationId !== requestedInstance?.conversationId || instance?.branchId !== requestedInstance?.branchId || instance?.nativeSessionId !== requestedInstance?.nativeSessionId || instance && instance.state !== 'assigned') { fallback(); return }
      if (observed.task_id !== taskId || observed.revision !== requestedRevision || observed.attempt?.runId !== requestedRun) { if (observed.task_id) openAgentPage('tasks', observed.task_id); return }
      if (latestProject.current !== requestedProject || latestMain.current !== requestedMain) { fallback(); return }
      const attempt = detail.attempts[0]
      const sessions = latestSessions.current.failed ? [] : latestSessions.current.value.filter(session => session.name === attempt?.sessionId)
      const session = sessions.length === 1 && !sessions[0].dormant && sessions[0].agent === requestedExecutor ? sessions[0] : undefined
      // Legacy session targets can omit projectId; use the host's persistent home identity.
      const projectMatches = !requestedProject || (detail.task.projectId === requestedProject || detail.task.projectId == null && !detail.task.nativeSession && detail.task.origin_conversation_id === requestedMain && session?.projectKey === requestedProject) && (!session?.projectKey || session.projectKey === requestedProject)
      if (detail.task.id !== taskId || detail.task.revision !== currentWork.revision || !attempt || attempt.revision !== detail.task.revision || attempt.id !== currentWork.attempt?.runId || ['closing', 'closed', 'unknown'].includes(detail.sessionClosure?.state || '') || taskExecutor(detail.task) !== currentMember?.executor || !projectMatches) { fallback(); return }
      if (detail.task.nativeSession) {
        if (instance && (instance.conversationId !== detail.task.nativeSession.conversationId || instance.nativeSessionId !== detail.task.nativeSession.id)) { fallback(); return }
        openAgentPage('session', detail.task.nativeSession.id)
      }
      else if (session) onSession(session.name)
      else fallback()
    } catch { if (alive.current && latestScope.current === requestedScope) fallback() }
    finally { openingRef.current = false; if (alive.current) setOpening(false) }
  }
  const send = async () => {
    if (!draft.trim() || sending) return
    const mention = /^\s*@([^\s]+)(?:\s+|$)/.exec(draft)?.[1]
    const recipient = thread === 'group' ? 'main' : thread
    const addressedMain = ['leader', 'main'].includes(mention?.toLowerCase() || '')
    const matches = mention ? members.filter(member => member.name === mention || member.registered?.name === mention) : []
    if (mention && !addressedMain && matches.length !== 1) { message.error(t('swarm.member.recipientUnavailable')); return }
    const destination = scope === 'group' ? addressedMain || !mention ? 'main' : matches[0].id : scope
    const member = swarmMember(members, destination)
    const work = member?.work
    if (scope !== 'group' && mention && (addressedMain || matches[0]?.id !== currentMember?.id)) { message.error(t('swarm.conversation.recipientConflict')); return }
    if (destination !== 'main' && (!work?.task_id || !work.revision || member?.registered?.instance && ['closed', 'closing', 'unknown'].includes(member.registered.instance.state))) { message.error(t('swarm.member.recipientUnavailable')); return }
    let body = { text: draft.trim(), ...(work ? { workId: work.id, taskRevision: work.revision } : {}) }
    const payload = JSON.stringify({ text: body.text, workId: body.workId })
    if (sendKey.current.payload && payload !== sendKey.current.payload) sendKey.current = { key: crypto.randomUUID(), payload: '' }
    if (sendKey.current.payload === payload && sendKey.current.body) body = sendKey.current.body
    else sendKey.current.body = body
    sendKey.current.payload = payload; localStorage.setItem(storageKey, JSON.stringify({ draft, scope, pending: sendKey.current })); setSending(true)
    const requestedNode = nodeApi('/agent/swarms/' + data.id)
    try { await api('POST', `/agent/swarms/${data.id}/messages`, { ...body, commandKey: sendKey.current.key }); if (!alive.current || nodeApi('/agent/swarms/' + data.id) !== requestedNode) return; setDraft(''); sendKey.current = { key: crypto.randomUUID(), payload: '' }; await onSent() }
    catch { if (alive.current && nodeApi('/agent/swarms/' + data.id) === requestedNode) message.error(t('swarm.managed.sendFailed')) } finally { if (alive.current && nodeApi('/agent/swarms/' + data.id) === requestedNode) setSending(false) }
  }
  return <section className="swarm-chat" aria-label={t('swarm.managed.tab.chat')}>
    {(unavailableRecipient || unavailableSession || currentMember) && <div className="swarm-chat-context">{(unavailableRecipient || unavailableSession || currentMember && !currentWork) && <span>{t(unavailableRecipient ? 'swarm.member.recipientUnavailable' : unavailableSession ? 'swarm.member.sessionUnavailable' : 'swarm.member.unassigned')}</span>}{(unavailableRecipient || unavailableSession || currentMember && !currentWork) && <button type="button" className="tt-act" onClick={() => chooseRecipient('main')}>{t('swarm.relations.adjustMain')}</button>}{currentWork && <div className="swarm-detail-actions"><button type="button" className="tt-act" onClick={() => openAgentPage('tasks', currentWork.task_id!)}>{t('swarm.relations.openWork')}</button><button type="button" className="tt-act" disabled={opening || unavailableSession} onClick={() => void enterConversation()}>{t('swarm.managed.openSession')}</button></div>}</div>}
    <div className="swarm-chat-log" ref={chatLog} onScroll={event => { const pane = event.currentTarget; followLatest.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < pane.clientHeight * .1 }} role="log" aria-label={t('swarm.managed.messages')}>
    {!visibleMessages.length && <p className="swarm-note">{t('swarm.managed.chatEmpty')}</p>}
    {visibleMessages.map(item => <article className="swarm-chat-message" key={item.id} data-selected={item.work?.id === selected}><header><button type="button" className="tt-act" onClick={() => item.work ? chooseRecipient(swarmMember(members, item.work.id)?.id || item.work.id) : chooseRecipient('main')}>{item.author}</button>{item.time > 0 && <time>{new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(item.time)}</time>}</header>{item.pending && <span className="swarm-note">{t('swarm.managed.deliveryPending')}</span>}{item.id.startsWith('result:') && item.text === 'SESSION_TARGET_NOT_FOUND' && <p role="status">{t('swarm.chat.sessionMissing')}</p>}{item.id.startsWith('result:') ? <details><summary>{t('swarm.managed.report')}</summary><Markdown>{item.text}</Markdown></details> : <Markdown>{item.text}</Markdown>}{scope === 'group' && item.mainTurn?.state === 'failed' && <div className="swarm-chat-delivery-failed" role="alert"><span>{t('swarm.chat.mainReplyFailed')}</span><button type="button" className="tt-act" onClick={() => chooseRecipient('main')}>{t('swarm.chat.viewMain')}</button></div>}{scope === 'group' && item.work && <div className="swarm-chat-task-actions"><button type="button" className="tt-act" onClick={() => onWork(item.work!)}>{t('swarm.managed.openTask')}</button><button type="button" className="tt-act" onClick={() => { chooseRecipient(swarmMember(members, item.work!.id)?.id || item.work!.id) }}>{t('swarm.managed.replyMember')}</button></div>}</article>)}
  </div><ConversationComposer className="swarm-chat-composer" value={draft} onChange={editDraft} label={t('swarm.managed.messages')} placeholder={scope === 'group' ? t('swarm.conversation.groupPlaceholder') : t('chat.sendTo', { name: currentMember?.name || '' })} disabled={data.archived} maxLength={8000}
    send={{ label: t('common.send'), pending: sending, disabled: unavailableRecipient || unavailableSession || Boolean(currentMember && !currentWork), onClick: () => void send() }}
    suggestions={scope === 'group' && /^\s*@[^\s]*$/.test(draft) && <div className="swarm-detail-actions">{[{ name: 'leader', id: 'main' }, ...members.map(member => ({ name: member.name, id: member.id }))].filter(member => member.name.toLowerCase().startsWith(draft.trim().slice(1).toLowerCase())).map(member => <button type="button" key={member.id} className="tt-act" onClick={() => { setDraft('@' + member.name + ' '); document.querySelector<HTMLTextAreaElement>('.swarm-chat textarea')?.focus() }}>{'@' + member.name}</button>)}</div>} />
  </section>
}
