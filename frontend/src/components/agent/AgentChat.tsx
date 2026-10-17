import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { App, Button, Input, Modal, Select, Spin } from 'antd'
import { api } from '../../api'
import { ArrowUp, BellIcon, ChecklistIcon, ClockIcon, NotebookIcon, PlusIcon, RefreshIcon, StopIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import Markdown from '../markdown/Markdown'
import { conversationTitle } from './AgentHistory'
import { useAgentThread } from './useAgentThread'
import { useAgentDraft } from './useAgentDraft'
import { useVisibleAgentReads } from './useVisibleAgentReads'
import type { AgentInboxState } from './useAgentInbox'
import type { AgentMessage, AgentTask } from './agent-protocol'
import './agent-chat.css'

export function agentFailure(error: any, t: (key: string) => string) {
  const code = error?.apiError?.code || error?.message
  return t(code === 'MODEL_NOT_CONFIGURED' ? 'agent.modelMissing' : code === 'BRANCH_BUSY' || code === 'COMPACTION_IN_PROGRESS' ? 'agent.busy' : code === 'NOT_ENOUGH_HISTORY' ? 'agent.compactSkipped' : 'agent.requestFailed')
}
const newKey = () => crypto.randomUUID()
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'interrupted'])

export default function AgentChat({ cid, branch, fresh, node, inbox, inboxOpen, select, notifications, projects, onSession, onOverview }: {
  cid: string; branch: string; fresh: boolean; node: string | null; inbox: AgentInboxState; inboxOpen: boolean
  select: (cid: string, branch?: string) => void; notifications: () => void
  projects: { id: string; name: string }[]; onSession: (session: string) => void; onOverview: () => void
}) {
  const { t } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const thread = useAgentThread(cid, branch)
  const [sending, setSending] = useState(false)
  const [target, setTarget] = useState('direct'), [executor, setExecutor] = useState('codex')
  const [panel, setPanel] = useState<'history' | 'tasks' | 'memory' | 'context' | null>(null)
  const [tasks, setTasks] = useState<AgentTask[]>([]), [memories, setMemories] = useState<any[]>([])
  const [context, setContext] = useState<any>(null), [summary, setSummary] = useState('')
  const [panelLoading, setPanelLoading] = useState(false), [panelError, setPanelError] = useState(false)
  const [query, setQuery] = useState(''), [source, setSource] = useState<AgentMessage | null>(null)
  const [memoryTitle, setMemoryTitle] = useState(''), [memoryBody, setMemoryBody] = useState('')
  const [error, setError] = useState('')
  const scroll = useRef<HTMLDivElement>(null), stick = useRef(true), sendingRef = useRef(false)
  const activeCID = useRef(cid); activeCID.current = cid
  const panelRequest = useRef(0)
  const pending = useRef<{ text: string; target: string; executor: string; cid: string; key: string } | null>(null)
  const [creationVersion, setCreationVersion] = useState(0)
  const createKey = useMemo(newKey, [cid, node, creationVersion])
  const mirror = `roami.agent.last.${node || 'local'}`
  const draftKey = `roami.agent.draft.${node || 'local'}.${cid || 'new'}`
  const [draft, setDraft] = useAgentDraft(draftKey)
  const readOnly = !!thread.view && thread.view.branchId !== thread.view.conversation.active_branch_id
  const running = thread.view?.turns.some((item) => item.state === 'running' || item.state === 'queued') || false
  const compact = thread.view?.compaction
  const compacting = compact?.state === 'queued' || compact?.state === 'running' || compact?.state === 'started'
  const visible = (thread.view?.messages || []).filter((m) => (m.role === 'user' || m.role === 'assistant') && (m.content.text || m.status === 'streaming'))
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
  const changeDraft = (value: string) => { setDraft(value); try { localStorage.setItem(draftKey, value) } catch {} }
  const ensureConversation = async () => {
    if (cid) return cid
    const { data } = await api('POST', '/agent/conversations', { requestKey: createKey })
    if (activeCID.current === cid) select(data.id)
    inbox.refresh(); return data.id as string
  }
  const loadPanel = useCallback(async () => {
    if (!panel || panel === 'history' || !cid) return
    const version = ++panelRequest.current
    const current = () => version === panelRequest.current && activeCID.current === cid
    setPanelLoading(true); setPanelError(false)
    try {
      if (panel === 'tasks') { const r = await api('GET', '/agent/tasks?conversationId=' + encodeURIComponent(cid)); if (current()) setTasks(r.data) }
      else if (panel === 'memory') { const r = await api('GET', '/agent/memories?conversationId=' + encodeURIComponent(cid) + '&query=' + encodeURIComponent(query)); if (current()) setMemories(r.data) }
      else {
        const r = await api('GET', `/agent/conversations/${encodeURIComponent(cid)}/context`)
        if (!current()) return
        setContext(r.data); setSummary('')
        if (r.data.snapshotId) { const s = await api('GET', `/agent/conversations/${encodeURIComponent(cid)}/context/snapshots/${encodeURIComponent(r.data.snapshotId)}`); if (current()) setSummary(s.data.summary.text || '') }
      }
    } catch { if (current()) setPanelError(true) } finally { if (current()) setPanelLoading(false) }
  }, [panel, cid, query])
  useEffect(() => {
    let stop = false
    const timer = setTimeout(() => { if (!stop) void loadPanel() }, 150)
    const interval = panel === 'tasks' || panel === 'context' ? setInterval(() => { void loadPanel() }, 3000) : undefined
    return () => { stop = true; panelRequest.current++; clearTimeout(timer); clearInterval(interval) }
  }, [loadPanel, panel])
  const submit = async (text = draft) => {
    const value = text.trim()
    if (!value || sendingRef.current || readOnly || (target !== 'direct' && !value.startsWith('/') && value.length > 20000)) return
    sendingRef.current = true; setSending(true); setError('')
    if (!pending.current || pending.current.text !== value || pending.current.target !== target || pending.current.executor !== executor || (cid && pending.current.cid !== cid)) pending.current = { text: value, target, executor, cid, key: newKey() }
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
        const { data } = await api('POST', `/agent/conversations/${encodeURIComponent(origin)}/messages`, { requestKey: request.key, text: value })
        if (!current()) { inbox.refresh(); return }
        if (data.kind === 'ui_action') setPanel(data.action === 'tasks' ? 'tasks' : 'memory')
        else if (data.kind === 'commands') setPanel('context')
        else if (data.kind === 'status' || data.kind === 'compaction') setPanel('context')
        else if (data.kind === 'message' && origin === cid) thread.accepted(data, value)
      }
      if (!current()) { inbox.refresh(); return }
      if (pending.current === request) pending.current = null
      changeDraft(''); thread.refresh(); inbox.refresh(); stick.current = true
      try { localStorage.removeItem(`roami.agent.draft.${node || 'local'}.new`) } catch {}
    } catch (reason) {
      const owner = request.cid || cid
      if (activeCID.current === owner || (!activeCID.current && !cid)) {
        setDraft(value, `roami.agent.draft.${node || 'local'}.${owner || 'new'}`); setError(agentFailure(reason, t))
        try { localStorage.setItem(`roami.agent.draft.${node || 'local'}.${owner || 'new'}`, value) } catch {}
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
  const slash = draft.startsWith('/') && !draft.includes(' ') && !draft.includes('\n')
    ? ['compact', 'status', 'tasks', 'memory', 'stop', 'help'].filter((name) => ('/' + name).startsWith(draft)) : []
  const panelTitle = panel ? t(`agent.${panel}`) : ''
  const conversation = thread.view?.conversation
  const title = conversation ? conversationTitle(conversation, t('agent.new')) : t('agent.title')
  const reset = () => { changeDraft(''); pending.current = null; setCreationVersion((version) => version + 1); select('') }

  return <section className="agent-chat" aria-label={t('agent.title')}>
    <header className="tt-pagehead agent-pagehead"><div><h2>{title}</h2></div><div className="acts"><button type="button" className="tt-act agent-bell" aria-label={t('agent.notifications')} onClick={notifications}><BellIcon />{!!inbox.unread && <span className="agent-badge">{inbox.unread > 99 ? '99+' : inbox.unread}</span>}</button></div></header>
    <div className="agent-toolbar">
      <button type="button" className="tt-act" onClick={reset} aria-label={t('agent.new')}><PlusIcon /><span>{t('agent.new')}</span></button>
      <button type="button" className="tt-act" onClick={() => setPanel('history')} aria-label={t('agent.history')}><ClockIcon /></button>
      <button type="button" className="tt-act" onClick={() => setPanel('tasks')} aria-label={t('agent.tasks')}><ChecklistIcon /></button>
      <button type="button" className="tt-act" onClick={() => setPanel('memory')} aria-label={t('agent.memory')}><NotebookIcon /></button>
      <button type="button" className="tt-act" disabled={readOnly} onClick={() => setPanel('context')}>{t('agent.context')}</button>
      <button type="button" className="tt-act agent-overview" onClick={onOverview}>{t('agent.overview')}</button>
    </div>
    {(inbox.unavailable || thread.failed) && <div className="agent-feedback" role="status"><span>{t(thread.view ? 'agent.reconnecting' : 'agent.unavailable')}</span><button type="button" className="tt-act" aria-label={t('agent.retry')} onClick={() => { inbox.refresh(); thread.refresh() }}><RefreshIcon /></button></div>}
    {readOnly && <div className="agent-feedback"><span>{t('agent.historicalBranch')}</span><button type="button" className="tt-act" onClick={() => select(cid)}>{t('agent.currentConversation')}</button></div>}
    <div className="agent-messages" ref={scroll} onScroll={() => { const element = scroll.current; if (element) stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80 }}>
      <div className="agent-thread">{thread.loading && <Spin />}{visible.map((m) => <article key={m.id} className={`agent-message ${m.role}`}>
        {m.role === 'assistant' && <div className="agent-author">Roami{m.status === 'streaming' && <Spin size="small" />}</div>}
        {m.content.text && (m.role === 'user' ? <p className="agent-user-text">{m.content.text}</p> : <Markdown>{m.content.text}</Markdown>)}
        {['failed', 'interrupted'].includes(m.status) && <small className="agent-muted">{t('agent.interrupted')}</small>}
        {m.role === 'assistant' && m.status === 'completed' && m.content.text && !m.content.tool_calls?.length && <button type="button" className="tt-act agent-message-action" onClick={() => beginMemory(m)} aria-label={t('agent.remember')}><NotebookIcon />{t('agent.remember')}</button>}
        {m.role === 'assistant' && m.completedEventId && <span className="agent-read-sentinel" data-event-id={m.completedEventId} aria-hidden />}
      </article>)}</div>
    </div>
    {error && <div className="agent-feedback error" role="alert">{error}</div>}
    <div className="agent-composer">
      <div className="agent-compose-options"><Select aria-label={t('agent.destination')} value={target} disabled={readOnly || sending} onChange={setTarget} options={[{ value: 'direct', label: t('agent.automatic') }, { value: 'loose', label: t('agent.loose') }, ...projects.map((p) => ({ value: 'project:' + p.id, label: p.name }))]} />
        {target !== 'direct' && <Select aria-label={t('agent.executor')} value={executor} onChange={setExecutor} options={[{ value: 'codex', label: 'Codex' }, { value: 'claude', label: 'Claude Code' }]} />}
        <span className="agent-muted" role="status">{compacting ? t('agent.compacting') : running ? t('agent.responding') : ''}</span>
      </div>
      {slash.length > 0 && <div className="agent-slash" role="listbox" aria-label={t('agent.commands')}>{slash.map((name) => <button type="button" key={name} role="option" aria-selected={false} onClick={() => changeDraft('/' + name + (name === 'compact' ? ' ' : ''))}><code>/{name}</code><span>{t('agent.command.' + name)}</span></button>)}</div>}
      <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
        <Input.TextArea aria-label={t('agent.message')} placeholder={t('agent.placeholder')} value={draft} onChange={(event) => changeDraft(event.target.value)} autoSize={{ minRows: 1, maxRows: 6 }} maxLength={target === 'direct' ? 100000 : 20000} disabled={readOnly}
          onKeyDown={(event) => { if (!phone && event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit() } }} />
        {running && <Button htmlType="button" aria-label={t('agent.stop')} icon={<StopIcon />} onClick={() => { void action(`/agent/conversations/${encodeURIComponent(cid)}/messages`, { requestKey: newKey(), text: '/stop' }) }} />}
        <Button type="primary" htmlType="submit" icon={<ArrowUp size={18} />} aria-label={t('agent.send')} loading={sending} disabled={!draft.trim() || readOnly || (target !== 'direct' && !draft.startsWith('/') && draft.trim().length > 20000)} />
      </form>
    </div>
    <Modal title={panelTitle} open={!!panel} onCancel={() => setPanel(null)} footer={null} destroyOnClose>
      {panel === 'history' && <div className="agent-panel-list">{inbox.conversations.map((c) => <button className="agent-panel-row" type="button" data-conversation-id={c.id} key={c.id} onClick={() => { select(c.id); setPanel(null) }}>{conversationTitle(c, t('agent.new'))}{inbox.notices.some((n) => n.conversation_id === c.id) && <i className="agent-unread-dot" />}</button>)}</div>}
      {panelLoading && <Spin size="small" />}{panelError && <p role="alert">{t('agent.requestFailed')}</p>}
      {panel === 'tasks' && <div className="agent-panel-list">{!tasks.length && !panelLoading && <p className="agent-muted">{t('agent.noTasks')}</p>}{tasks.map((task) => <div key={task.id} className="agent-task"><b>{JSON.parse(task.intent_json).goal}</b><span className="agent-muted">{t('agent.state.' + task.state)}</span>{task.latestAttempt?.workspace && <code>{task.latestAttempt.workspace.branch || task.latestAttempt.workspace.directory}</code>}<div className="agent-task-actions">{task.latestAttempt?.sessionId && <Button onClick={() => { setPanel(null); onSession(task.latestAttempt!.sessionId!) }}>{t('agent.openSession')}</Button>}{!terminal.has(task.state) && <Button danger disabled={task.state === 'cancelling'} onClick={() => { void action(`/agent/tasks/${encodeURIComponent(task.id)}/cancel`) }}>{t('agent.cancelTask')}</Button>}</div></div>)}</div>}
      {panel === 'memory' && <><Input.Search aria-label={t('agent.searchMemory')} placeholder={t('agent.searchMemory')} value={query} onChange={(e) => setQuery(e.target.value)} /><div className="agent-panel-list">{!memories.length && !panelLoading && <p className="agent-muted">{t('agent.noMemories')}</p>}{memories.map((m) => <div key={m.id} className="agent-task"><b>{m.title}</b><p>{m.body}</p><Button danger onClick={async () => { try { await api('DELETE', `/agent/memories/${encodeURIComponent(m.id)}`); void loadPanel() } catch (reason) { message.error(agentFailure(reason, t)) } }}>{t('agent.forget')}</Button></div>)}</div></>}
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
