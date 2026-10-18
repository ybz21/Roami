import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { App, Button, Dropdown, Input, Modal, Spin } from 'antd'
import { api } from '../../api'
import { AgentLogo, ArchiveIcon, ArrowDown, ArrowUp, BellIcon, BotIcon, ChecklistIcon, ChevronDown, ClockIcon, CloseIcon, CodeIcon, FileTextIcon, MoreIcon, NotebookIcon, PencilIcon, RefreshIcon, StopIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import Markdown from '../markdown/Markdown'
import AgentMemory from './AgentMemory'
import AgentTasks from './AgentTasks'
import { conversationTitle } from './AgentHistory'
import { useAgentThread } from './useAgentThread'
import { useAgentDraft } from './useAgentDraft'
import { useAgentMessageFocus } from './useAgentMessageFocus'
import { useVisibleAgentReads } from './useVisibleAgentReads'
import type { AgentInboxState } from './useAgentInbox'
import type { AgentActivityItem, AgentMessage } from './agent-protocol'
import AgentComposerPlus from './AgentComposerPlus'
import AgentMessageView from './AgentMessageView'
import AgentActivity from './AgentActivity'
import { useAgentAttachments } from './useAgentAttachments'
import { useAgentModels } from './useAgentModels'
import './agent-chat.css'

export function agentFailure(error: any, t: (key: string) => string) {
  const code = error?.apiError?.code || error?.message
  return t(code === 'MODEL_NOT_CONFIGURED' ? 'agent.modelMissing' : code === 'BRANCH_BUSY' || code === 'COMPACTION_IN_PROGRESS' ? 'agent.busy' : code === 'NOT_ENOUGH_HISTORY' ? 'agent.compactSkipped' : 'agent.requestFailed')
}
const newKey = () => crypto.randomUUID()

export default function AgentChat({ cid, branch, focusMessage = '', fresh, node, inbox, inboxOpen, select, notifications, projects, onSession, onOverview }: {
  cid: string; branch: string; focusMessage?: string; fresh: boolean; node: string | null; inbox: AgentInboxState; inboxOpen: boolean
  select: (cid: string, branch?: string) => void; notifications: () => void
  projects: { id: string; name: string }[]; onSession: (session: string) => void; onOverview: () => void
}) {
  const { t } = useI18n(), { phone, landscape } = useLayout(), { message } = App.useApp()
  const thread = useAgentThread(cid, branch)
  const [sending, setSending] = useState(false)
  const [target, setTarget] = useState('direct'), [executor, setExecutor] = useState('codex')
  const [panel, setPanel] = useState<'history' | 'tasks' | 'memory' | 'context' | null>(null)
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
  const [creationVersion, setCreationVersion] = useState(0)
  const createKey = useMemo(newKey, [cid, node, creationVersion])
  const mirror = `roami.agent.last.${node || 'local'}`
  const draftKey = `roami.agent.draft.${node || 'local'}.${cid || 'new'}`
  const [draft, setDraft] = useAgentDraft(draftKey)
  const attachments = useAgentAttachments(draftKey)
  const readOnly = !!thread.view && thread.view.branchId !== thread.view.conversation.active_branch_id
  const running = thread.view?.turns.some((item) => item.state === 'running' || item.state === 'queued') || false
  const compact = thread.view?.compaction
  const compacting = compact?.state === 'queued' || compact?.state === 'running' || compact?.state === 'started'
  const activity = thread.view?.activities || []
  const bodies = (thread.view?.messages || []).filter(m => (m.role === 'user' || m.role === 'assistant'))
  const activityAnchors = new Map<string, string>(), activityGroups = new Map<string, AgentActivityItem[]>()
  let lastBody = ''
  for (const m of bodies) {
    if (m.content.text || m.content.taskStatus || m.content.attachments?.length || m.status === 'streaming') lastBody = m.id
    activityAnchors.set(m.id, lastBody || m.id)
  }
  for (const item of activity) {
    const anchor = activityAnchors.get(item.anchorMessageId) || item.anchorMessageId
    activityGroups.set(anchor, [...(activityGroups.get(anchor) || []), item])
  }
  const visible = bodies.filter(m => m.content.text || m.content.taskStatus || m.content.attachments?.length || m.status === 'streaming' || activityGroups.has(m.id))
  const eventIds = visible.map((m) => m.completedEventId || '').join(',')
  useVisibleAgentReads(!panel && !source && !inboxOpen ? cid : '', scroll, eventIds, inbox.refresh)

  useEffect(() => {
    if (cid) { try { localStorage.setItem(mirror, cid) } catch {} }
    else if (!fresh && inbox.conversations.length) {
      let saved = ''
      try { saved = localStorage.getItem(mirror) || '' } catch {}
      select(inbox.conversations.some((c) => c.id === saved) ? saved : inbox.conversations[0].id)
    }
  }, [cid, fresh, mirror, inbox.conversations, select])
  useEffect(() => {
    stick.current = true; setError(''); setPanel(null); setSource(null); panelRequest.current++
    if (!sendingRef.current || pending.current?.cid !== cid) {
      setTarget('direct')
    }
  }, [draftKey])
  useEffect(() => { if (stick.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight }, [thread.view?.messages, cid])
  useAgentMessageFocus(scroll, cid, branch, focusMessage, visible.map((item) => item.id).join(','), stick)
  const changeDraft = (value: string) => { setDraft(value); try { localStorage.setItem(draftKey, value) } catch {} }
  const ensureConversation = async () => {
    if (cid) return cid
    const { data } = await api('POST', '/agent/conversations', { requestKey: createKey })
    if (activeCID.current === cid) {
      const destination = `roami.agent.draft.${node || 'local'}.${data.id}`
      attachments.transfer(destination)
      setDraft(draft, destination)
      try { localStorage.setItem(destination, draft); localStorage.removeItem(draftKey) } catch {}
      if (pending.current?.scope === draftKey) pending.current.scope = destination
      select(data.id)
    }
    inbox.refresh(); return data.id as string
  }
  const loadPanel = useCallback(async () => {
    if (!panel || panel === 'history' || panel === 'memory' || panel === 'tasks' || !cid) return
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
  const submit = async (text = draft, consumeDraft = true) => {
    const attachmentIds = consumeDraft ? attachments.ids : []
    const value = text.trim()
    if ((!value && !attachmentIds.length) || (consumeDraft && attachments.blocked) || sendingRef.current || readOnly || (target !== 'direct' && !value.startsWith('/') && value.length > 20000)) return
    sendingRef.current = true; setSending(true); setError('')
    if (!pending.current || pending.current.text !== value || pending.current.target !== target || pending.current.executor !== executor || JSON.stringify(pending.current.attachmentIds) !== JSON.stringify(attachmentIds) || (cid && pending.current.cid !== cid)) pending.current = { text: value, target, executor, cid, key: newKey(), attachmentIds, scope: draftKey }
    const request = pending.current
    try {
      const origin = await ensureConversation()
      request.cid = origin
      const current = () => activeCID.current === origin || (!activeCID.current && !cid)
      if (target !== 'direct' && !value.startsWith('/')) {
        await api('POST', '/agent/tasks', { conversationId: origin, goal: value, requestKey: request.key, executor,
          target: target === 'loose' ? { kind: 'new_session' } : { kind: 'project', projectId: target.slice(8) } })
        if (current()) { setTarget('direct'); setPanel('tasks') }
      } else {
        const { data } = await api('POST', `/agent/conversations/${encodeURIComponent(origin)}/messages`, { requestKey: request.key, text: value, attachmentIds: request.attachmentIds })
        if (request.attachmentIds.length) attachments.clear(request.scope)
        if (!current()) { inbox.refresh(); return }
        if (data.kind === 'ui_action') setPanel(data.action === 'tasks' ? 'tasks' : 'memory')
        else if (data.kind === 'commands') setPanel('context')
        else if (data.kind === 'status' || data.kind === 'compaction') setPanel('context')
        else if (data.kind === 'message' && origin === cid) thread.accepted(data, value)
      }
      if (!current()) { inbox.refresh(); return }
      if (pending.current === request) pending.current = null
      if (consumeDraft) { setDraft('', request.scope); try { localStorage.removeItem(request.scope) } catch {} }; setCommandsOpen(false); thread.refresh(); inbox.refresh(); stick.current = true
      if (consumeDraft) { try { localStorage.removeItem(`roami.agent.draft.${node || 'local'}.new`) } catch {} }
    } catch (reason) {
      const owner = request.cid || cid
      if (activeCID.current === owner || (!activeCID.current && !cid)) {
        if (consumeDraft) setDraft(value, `roami.agent.draft.${node || 'local'}.${owner || 'new'}`); setError(agentFailure(reason, t))
        if (consumeDraft) { try { localStorage.setItem(`roami.agent.draft.${node || 'local'}.${owner || 'new'}`, value) } catch {} }
      }
    }
    finally { sendingRef.current = false; setSending(false) }
  }
  const action = async (path: string, body: any = {}) => {
    try { await api('POST', path, body); thread.refresh(); void loadPanel(); inbox.refresh() } catch (reason) { message.error(agentFailure(reason, t)) }
  }
  const beginMemory = (m: AgentMessage) => { setSource(m); setMemoryTitle((m.content.text || '').slice(0, 80)); setMemoryBody(m.content.text || '') }
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
  const moreMenu = { items: [
    { key: 'history', label: t('agent.history'), icon: <ClockIcon size={16} /> },
    { key: 'tasks', label: t('agent.tasks'), icon: <ChecklistIcon size={16} /> },
    { key: 'memory', label: t('agent.memory'), icon: <NotebookIcon size={16} /> },
    { key: 'context', label: t('agent.context'), icon: <ArchiveIcon size={16} /> },
    { key: 'overview', label: t('agent.overview'), icon: <BotIcon size={16} /> },
  ], onClick: ({ key }: { key: string }) => { if (key === 'overview') onOverview(); else setPanel(key as 'history' | 'tasks' | 'memory' | 'context') } }
  const panelTitle = panel ? t(`agent.${panel}`) : ''
  const conversation = thread.view?.conversation
  const title = conversation ? conversationTitle(conversation, t('agent.new')) : t('agent.title')
  const reset = () => { changeDraft(''); pending.current = null; setCreationVersion((version) => version + 1); select('') }

  return <section className={`agent-chat${dragging ? ' is-dragging' : ''}`} aria-label={t('agent.title')}
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setDragging(true) } }}
    onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
    onDrop={event => { if (event.dataTransfer.files.length) { event.preventDefault(); setDragging(false); void addFiles(Array.from(event.dataTransfer.files)) } }}>
    <header className="tt-pagehead agent-pagehead"><div><h2>{title}</h2></div><div className="acts">
      <button type="button" className="tt-act" onClick={reset} aria-label={t('agent.new')}><PencilIcon size={18} /></button>
      <Dropdown trigger={['click']} menu={moreMenu}><button type="button" className="tt-act" aria-label={t('agent.composer.conversationMenu')}><MoreIcon size={18} /></button></Dropdown>
      <button type="button" className="tt-act agent-bell" aria-label={t('agent.notifications')} onClick={notifications}><BellIcon />{!!inbox.unread && <span className="agent-badge">{inbox.unread > 99 ? '99+' : inbox.unread}</span>}</button>
    </div></header>
    <div className="agent-mobile-actions">
      <button type="button" className="agent-conversation-title" onClick={() => setPanel('history')} aria-label={t('agent.history')}>{title}<ChevronDown size={13} /></button>
      <button type="button" className="tt-act" onClick={reset} aria-label={t('agent.new')}><PencilIcon size={18} /></button>
      <Dropdown trigger={['click']} menu={moreMenu}><button type="button" className="tt-act" aria-label={t('agent.composer.conversationMenu')}><MoreIcon size={18} /></button></Dropdown>
    </div>
    {(inbox.unavailable || thread.failed) && <div className="agent-feedback" role="status"><span>{t(thread.view ? 'agent.reconnecting' : 'agent.unavailable')}</span><button type="button" className="tt-act" aria-label={t('agent.retry')} onClick={() => { inbox.refresh(); thread.refresh() }}><RefreshIcon /></button></div>}
    {readOnly && <div className="agent-feedback"><span>{t('agent.historicalBranch')}</span><button type="button" className="tt-act" onClick={() => select(cid)}>{t('agent.currentConversation')}</button></div>}
    <div className="agent-reading">
      <div className="agent-messages" ref={scroll} onScroll={() => { const element = scroll.current; if (element) { stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; setJumpLatest(!stick.current) } }}>
        <div className="agent-thread">{thread.loading && <Spin />}{visible.map(m => <Fragment key={m.id}>{(m.content.text || m.content.taskStatus || m.content.attachments?.length || m.status === 'streaming') && <AgentMessageView item={m} focused={m.id === focusMessage} remember={beginMemory} />}<AgentActivity items={activityGroups.get(m.id) || []} onSession={onSession} /></Fragment>)}</div>
      </div>
      {jumpLatest && <button type="button" className="agent-jump-latest" aria-label={t('agent.composer.latest')} onClick={() => { stick.current = true; scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' }); setJumpLatest(false) }}><ArrowDown size={18} /></button>}
    </div>
    {error && <div className="agent-feedback error" role="alert">{error}</div>}
    <div className="agent-composer">
      <div className="tt-composer agent-compose-card">
        {!!attachments.items.length && <div className="agent-draft-files">{attachments.items.map(item => <div className={`agent-file-card is-${item.state}`} key={item.key}>
          <FileTextIcon size={20} /><span>{item.name}<small>{t(item.state === 'uploading' ? 'agent.composer.uploading' : item.state === 'failed' ? 'agent.composer.uploadFailed' : item.reference?.previewState === 'unsupported' ? 'agent.composer.fileStoredOnly' : item.reference?.previewState === 'image' && !models.settings?.main.images ? 'agent.composer.imageUnavailable' : ['unavailable', 'encrypted', 'no_text'].includes(item.reference?.previewState || '') ? 'agent.composer.fileUnavailable' : 'agent.composer.fileReady')}</small></span>
          {item.state === 'uploading' ? <Spin size="small" /> : <>{item.state === 'failed' && <button type="button" aria-label={t('agent.retry')} disabled={sending} onClick={() => { void attachments.retry(item) }}><RefreshIcon size={15} /></button>}<button type="button" aria-label={t('agent.composer.removeFile', { name: item.name })} disabled={sending} onClick={() => { void attachments.remove(item).catch(() => message.error(t('agent.requestFailed'))) }}><CloseIcon size={15} /></button></>}
        </div>)}</div>}
        <form onSubmit={event => { event.preventDefault(); void submit() }}>
          <Input.TextArea variant="borderless" aria-label={t('agent.message')} placeholder={t('agent.placeholder')} value={draft} onChange={event => { changeDraft(event.target.value); setCommandsDismissed(false); setCommandIndex(0); if (!event.target.value) setCommandsOpen(false) }} autoSize={{ minRows: 1, maxRows: !phone ? 8 : landscape ? 1 : 5 }} maxLength={target === 'direct' ? 100000 : 20000} disabled={readOnly}
            onPaste={event => { if (event.clipboardData.files.length) { event.preventDefault(); void addFiles(Array.from(event.clipboardData.files)) } }}
            onKeyDown={event => {
              if (event.nativeEvent.isComposing) return
              if (slash.length && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)) {
                if (event.key === 'Escape') { event.preventDefault(); setCommandsOpen(false); setCommandsDismissed(true); return }
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setCommandIndex(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + slash.length) % slash.length); return }
                if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (commandsOpen) openCommand(slash[commandIndex % slash.length]); else if (draft === '/' + slash[commandIndex % slash.length]) { void submit() } else { changeDraft('/' + slash[commandIndex % slash.length] + (slash[commandIndex % slash.length] === 'compact' ? ' ' : '')); setCommandsOpen(false) }; return }
              }
              if (!phone && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() }
            }} />
          {slash.length > 0 && <div className="agent-slash" role="listbox" aria-label={t('agent.commands')}>{slash.map((name, index) => <button type="button" key={name} role="option" aria-selected={index === commandIndex % slash.length} onClick={() => { if (commandsOpen) openCommand(name); else void submit('/' + name) }}><code>/{name}</code><span>{t('agent.command.' + name)}</span></button>)}</div>}
          <div className="tt-cbar agent-compose-bar">
            <div className="tt-cgrp">
              <AgentComposerPlus models={models} disabled={readOnly || sending} canCompact={!!cid && !readOnly && !compacting && !running} onFiles={() => fileInput.current?.click()} onCompact={() => { void submit('/compact', false) }} onCommands={() => { setCommandsDismissed(false); setCommandsOpen(value => !value); setCommandIndex(0) }} />
              {phone ? <Dropdown trigger={['click']} menu={{ selectedKeys: [target === 'direct' ? 'direct' : 'task'], items: [{ key: 'direct', label: t('agent.composer.chatMode') }, { key: 'task', label: t('agent.composer.taskMode'), disabled: !!attachments.items.length }], onClick: ({ key }) => setTarget(key === 'direct' ? 'direct' : 'loose') }}><button type="button" className="tt-pill agent-mode-trigger" disabled={readOnly || sending} aria-label={t('agent.composer.mode')}>{t(target === 'direct' ? 'agent.composer.chatMode' : 'agent.composer.taskMode')}<ChevronDown size={14} /></button></Dropdown> : <div className="agent-send-modes" role="group" aria-label={t('agent.composer.mode')}>
                <button type="button" className={`tt-pill${target === 'direct' ? ' on' : ''}`} aria-pressed={target === 'direct'} disabled={readOnly || sending} onClick={() => setTarget('direct')}>{t('agent.composer.chatMode')}</button>
                <button type="button" className={`tt-pill${target !== 'direct' ? ' on' : ''}`} aria-pressed={target !== 'direct'} disabled={readOnly || sending || !!attachments.items.length} onClick={() => setTarget('loose')}>{t('agent.composer.taskMode')}</button>
              </div>}
            </div>
            <div className="tt-cend">
              <AgentComposerPlus models={models} modelTrigger disabled={readOnly || sending} canCompact={!!cid && !readOnly && !compacting && !running} onFiles={() => fileInput.current?.click()} onCompact={() => { void submit('/compact', false) }} onCommands={() => { setCommandsDismissed(false); setCommandsOpen(value => !value) }} />
              {running && <button type="button" className={draft.trim() || attachments.items.length ? 'tt-pill ico' : 'tt-send agent-stop'} aria-label={t('agent.stop')} onClick={() => { void action(`/agent/conversations/${encodeURIComponent(cid)}/messages`, { requestKey: newKey(), text: '/stop' }) }}><StopIcon size={16} /></button>}
              {(!running || !!draft.trim() || !!attachments.items.length) && <button type="submit" className="tt-send" aria-label={t('agent.send')} disabled={sending || attachments.blocked || (!draft.trim() && !attachments.ids.length) || readOnly || (target !== 'direct' && draft.trim().length > 20000)}>{sending ? <Spin size="small" /> : <ArrowUp size={20} />}</button>}
            </div>
          </div>
        </form>
        {target !== 'direct' && <div className="agent-task-options">
          <Dropdown trigger={['click']} menu={{ selectedKeys: [target], items: [{ key: 'loose', label: t('agent.loose') }, ...projects.map(project => ({ key: 'project:' + project.id, label: project.name }))], onClick: ({ key }) => setTarget(key) }}><button type="button" className="tt-pill sel" aria-label={t('agent.destination')}>{target === 'loose' ? t('agent.loose') : projects.find(project => 'project:' + project.id === target)?.name}<ChevronDown /></button></Dropdown>
          <Dropdown trigger={['click']} menu={{ selectedKeys: [executor], items: [{ key: 'codex', label: 'Codex', icon: <AgentLogo kind="codex" /> }, { key: 'claude', label: 'Claude Code', icon: <AgentLogo kind="claude" /> }], onClick: ({ key }) => setExecutor(key) }}><button type="button" className="tt-pill sel" aria-label={t('agent.executor')}><AgentLogo kind={executor as 'codex' | 'claude'} />{executor === 'codex' ? 'Codex' : 'Claude Code'}<ChevronDown /></button></Dropdown>
        </div>}
      </div>
      {(compacting || attachments.items.length > 0) && <div className="agent-compose-footnote" role="status">{compacting ? t('agent.compacting') : t('agent.composer.attachmentMode')}</div>}
      <input ref={fileInput} type="file" multiple className="agent-file-input" aria-label={t('agent.composer.addFiles')} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; void addFiles(files) }} />
    </div>
    {dragging && <div className="agent-drop-zone"><FileTextIcon size={24} /><span>{t('agent.composer.dropFiles')}</span></div>}
    <Modal title={panelTitle} open={!!panel} onCancel={() => setPanel(null)} footer={null} destroyOnClose className={panel === 'tasks' ? 'agent-task-dialog' : undefined} wrapClassName={panel === 'tasks' ? 'agent-task-wrap' : undefined} centered={panel === 'tasks'} width={panel === 'tasks' ? 'calc(var(--sp-5) * 32)' : undefined}>
      {panel === 'history' && <div className="agent-panel-list">{inbox.conversations.map((c) => <button className="agent-panel-row" type="button" data-conversation-id={c.id} key={c.id} onClick={() => { select(c.id); setPanel(null) }}>{conversationTitle(c, t('agent.new'))}{inbox.notices.some((n) => n.conversation_id === c.id) && <i className="agent-unread-dot" />}</button>)}</div>}
      {panel !== 'memory' && panel !== 'tasks' && panelLoading && <Spin size="small" />}{panel !== 'memory' && panel !== 'tasks' && panelError && <p role="alert">{t('agent.requestFailed')}</p>}
      {panel === 'tasks' && <AgentTasks key={`${node || 'local'}:${cid}`} cid={cid} onSession={(session) => { setPanel(null); onSession(session) }} onChanged={() => { thread.refresh(); inbox.refresh() }} />}
      {panel === 'memory' && <AgentMemory cid={cid} projects={projects} select={(sourceCID) => { setPanel(null); select(sourceCID) }} />}
      {panel === 'context' && <div className="agent-context">{context?.model && <p>{context.model}</p>}<p>{context ? t('agent.contextUsage', { used: context.estimatedTokens, budget: context.inputBudget }) : t('agent.contextHint')}</p>{compact && <p role="status">{t('agent.compaction.' + compact.state)}</p>}{summary && <Markdown>{summary}</Markdown>}
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
}
