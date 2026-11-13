import { usePageEffect } from '../../page-activity'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Dropdown, Modal, Spin } from 'antd'
import { RoamiLogo, ChevronRight, PlusIcon } from '../../icons'
import ConversationComposer from '../chat/ConversationComposer'
import VoiceInput from '../chat/VoiceInput'
import AgentModelPicker from './AgentModelPicker'
import { useAgentModels } from './useAgentModels'
import { TaskProcess } from './AgentTaskRecord'
import { TaskResult } from './TaskOutput'
import NativeSessionArtifacts from './NativeSessionArtifacts'
import './agent-tasks.css'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import NativeConversation from './NativeConversation'
import { agentDataKey } from './agent-data-cache'
import { openAgentPage } from './agent-page-route'
import type { AgentMessage, AgentSnapshot } from './agent-protocol'
import RenameSessionModal from '../sessions/RenameSessionModal'
import { nativeSessionName } from '../sessions/session-record'
import { updateSessionLabel, useSessionLabel } from '../sessions/session-label'
import { taskFailureKey } from './task-failure'
import { taskSessionError } from './task-session-error'
import { useBoundaryLoad } from './useBoundaryLoad'
import { useAgentData } from './useAgentData'
import { useAgentDraft } from './useAgentDraft'
import { useAgentTask } from './useAgentTask'
import './native-session.css'

type Metadata = { nativeSessionId: string; taskId: string; projectId?: string; title?: string; conversationId?: string; branchId?: string; revision?: number; lifecycle?: string }
type Page = AgentSnapshot & { before: number | null }

export default function NativeSession({ id, node, projects, onChanged, onSession, embedded = false, expectedTask }: { expectedTask?: { id: string; projectId?: string; conversationId: string; branchId: string; revision: number }; id: string; node: string | null; embedded?: boolean; projects: { id: string; name: string }[]; onChanged: () => void; onSession?: (id: string) => void }) {
  const { t } = useI18n()
  const session = useAgentData<Metadata>('/agent/native-sessions/' + encodeURIComponent(id), 0)
  useEffect(() => { if (session.value?.title) updateSessionLabel(nativeSessionName(id), session.value.title) }, [id, session.value?.title])
  const matches = !expectedTask || session.value?.nativeSessionId === id && session.value.taskId === expectedTask.id && (!expectedTask.projectId || session.value.projectId === expectedTask.projectId) && session.value.conversationId === expectedTask.conversationId && session.value.branchId === expectedTask.branchId && session.value.revision === expectedTask.revision && session.value.lifecycle === 'open'
  return <>{session.value && !matches && <p role="alert">{t('swarm.member.sessionUnavailable')} <button type="button" className="tt-act" onClick={session.refresh}>{t('agent.retry')}</button></p>}{session.loading && <Spin />}{session.failed && <p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={session.refresh}>{t('agent.retry')}</button></p>}{session.value && matches && <SessionConversation key={agentDataKey('/agent/native-sessions/' + id)} embedded={embedded} metadata={session.value} refreshMetadata={session.refresh} node={node} projects={projects} onChanged={onChanged} onSession={onSession} />}</>
}

