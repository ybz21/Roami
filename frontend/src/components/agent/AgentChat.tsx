import { agentTimeline, groupAgentTimeline } from './agent-timeline'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { App, Button, Dropdown, Input, Modal, Spin } from 'antd'
import { api } from '../../api'
import { AgentLogo, ArrowDown, ArrowUp, BellIcon, ChecklistIcon, ChevronDown, ClockIcon, CloseIcon, CodeIcon, FileTextIcon, MoreIcon, NotebookIcon, PanelRightIcon, RefreshIcon, StopIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import Markdown from '../markdown/Markdown'
import AgentMemory from './AgentMemory'
import { openAgentPage } from './agent-page-route'
import AgentTasks from './AgentTasks'
import { taskFailureKey } from './task-failure'
import AgentWorkspaceRail from './AgentWorkspaceRail'
import { useAgentWorkspace } from './useAgentWorkspace'
import './agent-workspace.css'
import { useAgentThread } from './useAgentThread'
import { useAgentData } from './useAgentData'
import { useAgentHistory } from './useAgentHistory'
import { agentDataKey, invalidateAgentData } from './agent-data-cache'
import { useAgentDraft } from './useAgentDraft'
import { useAgentMessageFocus } from './useAgentMessageFocus'
import { useVisibleAgentReads } from './useVisibleAgentReads'
import type { AgentInboxState } from './useAgentInbox'
import type { AgentMessage } from './agent-protocol'
import AgentComposerPlus from './AgentComposerPlus'
import AgentMessageView from './AgentMessageView'
import AgentTaskActivity from './AgentTaskActivity'
import { mainTaskActivities } from './main-task-activity'
import { useAgentAttachments } from './useAgentAttachments'
import { useAgentModels } from './useAgentModels'
import { useAgentOutbox } from './useAgentOutbox'
import AgentOutbox from './AgentOutbox'
import './agent-chat.css'

export function agentFailure(error: any, t: (key: string) => string) {
  const code = error?.apiError?.code || error?.message
  const reason = typeof code === 'string' ? taskFailureKey(code) : undefined
  if (reason) return t(reason)
  return t(code === 'MODEL_NOT_CONFIGURED' ? 'agent.modelMissing' : code === 'BRANCH_BUSY' || code === 'COMPACTION_IN_PROGRESS' ? 'agent.busy' : code === 'NOT_ENOUGH_HISTORY' ? 'agent.compactSkipped' : 'agent.requestFailed')
}
const newKey = () => crypto.randomUUID()

export default function AgentChat({ cid, branch, focusMessage = '', inactive = false, node, inbox, inboxOpen, select, notifications, projects, onSession, mobileActionsHost }: {
  cid: string; branch: string; focusMessage?: string; inactive?: boolean; node: string | null; inbox: AgentInboxState; inboxOpen: boolean
  select: (cid: string, branch?: string, message?: string) => void; notifications: () => void
  projects: { id: string; name: string }[]; onSession: (session: string) => void; onOverview: () => void
  mobileActionsHost?: HTMLElement | null
}) {
  const { t } = useI18n(), { phone, landscape, size } = useLayout(), { message } = App.useApp()
  const thread = useAgentThread(cid, branch, node)
  const rsi = useAgentData<{ developmentRsi: boolean }>('/agent/status', 60_000)
  const workspace = useAgentWorkspace(node), wide = size === 'large'
  const [workspaceTask, setWorkspaceTask] = useState('')
  const openWorkspaceTask = (id: string) => { setWorkspaceTask(id); workspace.change({ open: true, tab: 'tasks' }) }
  const [sending, setSending] = useState(false)
  const [target, setTarget] = useState('direct'), [executor, setExecutor] = useState('codex')
  const [panel, setPanel] = useState<'tasks' | 'memory' | 'context' | null>(null)
  const showPanel = (next: 'tasks' | 'memory' | 'context') => {
    if (phone && next !== 'context') { openAgentPage(next); return }
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
  const pending = useRef<{ text: string; target: string; executor: string; cid: string; key: string; attachmentIds: string[]; scope: string } | null>(null)
  const createKey = useMemo(newKey, [cid, node])
  const mirror = `roami.agent.last.${node || 'local'}`
  const draftKey = `roami.agent.draft.${node || 'local'}.${cid || 'new'}`
  const [draft, setDraft] = useAgentDraft(draftKey)
  const activeScope = useRef(draftKey); activeScope.current = draftKey
  const draftRef = useRef(draft); draftRef.current = draft
  const attachments = useAgentAttachments(draftKey)
  const mainCID = inbox.conversations[0]?.id
  const historical = !!thread.view && (thread.view.branchId !== thread.view.conversation.active_branch_id || (!!mainCID && cid !== mainCID))
  const readOnly = historical || !mainCID
  const running = thread.view?.turns.some((item) => item.state === 'running' || item.state === 'queued') || false
  const compact = thread.view?.compaction
  const compacting = compact?.state === 'queued' || compact?.state === 'running' || compact?.state === 'started'
  const outboxReady = !readOnly && !sending && !compacting && thread.connected && thread.view?.conversation.id === cid
  const outbox = useAgentOutbox(draftKey, outboxReady, !running, async item => {
    const owner = draftKey, origin = cid
    const { data } = await api('POST', `/agent/conversations/${encodeURIComponent(origin)}/messages`, { requestKey: item.id, text: item.text, attachmentIds: item.attachments.map(file => file.id) })
    if (activeScope.current !== owner) return
    if (data.kind === 'message') thread.accepted(data, item.text)
    thread.refresh(); inbox.refresh()
  })
  const bodies = useMemo(() => (thread.view?.messages || []).filter(m => m.role === 'user' || m.role === 'assistant'), [thread.view?.messages])
  const settledDispatches = useMemo(() => new Set(bodies.filter(m => ['completed', 'failed'].includes(m.content.sessionReply?.status || '')).map(m => m.content.sessionReply!.dispatchId)), [bodies])
  const timeline = useMemo(() => groupAgentTimeline(agentTimeline(bodies, mainTaskActivities(thread.view?.activities || []))), [bodies, thread.view?.activities])
  const visible = useMemo(() => bodies.filter(m => m.content.text || m.content.question || m.content.taskStatus || m.content.attachments?.length || m.status === 'streaming'), [bodies])
  const history = useAgentHistory(`${node || 'local'}:${cid}:${branch}:${thread.view?.branchId || ''}`, timeline, focusMessage, scroll)
  const eventIds = history.entries.map(entry => entry.message?.completedEventId || '').join(',')
  useVisibleAgentReads(!inactive && !panel && !source && !inboxOpen ? cid : '', scroll, eventIds, inbox.refresh)

  useEffect(() => {
    if (!inactive && mainCID && !branch && !focusMessage && cid !== mainCID) select(mainCID)
    if (cid === mainCID) { try { localStorage.setItem(mirror, cid) } catch {} }
  }, [cid, mainCID, branch, focusMessage, mirror, select, inactive])

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
    inbox.refresh(); return data.id as string
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
    if ((!value && !attachmentIds.length) || (consumeDraft && attachments.blocked) || sendingRef.current || readOnly || (destination !== 'direct' && !value.startsWith('/') && value.length > 20000)) return
    sendingRef.current = true; setSending(true); setError('')
    if (!pending.current || pending.current.text !== value || pending.current.target !== destination || pending.current.executor !== executor || JSON.stringify(pending.current.attachmentIds) !== JSON.stringify(attachmentIds) || (cid && pending.current.cid !== cid)) pending.current = { text: value, target: destination, executor, cid, key: newKey(), attachmentIds, scope: draftKey }
    const request = pending.current
    try {
      const origin = await ensureConversation()
      request.cid = origin
      const current = () => activeCID.current === origin || (!activeCID.current && !cid)
      if (destination !== 'direct' && !value.startsWith('/')) {
        await api('POST', '/agent/tasks', { conversationId: origin, goal: value, requestKey: request.key, executor,
          target: destination === 'loose' ? { kind: 'new_session' } : { kind: 'project', projectId: destination.slice(8) } })
        invalidateAgentData(agentDataKey('/agent/tasks?conversationId=' + encodeURIComponent(origin)))
        if (current()) { setTarget('direct'); showPanel('tasks') }
      } else {
        const { data } = await api('POST', `/agent/conversations/${encodeURIComponent(origin)}/messages`, { requestKey: request.key, text: value, attachmentIds: request.attachmentIds })
        if (request.attachmentIds.length) attachments.clear(request.scope)
        if (!current()) { inbox.refresh(); return }
        if (data.kind === 'ui_action') showPanel(data.action === 'tasks' ? 'tasks' : 'memory')
        else if (data.kind === 'commands') showPanel('context')
        else if (data.kind === 'status' || data.kind === 'compaction') showPanel('context')
        else if (data.kind === 'message' && origin === cid) thread.accepted(data, value)
      }
      if (!current()) { inbox.refresh(); return }
      if (pending.current === request) pending.current = null
      if (consumeDraft && draftRef.current.trim() === value) { setDraft('', request.scope); try { localStorage.removeItem(request.scope) } catch {} }; setCommandsOpen(false); thread.refresh(); inbox.refresh(); stick.current = true
      if (consumeDraft) { try { localStorage.removeItem(`roami.agent.draft.${node || 'local'}.new`) } catch {} }
      return true
    } catch (reason) {
      const owner = request.cid || cid
      if (activeCID.current === owner || (!activeCID.current && !cid)) {
        setError(agentFailure(reason, t))
      }
    }
    finally { sendingRef.current = false; setSending(false) }
  }
  const action = async (path: string, body: any = {}) => {
    try { await api('POST', path, body); thread.refresh(); void loadPanel(); inbox.refresh() } catch (reason) { message.error(agentFailure(reason, t)) }
  }
  const beginMemory = useCallback((m: AgentMessage) => { setSource(m); setMemoryTitle((m.content.text || '').slice(0, 80)); setMemoryBody(m.content.text || '') }, [])
  const submitRef = useRef(submit); submitRef.current = submit
  const answer = useCallback(async (text: string) => await submitRef.current(text, false, true) === true, [])
  const saveMemory = async () => {
    if (!source) return
    try { await api('POST', '/agent/memories', { title: memoryTitle, body: memoryBody, sourceMessageId: source.id, conversationId: cid }); setSource(null); message.success(t('agent.memorySaved')); void loadPanel() } catch (reason) { message.error(agentFailure(reason, t)) }
  }
  const slash = !commandsDismissed && (commandsOpen || (draft.startsWith('/') && !draft.includes(' ') && !draft.includes('\n')))
    ? ['compact', 'status', 'tasks', 'memory', 'stop', 'help'].filter(name => commandsOpen || ('/' + name).startsWith(draft)) : []
  const addFiles = async (files: File[]) => {
    if (sending || readOnly || !files.length) return
    setTarget('direct')
    if (!await attachments.add(files)) message.error(t('agent.composer.fileLimit'))
  }
  const openCommand = (name: string) => { setCommandsOpen(false); setCommandsDismissed(true); setCommandIndex(0); void submit('/' + name, false) }
  const enqueue = () => {
    if (readOnly || sendingRef.current || attachments.blocked || target !== 'direct' || !cid || (!draft.trim() && !attachments.ids.length)) return
    if (!outbox.enqueue(draft.trim(), attachments.items.flatMap(item => item.reference ? [item.reference] : []))) { message.error(t('agent.outbox.storageFailed')); return }
    changeDraft(''); attachments.clear(); setCommandsOpen(false)
  }
  const queueDraft = !!cid && target === 'direct' && !draft.trim().startsWith('/') && (running || compacting || outbox.items.length > 0)
  const sendDraft = () => { if (queueDraft) enqueue(); else void submit() }
  const composerActions = {
    contextUsage: { cid: historical ? '' : cid, model: `${models.settings?.main.model || ''}:${models.settings?.main.contextWindow || ''}`, revision: `${thread.view?.turns.map(turn => turn.id + ':' + turn.state).join(',')}:${thread.view?.messages[thread.view.messages.length - 1]?.id}:${thread.view?.messages[thread.view.messages.length - 1]?.status}:${compact?.state}`, active: running || compacting },
    onContext: () => showPanel('context'),
    models, node, disabled: readOnly || sending, canCompact: !!cid && !readOnly && !compacting && !running,
    canDelegate: !attachments.items.length, onFiles: () => fileInput.current?.click(), onTask: () => setTarget('loose'),
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
    <button type="button" className="tt-act agent-bell" aria-label={t('agent.notifications')} onClick={notifications}><BellIcon />{!!inbox.unread && <span className="agent-badge">{inbox.unread > 99 ? '99+' : inbox.unread}</span>}</button>
  </>
  const conversationActions = <>
    <button type="button" className="tt-act" onClick={() => showPanel('tasks')}><ChecklistIcon size={18} />{t('agent.workspace.tasks')}</button>
    {secondaryActions}
  </>
  const panelTitle = panel ? t(`agent.${panel}`) : ''
  const latestUserSeq = useMemo(() => bodies.reduce((seq, m) => m.role === 'user' ? Math.max(seq, m.seq) : seq, 0), [bodies])

  return <div className="agent-workspace"><section className={`agent-chat${dragging ? ' is-dragging' : ''}`} aria-label={t('agent.title')}
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setDragging(true) } }}
    onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
    onDrop={event => { if (event.dataTransfer.files.length) { event.preventDefault(); setDragging(false); void addFiles(Array.from(event.dataTransfer.files)) } }}>
    {!phone && !(wide && workspace.open) && <div className="agent-chat-actions">
      {conversationActions}
      {wide && <button type="button" className="tt-act" aria-label={t('agent.workspace.toggle')} title={t('agent.workspace.title')} aria-pressed={workspace.open} onClick={() => workspace.change({ open: true })}><PanelRightIcon size={18} /></button>}
    </div>}
    {phone && mobileActionsHost && createPortal(
      <>
        <button type="button" className="tt-mobile-topbar-icon" aria-label={t('agent.workspace.tasks')} onClick={() => showPanel('tasks')}><ChecklistIcon size={20} /></button>
        <Dropdown trigger={['click']} menu={moreMenu}><button type="button" className="tt-mobile-topbar-icon" aria-label={t('agent.composer.conversationMenu')}><MoreIcon size={20} /></button></Dropdown>
      </>, mobileActionsHost)}
    {(inbox.unavailable || thread.failed) && <div className="agent-feedback" role="status"><span>{t(thread.view ? 'agent.reconnecting' : 'agent.unavailable')}</span><button type="button" className="tt-act" aria-label={t('agent.retry')} onClick={() => { inbox.refresh(); thread.refresh() }}><RefreshIcon /></button></div>}
    {historical && <div className="agent-feedback"><span>{t('agent.historicalBranch')}</span><button type="button" className="tt-act" onClick={() => select(mainCID || cid)}>{t('agent.currentConversation')}</button></div>}
    <div className="agent-reading">
      <div className="agent-messages" ref={scroll} onScroll={() => { const element = scroll.current; if (element) { stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; setJumpLatest(!stick.current); history.expand() } }}>
        <div className="agent-thread">{thread.loading && <Spin />}{history.entries.map(entry => entry.message ? <AgentMessageView key={entry.id} item={entry.message} node={node} focused={entry.id === focusMessage} remember={beginMemory} canAnswer={!readOnly && !sending && entry.message.seq > latestUserSeq && !settledDispatches.has(entry.message.content.sessionReply?.dispatchId || '')} answer={answer} /> : <AgentTaskActivity key={entry.id} items={entry.activities} onTask={id => { if (phone || !wide) openAgentPage('tasks', id); else openWorkspaceTask(id) }} />)}</div>
      </div>
      {jumpLatest && <button type="button" className="agent-jump-latest" aria-label={t('agent.composer.latest')} onClick={() => { stick.current = true; scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' }); setJumpLatest(false) }}><ArrowDown size={18} /></button>}
    </div>
    {error && <div className="agent-feedback error" role="alert">{error}</div>}
    <div className="agent-composer">
      <AgentOutbox key={draftKey} outbox={outbox} ready={outboxReady} running={running} />
      <div className="tt-composer agent-compose-card">
        {!!attachments.items.length && <div className="agent-draft-files">{attachments.items.map(item => <div className={`agent-file-card is-${item.state}`} key={item.key}>
          <FileTextIcon size={20} /><span>{item.name}<small>{t(item.state === 'uploading' ? item.processing ? 'agent.composer.imagePreparing' : 'agent.composer.uploading' : item.state === 'failed' ? item.preparationFailed ? 'agent.composer.imagePrepareFailed' : 'agent.composer.uploadFailed' : item.reference?.previewState === 'unsupported' ? 'agent.composer.fileStoredOnly' : item.reference?.previewState === 'image' && !models.settings?.main.images ? 'agent.composer.imageUnavailable' : ['unavailable', 'encrypted', 'no_text'].includes(item.reference?.previewState || '') ? 'agent.composer.fileUnavailable' : item.optimized ? 'agent.composer.imageOptimized' : 'agent.composer.fileReady')}</small></span>
          {item.state === 'uploading' ? <Spin size="small" /> : <>{item.state === 'failed' && <button type="button" aria-label={t('agent.retry')} disabled={sending} onClick={() => { void attachments.retry(item) }}><RefreshIcon size={15} /></button>}<button type="button" aria-label={t('agent.composer.removeFile', { name: item.name })} disabled={sending} onClick={() => { void attachments.remove(item).catch(() => message.error(t('agent.requestFailed'))) }}><CloseIcon size={15} /></button></>}
        </div>)}</div>}
        <form onSubmit={event => { event.preventDefault(); sendDraft() }}>
          <Input.TextArea variant="borderless" aria-label={t('agent.message')} placeholder={t('agent.placeholder')} value={draft} onChange={event => { changeDraft(event.target.value); setCommandsDismissed(false); setCommandIndex(0); if (!event.target.value) setCommandsOpen(false) }} autoSize={{ minRows: 1, maxRows: !phone ? 8 : landscape ? 1 : 5 }} maxLength={target === 'direct' ? 100000 : 20000} disabled={readOnly}
            onPaste={event => { if (event.clipboardData.files.length) { event.preventDefault(); void addFiles(Array.from(event.clipboardData.files)) } }}
            onKeyDown={event => {
              if (event.nativeEvent.isComposing) return
              if (slash.length && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)) {
                if (event.key === 'Escape') { event.preventDefault(); setCommandsOpen(false); setCommandsDismissed(true); return }
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setCommandIndex(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + slash.length) % slash.length); return }
                if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (commandsOpen) openCommand(slash[commandIndex % slash.length]); else if (draft === '/' + slash[commandIndex % slash.length]) { void submit() } else { changeDraft('/' + slash[commandIndex % slash.length] + (slash[commandIndex % slash.length] === 'compact' ? ' ' : '')); setCommandsOpen(false) }; return }
              }
              if (!phone && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendDraft() }
            }} />
          {slash.length > 0 && <div className="agent-slash" role="listbox" aria-label={t('agent.commands')}>{slash.map((name, index) => <button type="button" key={name} role="option" aria-selected={index === commandIndex % slash.length} onClick={() => { if (commandsOpen) openCommand(name); else void submit('/' + name) }}><code>/{name}</code><span>{t('agent.command.' + name)}</span></button>)}</div>}
          {(compacting || attachments.items.length > 0) && <div className="agent-compose-status"><span role="status">{compacting ? t('agent.compacting') : t('agent.composer.attachmentMode')}</span></div>}
          <div className="tt-cbar agent-compose-bar">
            <div className="tt-cgrp">
              <AgentComposerPlus {...composerActions} />
              {target !== 'direct' && <Dropdown trigger={['click']} menu={{ selectedKeys: [target !== 'direct' ? 'task' : 'direct'], items: [{ key: 'direct', label: t('agent.composer.chatMode') }, { key: 'task', label: t('agent.composer.taskMode'), disabled: !!attachments.items.length }], onClick: ({ key }) => setTarget(key === 'task' ? 'loose' : 'direct') }}><button type="button" className="tt-pill agent-mode-trigger" disabled={readOnly || sending} aria-label={t('agent.composer.mode')}>{t(target !== 'direct' ? 'agent.composer.taskMode' : 'agent.composer.chatMode')}<ChevronDown size={14} /></button></Dropdown>}
            </div>
            <div className="tt-cend">
              <AgentComposerPlus {...composerActions} modelTrigger />
              {running && <button type="button" className={draft.trim() || attachments.items.length ? 'tt-pill ico' : 'tt-send agent-stop'} aria-label={t('agent.stop')} onClick={() => { void action(`/agent/conversations/${encodeURIComponent(cid)}/messages`, { requestKey: newKey(), text: '/stop' }) }}><StopIcon size={16} /></button>}
              {(!running || !!draft.trim() || !!attachments.items.length) && <button type="submit" className="tt-send" aria-label={t(queueDraft ? 'agent.outbox.add' : 'agent.send')} disabled={sending || attachments.blocked || (!draft.trim() && !attachments.ids.length) || readOnly || (target !== 'direct' && draft.trim().length > 20000)}>{sending ? <Spin size="small" /> : queueDraft ? <ClockIcon size={20} /> : <ArrowUp size={20} />}</button>}
            </div>
          </div>
        </form>
        {target !== 'direct' && <div className="agent-task-options">
          <Dropdown trigger={['click']} menu={{ selectedKeys: [target], items: [{ key: 'loose', label: t('agent.loose') }, ...projects.map(project => ({ key: 'project:' + project.id, label: project.name }))], onClick: ({ key }) => setTarget(key) }}><button type="button" className="tt-pill sel" aria-label={t('agent.destination')}>{target === 'loose' ? t('agent.loose') : projects.find(project => 'project:' + project.id === target)?.name}<ChevronDown /></button></Dropdown>
          <Dropdown trigger={['click']} menu={{ selectedKeys: [executor], items: [{ key: 'codex', label: 'Codex', icon: <AgentLogo kind="codex" /> }, { key: 'claude', label: 'Claude Code', icon: <AgentLogo kind="claude" /> }], onClick: ({ key }) => setExecutor(key) }}><button type="button" className="tt-pill sel" aria-label={t('agent.executor')}><AgentLogo kind={executor as 'codex' | 'claude'} />{executor === 'codex' ? 'Codex' : 'Claude Code'}<ChevronDown /></button></Dropdown>
        </div>}
      </div>
      <input ref={fileInput} type="file" multiple className="agent-file-input" aria-label={t('agent.composer.addFiles')} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; void addFiles(files) }} />
    </div>
    {dragging && <div className="agent-drop-zone"><FileTextIcon size={24} /><span>{t('agent.composer.dropFiles')}</span></div>}
    <Modal title={panelTitle} open={!!panel} onCancel={() => setPanel(null)} footer={null} destroyOnClose className={panel === 'tasks' ? 'agent-task-dialog' : undefined} wrapClassName={panel === 'tasks' ? 'agent-task-wrap' : undefined} centered={panel === 'tasks'} width={panel === 'tasks' ? 'calc(var(--sp-5) * 32)' : undefined}>

      {panel !== 'memory' && panel !== 'tasks' && panelLoading && <Spin size="small" />}{panel !== 'memory' && panel !== 'tasks' && panelError && <p role="alert">{t('agent.requestFailed')}</p>}
      {panel === 'tasks' && <AgentTasks key={`${node || 'local'}:${cid}`} cid={cid} onSession={(session) => { setPanel(null); onSession(session) }} onChanged={() => { thread.refresh(); inbox.refresh() }} />}
      {panel === 'memory' && <AgentMemory cid={cid} projects={projects} select={(sourceCID, sourceBranch, sourceMessage) => { setPanel(null); select(sourceCID, sourceBranch, sourceMessage) }} />}
      {panel === 'context' && <div className="agent-context">{context?.model && <p>{context.model}</p>}<p>{context ? context.contextWindow ? t('agent.contextUsage', { used: context.estimatedTokens, budget: context.contextWindow }) : t('agent.contextUnknown', { used: context.estimatedTokens }) : t('agent.contextHint')}</p>{context?.contextWindow && <p>{t('agent.contextMeter.threshold', { percent: Math.round((context.compactionRatio ?? 0.75) * 100) })}</p>}{compact && <p role="status">{t('agent.compaction.' + compact.state)}</p>}{summary && <Markdown>{summary}</Markdown>}
        <Button disabled={!cid || readOnly || compacting || running} onClick={() => { void submit('/compact') }}>{t('agent.compactNow')}</Button>
        {compacting && compact && <Button onClick={() => { void action(`/agent/conversations/${encodeURIComponent(cid)}/compactions/${encodeURIComponent(compact.operationId)}/cancel`) }}>{t('agent.cancelCompact')}</Button>}
        <div className="agent-command-list">{['compact', 'status', 'tasks', 'memory', 'stop', 'help'].map((name) => <button className="tt-act" type="button" key={name} onClick={() => { changeDraft('/' + name + (name === 'compact' ? ' ' : '')); setPanel(null) }}><code>/{name}</code><span>{t('agent.command.' + name)}</span></button>)}</div>
      </div>}
    </Modal>
    <Modal destroyOnClose title={t('agent.remember')} open={!!source} onCancel={() => setSource(null)} onOk={() => { void saveMemory() }} okText={t('agent.save')} cancelText={t('common.cancel')} okButtonProps={{ 'aria-label': t('agent.save'), disabled: !memoryBody.trim() || memoryBody.length > 20000 }}>
      <label className="agent-field">{t('agent.memoryTitle')}<Input aria-label={t('agent.memoryTitle')} value={memoryTitle} maxLength={200} onChange={(e) => setMemoryTitle(e.target.value)} /></label>
      <label className="agent-field">{t('agent.memoryBody')}<Input.TextArea aria-label={t('agent.memoryBody')} value={memoryBody} autoSize={{ minRows: 4, maxRows: 10 }} maxLength={20000} onChange={(e) => setMemoryBody(e.target.value)} /></label>
    </Modal>
  </section>
  {wide && workspace.open && <AgentWorkspaceRail key={`${node || 'local'}:${cid}:${thread.view?.branchId || ''}`} cid={cid} connected={thread.connected} actions={secondaryActions} inbox={inbox} tab={workspace.tab} task={workspaceTask} change={tab => { workspace.change({ tab }); setWorkspaceTask('') }} close={() => workspace.change({ open: false })} onTask={openWorkspaceTask} onSession={onSession} onChanged={() => { thread.refresh(); inbox.refresh() }} projects={projects} select={select} />}
  </div>
}
