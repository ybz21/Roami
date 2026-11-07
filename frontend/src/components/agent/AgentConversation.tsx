import { agentTimeline, groupAgentTimeline } from './agent-timeline'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { App, Button, Dropdown, Input, Modal, Spin } from 'antd'
import { api } from '../../api'
import { agentName, isAgentKind, type AgentKind } from '../../agent-kind'
import { AgentLogo, ArrowDown, BellIcon, ChecklistIcon, ChevronDown, ClockIcon, CloseIcon, CodeIcon, FileTextIcon, MoreIcon, NotebookIcon, PanelRightIcon, RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import Markdown from '../markdown/Markdown'
import MobileSubPage from '../MobileSubPage'
import AgentMemory from './AgentMemory'
import { openAgentPage } from './agent-page-route'
import AgentTasks from './AgentTasks'
import { agentFailure } from './agent-request-failure'
import AgentWorkspaceRail from './AgentWorkspaceRail'
import { useAgentWorkspace } from './useAgentWorkspace'
import './agent-workspace.css'
import { useAgentThread } from './useAgentThread'
import { useAgentData } from './useAgentData'
import { useBoundaryLoad } from './useBoundaryLoad'
import AgentPageBoundary from './AgentPageBoundary'
import { agentDataKey, invalidateAgentData } from './agent-data-cache'
import { useAgentDraft } from './useAgentDraft'
import { useAgentMessageFocus } from './useAgentMessageFocus'
import { useVisibleAgentReads } from './useVisibleAgentReads'
import type { AgentInboxState } from './useAgentInbox'
import type { AgentMessage } from './agent-protocol'
import AgentComposerPlus from './AgentComposerPlus'
import AgentDraftFiles from './AgentDraftFiles'
import ConversationComposer from '../chat/ConversationComposer'
import VoiceInput from '../chat/VoiceInput'
import AgentMessageView from './AgentMessageView'
import AgentTaskActivity from './AgentTaskActivity'
import AgentActivity from './AgentActivity'
import { mainTaskActivities, groupExecutionSteps } from './main-task-activity'
import { useAgentAttachments } from './useAgentAttachments'
import { useAgentModels } from './useAgentModels'
import { useAgentOutbox } from './useAgentOutbox'
import AgentOutbox from './AgentOutbox'
import './agent-chat.css'

const newKey = () => crypto.randomUUID()

export type HomeConversationProps = {
  cid: string; branch: string; focusMessage?: string; inactive?: boolean; node: string | null; inbox: AgentInboxState; inboxOpen: boolean
  select: (cid: string, branch?: string, message?: string) => void; notifications: () => void
  projects: { id: string; name: string }[]; onSession: (session: string) => void; onOverview: () => void
  mobileActionsHost?: HTMLElement | null
}
export type ProjectConversationBinding = {
  draftKey: string; ensureConversation: () => Promise<string>; isCurrent: () => boolean
  prepareContext: (text: string) => AgentMessage['content']['okrContext']; displayText: (text: string, content?: AgentMessage['content']) => string
  onUpdated?: () => void; onCurrentBranch?: () => void
  inputLabel: string; placeholder: string; sendLabel: string
}
type Props = Omit<Partial<HomeConversationProps>, 'cid' | 'node'> & {
  cid: string; node: string | null; project?: ProjectConversationBinding
}
const noop = () => {}
export default function AgentConversation({ cid, branch = '', focusMessage = '', inactive = false, node, inbox, inboxOpen = false, select = noop, notifications = noop, projects = [], onSession = noop, mobileActionsHost, project }: Props) {
  const { t } = useI18n(), { phone, size } = useLayout(), { message } = App.useApp()
  const thread = useAgentThread(cid, branch, node, focusMessage)
  const rsi = useAgentData<{ developmentRsi: boolean }>(project ? null : '/agent/status', 60_000)
  const workspace = useAgentWorkspace(node), wide = !project && size === 'large'
  const workspaceSelectionKey = 'roami.task.selection.' + (node || 'local') + ':' + cid
  const [workspaceTask, editWorkspaceTask] = useAgentDraft(workspaceSelectionKey)
  const setWorkspaceTask = (value: string) => { editWorkspaceTask(value); try { if (value) localStorage.setItem(workspaceSelectionKey, value); else localStorage.removeItem(workspaceSelectionKey) } catch { /* Keep selection in memory. */ } }
  const openWorkspaceTask = (id: string) => { setWorkspaceTask(id); workspace.change({ open: true, tab: 'tasks' }) }
  const [sending, setSending] = useState(false)
  const [target, setTarget] = useState('direct'), [executor, setExecutor] = useState<AgentKind>('codex')
  const [panel, setPanel] = useState<'tasks' | 'memory' | 'context' | null>(null)
  const showPanel = (next: 'tasks' | 'memory' | 'context') => {
    if (!project && phone && next !== 'context') { openAgentPage(next); return }
    if (wide && next !== 'context') { workspace.change({ open: true, tab: next }); setWorkspaceTask(''); setPanel(null) }
    else setPanel(next)
  }
  const [context, setContext] = useState<any>(null), [summary, setSummary] = useState('')
  const [panelLoading, setPanelLoading] = useState(false), [panelError, setPanelError] = useState(false)
  const [source, setSource] = useState<AgentMessage | null>(null)
  const [memoryTitle, setMemoryTitle] = useState(''), [memoryBody, setMemoryBody] = useState('')
  const [error, setError] = useState('')
  const [commandsDismissed, setCommandsDismissed] = useState(false)
  const [commandsOpen, setCommandsOpen] = useState(false), [commandIndex, setCommandIndex] = useState(0)
  const [jumpLatest, setJumpLatest] = useState(false), [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const models = useAgentModels(node)
  const scroll = useRef<HTMLDivElement>(null), stick = useRef(true), sendingRef = useRef(false)
  const activeCID = useRef(cid); activeCID.current = cid
  const panelRequest = useRef(0)
  const pending = useRef<{ text: string; payload?: string; okrContext?: AgentMessage['content']['okrContext']; target: string; executor: string; cid: string; key: string; attachmentIds: string[]; scope: string } | null>(null)
  const pendingOwner = useRef('')
  const createKey = useMemo(newKey, [cid, node])
  const draftKey = project?.draftKey || `roami.agent.draft.${node || 'local'}.${cid || 'new'}`
  const [draft, setDraft] = useAgentDraft(draftKey)
  if (pendingOwner.current !== draftKey) {
    pendingOwner.current = draftKey; pending.current = null
    if (project) {
      try {
        const saved = JSON.parse(localStorage.getItem(draftKey + ':pending') || 'null')
        if (saved && typeof saved.text === 'string' && typeof saved.payload === 'string' && typeof saved.key === 'string') pending.current = { ...saved, text: saved.text.trim(), target: 'direct', executor: 'codex', cid: saved.conversationId || saved.cid || '', attachmentIds: saved.attachmentIds || [], scope: draftKey }
      } catch { /* Preserve malformed receipts for explicit recovery. */ }
    }
  }
  const activeScope = useRef(draftKey); activeScope.current = draftKey
  const draftRef = useRef(draft); draftRef.current = draft
  const attachments = useAgentAttachments(draftKey)
  const mainCID = project ? cid : inbox?.conversations[0]?.id
  const completed = useRef(new Set<string>())
  useEffect(() => {
    const fresh = (thread.view?.messages || []).filter(item => item.role === 'assistant' && item.status === 'completed' && !completed.current.has(item.id))
    if (fresh.length) { fresh.forEach(item => completed.current.add(item.id)); project?.onUpdated?.() }
  }, [thread.view?.messages, project?.onUpdated])
  const historical = !!thread.view && (thread.view.branchId !== thread.view.conversation.active_branch_id || (!!mainCID && cid !== mainCID))
  const readOnly = historical || (!project && !mainCID)
  const running = thread.view?.turns.some((item) => item.state === 'running' || item.state === 'queued') || false
  const compact = thread.view?.compaction
  const compacting = compact?.state === 'queued' || compact?.state === 'running' || compact?.state === 'started'
  const outboxReady = !readOnly && !sending && !compacting && thread.connected && thread.view?.conversation.id === cid
  const outbox = useAgentOutbox(project ? draftKey + ':' + cid : draftKey, outboxReady, !running, async item => {
    if (project && !project.isCurrent()) throw new Error('Conversation changed')
    const owner = draftKey, origin = cid
    if (project && await project.ensureConversation() !== origin) throw new Error('Project Main changed')
    const { data } = await api('POST', `/agent/conversations/${encodeURIComponent(origin)}/messages`, { requestKey: item.id, text: item.payload ?? item.text, attachmentIds: item.attachments.map(file => file.id), ...(item.okrContext ? { okrContext: item.okrContext } : {}) })
    if (activeScope.current !== owner || project && !project.isCurrent()) return
    if (data.kind === 'message') thread.accepted(data, item.text, item.okrContext)
    thread.refresh(); inbox?.refresh()
  }, project ? text => ({ payload: text, okrContext: project.prepareContext(text) }) : undefined)
  const bodies = useMemo(() => (thread.view?.messages || []).filter(m => m.role === 'user' || m.role === 'assistant').map(m => project && m.role === 'user' && m.content.text ? { ...m, content: { ...m.content, text: project.displayText(m.content.text, m.content) } } : m), [thread.view?.messages, project?.displayText])
  const settledDispatches = useMemo(() => new Set(bodies.filter(m => ['completed', 'failed'].includes(m.content.sessionReply?.status || '')).map(m => m.content.sessionReply!.dispatchId)), [bodies])
  const timeline = useMemo(() => groupAgentTimeline(agentTimeline(bodies, mainTaskActivities(thread.view?.activities || []))), [bodies, thread.view?.activities])
  const visible = useMemo(() => bodies.filter(m => m.content.text || m.content.replyPreview?.text || m.content.question || m.content.taskStatus || m.content.attachments?.length || m.status === 'streaming'), [bodies])
  const history = { entries: timeline }
  const prepend = useRef<{ top: number; height: number } | null>(null)
  const older = () => {
    if (!scroll.current || thread.loadingOlder) return
    prepend.current = { top: scroll.current.scrollTop, height: scroll.current.scrollHeight }
    stick.current = false
    void thread.loadOlder()
  }
  useBoundaryLoad(scroll, older, !!thread.view?.page?.hasMore && !thread.loadingOlder && !thread.olderFailed, 'start')
  useLayoutEffect(() => {
    if (!thread.loadingOlder && prepend.current && scroll.current) {
      scroll.current.scrollTop = prepend.current.top + scroll.current.scrollHeight - prepend.current.height
      prepend.current = null
    }
  }, [thread.view?.messages, thread.loadingOlder])
  const eventIds = history.entries.map(entry => entry.message?.completedEventId || '').join(',')
  useVisibleAgentReads(!inactive && !panel && !source && !inboxOpen ? cid : '', scroll, eventIds, inbox?.refresh || noop)

  useEffect(() => {
    if (!project && !inactive && mainCID && !branch && !focusMessage && cid !== mainCID) select(mainCID)
    if (!project && cid === mainCID) { try { localStorage.setItem(`roami.agent.last.${node || 'local'}`, cid) } catch {} }
  }, [cid, mainCID, branch, focusMessage, node, select, inactive, project])

  useEffect(() => {
    stick.current = true; setError(''); setWorkspaceTask(''); setPanel(null); setSource(null); panelRequest.current++
    if (!sendingRef.current || pending.current?.cid !== cid) {
      setTarget('direct')
    }
  }, [draftKey])
  useEffect(() => { if (stick.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight }, [thread.view?.messages, thread.view?.activities, cid])
  useAgentMessageFocus(scroll, cid, branch, focusMessage, visible.map((item) => item.id).join(','), stick)
  const changeDraft = (value: string) => { draftRef.current = value; setDraft(value); try { localStorage.setItem(draftKey, value) } catch {} }
  const ensureConversation = async () => {
    if (project) return project.ensureConversation()
    if (cid) return cid
    const { data } = await api('POST', '/agent/main-conversation', { requestKey: createKey })
    if (activeCID.current === cid) {
      const destination = `roami.agent.draft.${node || 'local'}.${data.id}`
      attachments.transfer(destination)
      setDraft(draftRef.current, destination)
      try { localStorage.setItem(destination, draftRef.current); localStorage.removeItem(draftKey) } catch {}
      if (pending.current?.scope === draftKey) pending.current.scope = destination
      select(data.id)
    }
    inbox?.refresh(); return data.id as string
  }
  const loadPanel = useCallback(async () => {
    if (!panel || panel === 'memory' || panel === 'tasks' || !cid) return
    const version = ++panelRequest.current
    const current = () => version === panelRequest.current && activeCID.current === cid
    setPanelLoading(true); setPanelError(false)
    try {
      const r = await api('GET', `/agent/conversations/${encodeURIComponent(cid)}/context`)
      if (!current()) return
      setContext(r.data); setSummary('')
      if (r.data.snapshotId) { const s = await api('GET', `/agent/conversations/${encodeURIComponent(cid)}/context/snapshots/${encodeURIComponent(r.data.snapshotId)}`); if (current()) setSummary(s.data.summary.text || '') }
    } catch { if (current()) setPanelError(true) } finally { if (current()) setPanelLoading(false) }
  }, [panel, cid])
  useEffect(() => {
    let stop = false
    const timer = setTimeout(() => { if (!stop) void loadPanel() }, 150)
    const interval = panel === 'context' ? setInterval(() => { void loadPanel() }, 3000) : undefined
    return () => { stop = true; panelRequest.current++; clearTimeout(timer); clearInterval(interval) }
  }, [loadPanel, panel])
  const submit = async (text = draft, consumeDraft = true, direct = false) => {
    const destination = direct ? 'direct' : target
    const attachmentIds = consumeDraft ? attachments.ids : []
    const value = text.trim()
    if ((project && !project.isCurrent()) || (!value && !attachmentIds.length) || (consumeDraft && attachments.blocked) || sendingRef.current || readOnly || (destination !== 'direct' && !value.startsWith('/') && value.length > 20000)) return
    sendingRef.current = true; setSending(true); setError('')
    let request = pending.current
    try {
      const origin = await ensureConversation()
      if (!request || request.text !== value || request.target !== destination || request.executor !== executor || JSON.stringify(request.attachmentIds) !== JSON.stringify(attachmentIds) || (cid && !project && request.cid !== cid)) {
        request = { text: value, payload: value, okrContext: project?.prepareContext(value), target: destination, executor, cid, key: newKey(), attachmentIds, scope: draftKey }
        pending.current = request
      }
      if (project && request.cid && request.cid !== origin) throw new Error('Project Main changed')
      request.cid = origin
      if (project) localStorage.setItem(request.scope + ':pending', JSON.stringify(request))
      const current = () => activeScope.current === request.scope && (!project || project.isCurrent()) && (activeCID.current === origin || (!activeCID.current && !cid))
      if (!current()) return
      if (destination !== 'direct' && !value.startsWith('/')) {
        await api('POST', '/agent/tasks', { conversationId: origin, goal: value, requestKey: request.key, executor,
          target: destination === 'loose' ? { kind: 'new_session' } : { kind: 'project', projectId: destination.slice(8) } })
        invalidateAgentData(agentDataKey('/agent/tasks?conversationId=' + encodeURIComponent(origin)))
        if (current()) { setTarget('direct'); showPanel('tasks') }
      } else {
        const { data } = await api('POST', `/agent/conversations/${encodeURIComponent(origin)}/messages`, { requestKey: request.key, text: request.payload ?? value, attachmentIds: request.attachmentIds, ...(request.okrContext ? { okrContext: request.okrContext } : {}) })
        if (request.attachmentIds.length) attachments.clear(request.scope)
        if (!current()) { inbox?.refresh(); return }
        if (data.kind === 'ui_action') showPanel(data.action === 'tasks' ? 'tasks' : 'memory')
        else if (data.kind === 'commands') showPanel('context')
        else if (data.kind === 'status' || data.kind === 'compaction') showPanel('context')
        else if (data.kind === 'message' && origin === cid) thread.accepted(data, value, request.okrContext)
      }
      if (!current()) { inbox?.refresh(); return }
      if (pending.current === request) { pending.current = null; if (project) localStorage.removeItem(request.scope + ':pending') }
      if (consumeDraft && draftRef.current.trim() === value) { setDraft('', request.scope); try { localStorage.removeItem(request.scope) } catch {} }; setCommandsOpen(false); thread.refresh(); inbox?.refresh(); stick.current = true
      if (consumeDraft && !project) { try { localStorage.removeItem(`roami.agent.draft.${node || 'local'}.new`) } catch {} }
      return true
    } catch (reason) {
      const owner = request?.cid || cid
      if ((!project || project.isCurrent()) && activeScope.current === (request?.scope || draftKey) && (project || activeCID.current === owner || (!activeCID.current && !cid))) {
        setError(agentFailure(reason, t))
      }
    }
    finally { sendingRef.current = false; setSending(false) }
  }
  const action = async (path: string, body: any = {}) => {
    if (project && !project.isCurrent()) return
    try { await api('POST', path, body); thread.refresh(); void loadPanel(); inbox?.refresh() } catch (reason) { message.error(agentFailure(reason, t)) }
  }
  const beginMemory = useCallback((m: AgentMessage) => { setSource(m); setMemoryTitle((m.content.text || '').slice(0, 80)); setMemoryBody(m.content.text || '') }, [])
  const submitRef = useRef(submit); submitRef.current = submit
  const answer = useCallback(async (text: string) => await submitRef.current(text, false, true) === true, [])
  const saveMemory = async () => {
    if (!source || project && !project.isCurrent()) return
    try { await api('POST', '/agent/memories', { title: memoryTitle, body: memoryBody, sourceMessageId: source.id, conversationId: cid }); setSource(null); message.success(t('agent.memorySaved')); void loadPanel() } catch (reason) { message.error(agentFailure(reason, t)) }
  }
  const slash = !commandsDismissed && (commandsOpen || (draft.startsWith('/') && !draft.includes(' ') && !draft.includes('\n')))
    ? ['compact', 'status', 'tasks', 'memory', 'stop', 'help'].filter(name => commandsOpen || ('/' + name).startsWith(draft)) : []
  const addFiles = async (files: File[]) => {
    if (sending || readOnly || project && !project.isCurrent() || !files.length) return
    setTarget('direct')
    if (!await attachments.add(files)) message.error(t('agent.composer.fileLimit'))
  }
  const openCommand = (name: string) => { setCommandsOpen(false); setCommandsDismissed(true); setCommandIndex(0); void submit('/' + name, false) }
  const enqueue = () => {
    if (readOnly || sendingRef.current || attachments.blocked || target !== 'direct' || !cid || (!draft.trim() && !attachments.ids.length)) return
    if (!outbox.enqueue(draft.trim(), attachments.items.flatMap(item => item.reference ? [item.reference] : []))) { message.error(t('agent.outbox.storageFailed')); return }
    changeDraft(''); attachments.clear(); setCommandsOpen(false)
  }
  const queueDraft = !pending.current && !!cid && target === 'direct' && !draft.trim().startsWith('/') && (running || compacting || outbox.items.length > 0)
  const sendDraft = () => { if (queueDraft) enqueue(); else void submit() }
  const composerActions = {
    contextUsage: { cid: historical ? '' : cid, model: `${models.settings?.main?.model || ''}:${models.settings?.main?.contextWindow || ''}`, revision: `${thread.view?.turns.map(turn => turn.id + ':' + turn.state).join(',')}:${thread.view?.messages[thread.view.messages.length - 1]?.id}:${thread.view?.messages[thread.view.messages.length - 1]?.status}:${compact?.state}`, active: running || compacting },
    onContext: () => showPanel('context'),
    models, node, disabled: readOnly || sending, canCompact: !!cid && !readOnly && !compacting && !running,
    canDelegate: !project && !attachments.items.length, onFiles: () => fileInput.current?.click(), onTask: project ? undefined : () => setTarget('loose'),
    onCompact: () => { void submit('/compact', false) },
    onCommands: () => { setCommandsDismissed(false); setCommandsOpen(value => !value); setCommandIndex(0) },
    onSkill: (name: string) => { setTarget('direct'); changeDraft((draft ? draft + '\n\n' : '') + t('agent.composer.skillDraft', { name, path: 'skill://' + name }) + '\n') },
  }
  const moreMenu = { items: [
    ...(rsi.value?.developmentRsi === true ? [{ key: 'improvement', label: t('agent.improvement'), icon: <ClockIcon size={16} /> }] : []),
    { key: 'debug', label: t('agent.debug'), icon: <CodeIcon size={16} /> },
    ...(!wide ? [
      { key: 'memory', label: t('agent.memory'), icon: <NotebookIcon size={16} /> },
    ] : []),
  ], onClick: ({ key }: { key: string }) => { if (key === 'debug' || key === 'improvement') openAgentPage(key); else showPanel(key as 'tasks' | 'memory') } }
  const secondaryActions = <>
    <Dropdown trigger={['click']} menu={moreMenu}><button type="button" className="tt-act" aria-label={t('agent.composer.conversationMenu')}><MoreIcon size={18} /></button></Dropdown>
    <button type="button" className="tt-act agent-bell" aria-label={t('agent.notifications')} onClick={notifications}><BellIcon />{!!inbox?.unread && <span className="agent-badge">{inbox?.unread > 99 ? '99+' : inbox?.unread}</span>}</button>
  </>
  const conversationActions = <>
    <button type="button" className="tt-act" onClick={() => showPanel('tasks')}><ChecklistIcon size={18} />{t('agent.workspace.tasks')}</button>
    {secondaryActions}
  </>
  const panelTitle = panel ? t(`agent.${panel}`) : ''
  const latestUserSeq = useMemo(() => bodies.reduce((seq, m) => m.role === 'user' ? Math.max(seq, m.seq) : seq, 0), [bodies])

  const panelBody = <>

      {panel !== 'memory' && panel !== 'tasks' && panelLoading && <Spin size="small" />}{panel !== 'memory' && panel !== 'tasks' && panelError && <p role="alert">{t('agent.requestFailed')}</p>}
      {panel === 'tasks' && <AgentTasks selectedTask={project ? workspaceTask : undefined} onSelectTask={project ? setWorkspaceTask : undefined} projects={projects} key={`${node || 'local'}:${cid}`} cid={cid} onSession={(session) => { setPanel(null); onSession(session) }} onChanged={() => { thread.refresh(); inbox?.refresh() }} />}
      {panel === 'memory' && <AgentMemory cid={cid} projects={projects} select={(sourceCID, sourceBranch, sourceMessage) => { if (project && sourceCID !== cid) { setError(t('agent.requestFailed')); return }; setPanel(null); select(sourceCID, sourceBranch, sourceMessage) }} />}
      {panel === 'context' && <div className="agent-context">{context?.model && <p>{context.model}</p>}<p>{context ? context.contextWindow ? t('agent.contextUsage', { used: context.estimatedTokens, budget: context.contextWindow }) : t('agent.contextUnknown', { used: context.estimatedTokens }) : t('agent.contextHint')}</p>{context?.contextWindow && <p>{t('agent.contextMeter.threshold', { percent: Math.round((context.compactionRatio ?? 0.75) * 100) })}</p>}{compact && <p role="status">{t('agent.compaction.' + compact.state)}</p>}{summary && <Markdown>{summary}</Markdown>}
        <Button disabled={!cid || readOnly || compacting || running} onClick={() => { void submit('/compact') }}>{t('agent.compactNow')}</Button>
        {compacting && compact && <Button onClick={() => { void action(`/agent/conversations/${encodeURIComponent(cid)}/compactions/${encodeURIComponent(compact.operationId)}/cancel`) }}>{t('agent.cancelCompact')}</Button>}
        <div className="agent-command-list">{['compact', 'status', 'tasks', 'memory', 'stop', 'help'].map((name) => <button className="tt-act" type="button" key={name} onClick={() => { changeDraft('/' + name + (name === 'compact' ? ' ' : '')); setPanel(null) }}><code>/{name}</code><span>{t('agent.command.' + name)}</span></button>)}</div>
      </div>}
  </>

  return <div className="agent-workspace" style={inactive ? { display: 'none' } : undefined}><section className={`agent-chat${dragging ? ' is-dragging' : ''}`} aria-label={t('agent.title')}
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setDragging(true) } }}
    onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
    onDrop={event => { if (event.dataTransfer.files.length) { event.preventDefault(); setDragging(false); void addFiles(Array.from(event.dataTransfer.files)) } }}>
    {!project && !phone && !(wide && workspace.open) && <div className="agent-chat-actions">
      {conversationActions}
      {wide && <button type="button" className="tt-act" aria-label={t('agent.workspace.toggle')} title={t('agent.workspace.title')} aria-pressed={workspace.open} onClick={() => workspace.change({ open: true })}><PanelRightIcon size={18} /></button>}
    </div>}
    {!project && phone && mobileActionsHost && createPortal(
      <>
        <button type="button" className="tt-mobile-topbar-icon" aria-label={t('agent.workspace.tasks')} onClick={() => showPanel('tasks')}><ChecklistIcon size={20} /></button>
        <Dropdown trigger={['click']} menu={moreMenu}><button type="button" className="tt-mobile-topbar-icon" aria-label={t('agent.composer.conversationMenu')}><MoreIcon size={20} /></button></Dropdown>
      </>, mobileActionsHost)}
    {(inbox?.unavailable || thread.failed) && <div className="agent-feedback" role="status"><span>{t(thread.view ? 'agent.reconnecting' : 'agent.unavailable')}</span><button type="button" className="tt-act" aria-label={t('agent.retry')} onClick={() => { inbox?.refresh(); thread.refresh() }}><RefreshIcon /></button></div>}
    {historical && <div className="agent-feedback"><span>{t('agent.historicalBranch')}</span><button type="button" className="tt-act" onClick={() => project ? project.onCurrentBranch?.() : select(mainCID || cid)}>{t('agent.currentConversation')}</button></div>}
    <div className="agent-reading">
      <div className="agent-messages" role="region" aria-label={t('agent.title')} tabIndex={0} data-pagination-edge="start" ref={scroll} onScroll={() => { const element = scroll.current; if (element) { stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; setJumpLatest(!stick.current) } }}>
        <div className="agent-thread conversation-transcript"><AgentPageBoundary earlier more={!!thread.view?.page?.hasMore} loading={!!thread.loadingOlder} failed={!!thread.olderFailed} load={older} />{thread.loading && <Spin />}{history.entries.map(entry => entry.message ? <AgentMessageView key={entry.id} conversationId={cid} branchId={thread.view?.branchId} transformText={project?.displayText} item={entry.message} node={node} focused={entry.id === focusMessage} remember={beginMemory} canAnswer={!readOnly && !sending && entry.message.seq > latestUserSeq && !settledDispatches.has(entry.message.content.sessionReply?.dispatchId || '')} answer={answer} /> : <div key={entry.id} className="agent-execution-steps">{groupExecutionSteps(entry.activities).map(group => group[0].kind === 'tool' ? <AgentActivity key={group[0].id} items={group} onSession={onSession} conversationId={cid} branchId={thread.view?.branchId} /> : <AgentTaskActivity key={group[0].id} items={group} onTask={id => { if (project) { setWorkspaceTask(id); setPanel('tasks') } else if (phone || !wide) openAgentPage('tasks', id); else openWorkspaceTask(id) }} />)}</div>)}</div>
      </div>
      {jumpLatest && <button type="button" className="agent-jump-latest" aria-label={t('agent.composer.latest')} onClick={() => { stick.current = true; scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' }); setJumpLatest(false) }}><ArrowDown size={18} /></button>}
    </div>
    {error && <div className="agent-feedback error" role="alert">{error}</div>}
    <div className="agent-composer">
      <AgentOutbox key={draftKey} outbox={outbox} ready={outboxReady} running={running} />
      <ConversationComposer className="agent-compose-card" value={draft} onChange={value => { changeDraft(value); setCommandsDismissed(false); setCommandIndex(0); if (!value) setCommandsOpen(false) }} label={project?.inputLabel || t('agent.message')} placeholder={project?.placeholder || t(target === 'direct' ? 'agent.placeholder' : 'composer.taskPlaceholder')} maxLength={target === 'direct' ? 100000 : 20000} disabled={readOnly} hasAttachments={!!attachments.ids.length}
        send={{ label: queueDraft ? t('agent.outbox.add') : project?.sendLabel || t(target !== 'direct' ? 'composer.createTask' : 'agent.send'), disabled: sending || attachments.blocked || (target !== 'direct' && draft.trim().length > 20000), pending: sending, icon: queueDraft ? <ClockIcon size={16} /> : undefined, onClick: sendDraft }}
        stop={running && !readOnly ? { label: t('agent.stop'), onClick: () => { void action(`/agent/conversations/${encodeURIComponent(cid)}/messages`, { requestKey: newKey(), text: '/stop' }) } } : undefined}
        attachments={<AgentDraftFiles attachments={attachments} disabled={sending} imagesAvailable={!!models.settings?.main?.images} onError={() => message.error(t('agent.requestFailed'))} />}
        suggestions={<>{slash.length > 0 && <div className="agent-slash" role="listbox" aria-label={t('agent.commands')}>{slash.map((name, index) => <button type="button" key={name} role="option" aria-selected={index === commandIndex % slash.length} onClick={() => { if (commandsOpen) openCommand(name); else void submit('/' + name) }}><code>/{name}</code><span>{t('agent.command.' + name)}</span></button>)}</div>}
          {(compacting || attachments.items.length > 0) && <div className="agent-compose-status"><span role="status">{compacting ? t('agent.compacting') : t('agent.composer.attachmentMode')}</span></div>}</>}
        onPaste={event => { if (event.clipboardData.files.length) { event.preventDefault(); void addFiles(Array.from(event.clipboardData.files)) } }}
        onKeyDown={event => {
          if (slash.length && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)) {
            if (event.key === 'Escape') { event.preventDefault(); setCommandsOpen(false); setCommandsDismissed(true); return }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setCommandIndex(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + slash.length) % slash.length); return }
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (commandsOpen) openCommand(slash[commandIndex % slash.length]); else if (draft === '/' + slash[commandIndex % slash.length]) { void submit() } else { changeDraft('/' + slash[commandIndex % slash.length] + (slash[commandIndex % slash.length] === 'compact' ? ' ' : '')); setCommandsOpen(false) } }
          }
        }}
        leading={<AgentComposerPlus {...composerActions} mode={project ? undefined : { task: target !== 'direct', onChange: task => setTarget(task ? 'loose' : 'direct') }} options={<>
          <Dropdown trigger={['click']} menu={{ selectedKeys: [target], items: [{ key: 'loose', label: t('agent.loose') }, ...projects.map(project => ({ key: 'project:' + project.id, label: project.name }))], onClick: ({ key }) => setTarget(key) }}><button type="button" className="tt-pill sel" aria-label={t('agent.destination')}>{target === 'loose' ? t('agent.loose') : projects.find(project => 'project:' + project.id === target)?.name}<ChevronDown /></button></Dropdown>
          <Dropdown overlayClassName="agent-executor-menu" trigger={['click']} menu={{ selectedKeys: [executor], items: (['codex', 'claude', 'opencode', 'pi'] as const).map(kind => ({ key: kind, label: kind === 'claude' ? 'Claude Code' : agentName(kind), icon: <AgentLogo kind={kind} /> })), onClick: ({ key }) => { if (isAgentKind(key)) setExecutor(key) } }}><button type="button" className="tt-pill sel" aria-label={t('agent.executor')}><AgentLogo kind={executor} />{executor === 'claude' ? 'Claude Code' : agentName(executor)}<ChevronDown /></button></Dropdown></>} />}
        settings={<AgentComposerPlus {...composerActions} modelTrigger />}
        voice={<VoiceInput inline scope={draftKey} hotkey={!inactive} disabled={readOnly || inactive} accent="var(--accent)" onResult={text => changeDraft(draftRef.current + (draftRef.current ? '\n' : '') + text)} />} />
      <input ref={fileInput} type="file" multiple className="agent-file-input" aria-label={t('agent.composer.addFiles')} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; void addFiles(files) }} />
    </div>
    {dragging && <div className="agent-drop-zone"><FileTextIcon size={24} /><span>{t('agent.composer.dropFiles')}</span></div>}
    {project && phone && panel ? <MobileSubPage title={panelTitle} onBack={() => setPanel(null)}><div className="agent-project-panel">{panelBody}</div></MobileSubPage> : <Modal title={panelTitle} open={!!panel} onCancel={() => setPanel(null)} footer={null} destroyOnClose className={panel === 'tasks' ? 'agent-task-dialog' : undefined} wrapClassName={panel === 'tasks' ? 'agent-task-wrap' : undefined} centered={panel === 'tasks'} width={panel === 'tasks' ? 'calc(var(--sp-5) * 32)' : undefined}>{panelBody}</Modal>}
    <Modal destroyOnClose title={t('agent.remember')} open={!!source} onCancel={() => setSource(null)} onOk={() => { void saveMemory() }} okText={t('agent.save')} cancelText={t('common.cancel')} okButtonProps={{ 'aria-label': t('agent.save'), disabled: !memoryBody.trim() || memoryBody.length > 20000 }}>
      <label className="agent-field">{t('agent.memoryTitle')}<Input aria-label={t('agent.memoryTitle')} value={memoryTitle} maxLength={200} onChange={(e) => setMemoryTitle(e.target.value)} /></label>
      <label className="agent-field">{t('agent.memoryBody')}<Input.TextArea aria-label={t('agent.memoryBody')} value={memoryBody} autoSize={{ minRows: 4, maxRows: 10 }} maxLength={20000} onChange={(e) => setMemoryBody(e.target.value)} /></label>
    </Modal>
  </section>
  {inbox && !inactive && wide && workspace.open && <AgentWorkspaceRail key={`${node || 'local'}:${cid}:${thread.view?.branchId || ''}`} cid={cid} connected={thread.connected} actions={secondaryActions} inbox={inbox} tab={workspace.tab} task={workspaceTask} change={tab => { workspace.change({ tab }); setWorkspaceTask('') }} close={() => workspace.change({ open: false })} onTask={openWorkspaceTask} onSession={onSession} onChanged={() => { thread.refresh(); inbox?.refresh() }} projects={projects} select={select} />}
  </div>
}