function SessionConversation({ embedded, metadata, refreshMetadata, node, projects, onChanged, onSession }: { embedded?: boolean; metadata: Metadata; refreshMetadata: () => void; node: string | null; projects: { id: string; name: string }[]; onChanged: () => void; onSession?: (id: string) => void }) {
  const { t } = useI18n(), snapshot = useAgentTask(metadata.taskId), models = useAgentModels(node, 'worker')
  const sessionName = nativeSessionName(metadata.nativeSessionId), savedLabel = useSessionLabel(sessionName)
  const title = savedLabel !== sessionName ? savedLabel : metadata.title || 'Roami'
  const detail = snapshot.detail.value, task = detail?.task
  const closed = detail?.sessionClosure?.state === 'closed'
  const closing = detail?.sessionClosure?.state === 'closing'
  const closeError = ['failed', 'unknown'].includes(detail?.sessionClosure?.state || '') ? taskSessionError(detail?.sessionClosure?.error_code || undefined, t) : ''
  const active = !!task && ['queued', 'preparing', 'running', 'verifying', 'cancelling'].includes(task.state)
  const path = '/agent/native-sessions/' + encodeURIComponent(metadata.nativeSessionId) + '/conversation'
  const conversation = useAgentData<Page>(path, 0, active ? 3000 : 0)
  const [tab, setTab] = useState('conversation'), [renaming, setRenaming] = useState(false)
  const positions = useRef<Record<string, number>>({})
  const [older, setOlder] = useState<AgentMessage[]>([]), [before, setBefore] = useState<number | null | undefined>()
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [confirm, setConfirm] = useState(false)
  const draftKey = 'roami.native.draft.' + agentDataKey(path)
  const [draft, edit] = useAgentDraft(draftKey)
  const scroll = useRef<HTMLDivElement>(null), follow = useRef(true), prepend = useRef<number | null>(null)
  const draftRef = useRef(draft); draftRef.current = draft
  const pending = useRef<{ text: string; revision: number; key: string } | null>(null), sending = useRef(false), alive = useRef(true)
  const olderRequest = useRef<AbortController | null>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  usePageEffect(() => {
    const hidden = () => { if (document.hidden) olderRequest.current?.abort() }
    document.addEventListener('visibilitychange', hidden)
    return () => { olderRequest.current?.abort(); document.removeEventListener('visibilitychange', hidden) }
  }, [path, tab])
  const restoredSteering = useRef(''), observed = useRef('')
  const steering = detail?.steering
  const progressKey = task ? [task.revision,detail?.attempts[0]?.id,detail?.attempts[0]?.state,detail?.attempts[0]?.finishedMs].join(':') : ''
  useEffect(() => {
    if (!progressKey) return
    if (observed.current && observed.current !== progressKey) conversation.refresh()
    observed.current = progressKey
  }, [progressKey,conversation.refresh])
  const setDraft = (value: string) => { edit(value); try { if (value) localStorage.setItem(draftKey, value); else localStorage.removeItem(draftKey) } catch { /* Keep editing without storage. */ } }
  useEffect(() => {
    if (!steering || !['blocked','cancelled'].includes(steering.state) || restoredSteering.current === steering.operationId) return
    restoredSteering.current = steering.operationId
    if (!draft.trim() && steering.text) setDraft(steering.text)
  }, [steering?.operationId,steering?.state,steering?.text])
  const mutation = async (action: string, body: unknown) => {
    if (sending.current || !task || snapshot.detail.failed) return false
    sending.current = true; setBusy(true); setError('')
    try {
      await api('POST', '/agent/tasks/' + encodeURIComponent(task.id) + '/' + action, body)
      if (alive.current) { snapshot.refresh(); conversation.refresh(); onChanged() }
      return true
    } catch (reason: any) {
      if (alive.current) { setError(taskSessionError(reason?.apiError?.code,t)); snapshot.refresh() }
      if (reason?.apiError?.code === 'TASK_REVISION_CHANGED') pending.current = null
      return false
    } finally { sending.current = false; if (alive.current) setBusy(false) }
  }
  const send = async (answer?: string) => {
    const text = (answer ?? draft).trim()
    if (!text || !task || closed || closing) return false
    if (!pending.current || pending.current.text !== text) pending.current = { text, revision: task.revision, key: crypto.randomUUID() }
    const request = pending.current
    const ok = await mutation('steer', { text, revision: request.revision, requestKey: request.key })
    if (ok && alive.current) { if (!answer || draft.trim() === text) setDraft(''); pending.current = null }
    return ok
  }
  const loadOlder = async () => {
    const cursor = before === undefined ? conversation.value?.before : before
    if (!cursor || sending.current || document.hidden) return
    const controller = new AbortController(); olderRequest.current = controller
    let timedOut = false
    const timeout = setTimeout(() => { timedOut = true; controller.abort() }, 15_000)
    sending.current = true; setBusy(true); setError('')
    try {
      const response = await api('GET', path + '?before=' + cursor, undefined, { signal: controller.signal })
      if (alive.current && !controller.signal.aborted) { prepend.current = scroll.current?.scrollHeight || 0; follow.current = false; setOlder(previous => [...response.data.messages, ...previous]); setBefore(response.data.before) }
    } catch { if (alive.current && (!controller.signal.aborted || timedOut)) setError(t('agent.requestFailed')) }
    finally { clearTimeout(timeout); if (olderRequest.current === controller) olderRequest.current = null; sending.current = false; if (alive.current) setBusy(false) }
  }
  useBoundaryLoad(scroll, () => { void loadOlder() }, tab === 'conversation' && !!(before === undefined ? conversation.value?.before : before) && !busy && !error, 'start')
  const messages = useMemo(() => [...new Map([...older, ...(conversation.value?.messages || [])].map(item => [item.id, item])).values()]
    .filter(item => ['user', 'assistant', 'tool'].includes(item.role) && (item.content.text || item.content.tool_calls?.length || item.content.question || item.content.taskStatus || item.content.attachments?.length || item.status === 'streaming'))
    .sort((a, b) => a.seq - b.seq), [older, conversation.value?.messages])
  useLayoutEffect(() => {
    const element = scroll.current
    if (!element || tab !== 'conversation') return
    if (prepend.current !== null) { element.scrollTop += element.scrollHeight - prepend.current; prepend.current = null }
    else if (follow.current) element.scrollTop = element.scrollHeight
  }, [messages.length, messages[messages.length - 1]?.content.text])
  useLayoutEffect(() => { if (scroll.current) scroll.current.scrollTop = positions.current[tab] ?? (tab === 'conversation' ? scroll.current.scrollHeight : 0) }, [tab])
  const projectId = task?.projectId || metadata.projectId
  const current = detail?.attempts[0]
  const failure = task?.state === 'failed' && current?.revision === task.revision ? taskFailureKey(detail?.outcome?.errorCode || current.result?.summary) || 'agent.requestFailed' : ''
  const stopping = detail?.steering?.state === 'stopping'
  const disabled = busy || !task || snapshot.detail.failed || closed || closing || stopping
  const artifacts = snapshot.artifacts.value || []
  const switchTab = (value: string) => { if (scroll.current) positions.current[tab] = scroll.current.scrollTop; setTab(value) }
  return <div className="native-session">
    {!embedded && <header className="tt-pagehead native-session-head"><span className="native-session-mark"><RoamiLogo size={20} /></span><div className="native-session-identity"><h2>{title}</h2><div className="native-session-meta">{task && <span className="agent-task-state" data-state={task.state} role="status">{t(active ? 'mobile.st.running' : 'mobile.st.idle')}</span>}{projectId && <a href={'#/projects/' + encodeURIComponent(projectId)}>{projects.find(project => project.id === projectId)?.name || t('agent.task.project')}</a>}</div></div></header>}
    <div className="native-session-tabs" role="tablist" aria-label={t('agent.task.sessionViews')}>{['conversation', 'process', 'artifacts'].map(value => <button key={value} type="button" role="tab" id={'native-tab-' + value} aria-controls="native-session-panel" aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} onClick={() => switchTab(value)} onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const tabs = ['conversation', 'process', 'artifacts'], index = tabs.indexOf(tab)
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3
      switchTab(tabs[next]); document.getElementById('native-tab-' + tabs[next])?.focus()
    }}>{t('agent.task.sessionTab.' + value)}</button>)}</div>
    <div ref={scroll} onScroll={event => { const element = event.currentTarget; if (tab === 'conversation') follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80 }} data-pagination-edge={tab === 'conversation' ? 'start' : undefined} className="native-session-content" role="tabpanel" id="native-session-panel" aria-labelledby={'native-tab-' + tab}>
      {(!detail && !snapshot.detail.failed) && <Spin />}
      {snapshot.detail.failed && <p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={snapshot.refresh}>{t('agent.retry')}</button></p>}
      {tab === 'conversation' && <div className="native-session-messages conversation-transcript" role="log" aria-label={t('agent.task.conversation')}>
        {conversation.loading && <Spin />}
        {conversation.failed && <p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={conversation.refresh}>{t('agent.retry')}</button></p>}
        {(before === undefined ? conversation.value?.before : before) && <button type="button" className="tt-act" disabled={busy} onClick={() => { void loadOlder() }}>{t('agent.task.moreConversation')}</button>}
        <NativeConversation messages={messages} active={active} node={node} canAnswer={!disabled} answer={send} />
        {!conversation.loading && !conversation.failed && !messages.length && <p className="agent-muted">{t('agent.task.noConversation')}</p>}
        {closed && draft.trim() && <details className="agent-task-requirements"><summary><ChevronRight />{t('agent.task.unsentDraft')}</summary><p>{draft}</p></details>}
      </div>}
      {tab === 'process' && detail && <div className="native-session-process"><TaskProcess id={metadata.taskId} active={active} onSession={sessionId => onSession?.(sessionId)} /><details className="agent-task-requirements"><summary><ChevronRight />{t('agent.task.reports')}</summary>{detail.attempts.map(attempt => <section className="agent-task-attempt" key={attempt.id}><b>{t('agent.task.revision', { n: attempt.revision })}</b><span>{t('agent.state.' + attempt.state)}</span><div className="agent-task-attempt-record"><TaskResult attempt={attempt} artifacts={artifacts} /></div></section>)}{detail.attemptsTruncated && <small>{t('agent.task.moreHistory')}</small>}</details></div>}
      {tab === 'artifacts' && detail && <NativeSessionArtifacts detail={detail} artifacts={artifacts} failed={snapshot.artifacts.failed} retry={snapshot.refresh} />}
    </div>
    <div className="native-session-composer conversation-composer-dock">{!closed && failure && <p role="alert">{t(failure)}</p>}{steering?.state === 'blocked' && <p role="alert">{taskSessionError(steering.errorCode,t)}</p>}{(error || closeError) && <p role="alert">{error || closeError}</p>}{stopping && <p role="status">{t('agent.task.steering.stopping')}</p>}{closed && <p role="status">{t('agent.task.sessionClosed')}</p>}{closing && <p role="status">{t('agent.task.sessionClosing')}</p>}
      {!closed && <ConversationComposer id="native-message" value={draft} onChange={setDraft} label={t('chat.sendTo', { name: title })} placeholder={t('chat.sendTo', { name: title })} disabled={disabled} maxLength={10000}
        send={{ label: t('agent.send'), pending: busy, onClick: () => { void send() } }}
        stop={active ? { label: t('chat.stop'), disabled, onClick: () => { void mutation('cancel', {}) } } : undefined}
        leading={<Dropdown trigger={['click']} menu={{ items: [{ key: 'rename', label: t('session.rename'), disabled: closed || closing }, { key: 'details', label: t('agent.task.details') }, { key: 'artifacts', label: t('agent.task.sessionTab.artifacts') }, ...(!closed ? [{ key: 'close', label: t('session.close'), disabled: busy || !task || snapshot.detail.failed || closing || !detail?.attempts[0] }] : [])], onClick: ({ key }) => { if (key === 'rename') setRenaming(true); else if (key === 'details') openAgentPage('tasks', metadata.taskId); else if (key === 'artifacts') switchTab('artifacts'); else setConfirm(true) } }}><button type="button" className="tt-pill ico" aria-label={t('chat.more')}><PlusIcon size={16} /></button></Dropdown>}
        settings={<AgentModelPicker models={models} disabled={disabled || active} node={node} />}
        voice={<VoiceInput inline scope={metadata.nativeSessionId + ':' + node} hotkey disabled={disabled} accent="var(--accent)" onResult={text => setDraft(draftRef.current + (draftRef.current ? '\n' : '') + text)} />} />}
    </div>
    {renaming && <RenameSessionModal session={renaming ? nativeSessionName(metadata.nativeSessionId) : null} onClose={() => setRenaming(false)} onDone={() => { refreshMetadata(); onChanged() }} />}
    <Modal className="native-session-confirm" open={confirm} title={t('session.closeConfirm', { name: title })} okText={t('session.close')} cancelText={t('common.cancel')} confirmLoading={busy} onCancel={() => { if (!busy) setConfirm(false) }} onOk={() => { void mutation('close-session', { revision: task?.revision, runId: detail?.attempts[0]?.id }).then(ok => { if (ok && alive.current) setConfirm(false) }) }}>{error && <p role="alert">{error}</p>}</Modal>
  </div>
}
