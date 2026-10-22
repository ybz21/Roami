import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Button, Input, Modal, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import AgentMessageView from './AgentMessageView'
import { agentDataKey } from './agent-data-cache'
import { openAgentPage } from './agent-page-route'
import type { AgentMessage, AgentSnapshot } from './agent-protocol'
import { taskTopic } from './task-topic'
import { taskSessionError } from './task-session-error'
import { useAgentData } from './useAgentData'
import { useAgentDraft } from './useAgentDraft'
import { useAgentTask } from './useAgentTask'
import './native-session.css'

type Metadata = { nativeSessionId: string; taskId: string; projectId?: string }
type Page = AgentSnapshot & { before: number | null }

export default function NativeSession({ id, node, projects, onChanged }: { id: string; node: string | null; projects: { id: string; name: string }[]; onChanged: () => void }) {
  const { t } = useI18n()
  const session = useAgentData<Metadata>('/agent/native-sessions/' + encodeURIComponent(id), 0)
  return <>{session.loading && <Spin />}{session.failed && <p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={session.refresh}>{t('agent.retry')}</button></p>}{session.value && <SessionConversation key={agentDataKey('/agent/native-sessions/' + id)} metadata={session.value} node={node} projects={projects} onChanged={onChanged} />}</>
}

function SessionConversation({ metadata, node, projects, onChanged }: { metadata: Metadata; node: string | null; projects: { id: string; name: string }[]; onChanged: () => void }) {
  const { t } = useI18n(), snapshot = useAgentTask(metadata.taskId)
  const detail = snapshot.detail.value, task = detail?.task
  const closed = detail?.sessionClosure?.state === 'closed'
  const closing = ['closing', 'unknown'].includes(detail?.sessionClosure?.state || '')
  const active = !!task && ['queued', 'preparing', 'running', 'verifying', 'cancelling'].includes(task.state)
  const path = '/agent/native-sessions/' + encodeURIComponent(metadata.nativeSessionId) + '/conversation'
  const conversation = useAgentData<Page>(path, 0, active ? 3000 : 0)
  const [older, setOlder] = useState<AgentMessage[]>([]), [before, setBefore] = useState<number | null | undefined>()
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [confirm, setConfirm] = useState(false)
  const draftKey = 'roami.native.draft.' + agentDataKey(path)
  const [draft, edit] = useAgentDraft(draftKey)
  const scroll = useRef<HTMLDivElement>(null), follow = useRef(true), prepend = useRef<number | null>(null)
  const pending = useRef<{ text: string; revision: number; key: string } | null>(null), sending = useRef(false), alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
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
    if (!cursor || sending.current) return
    sending.current = true; setBusy(true)
    try {
      const response = await api('GET', path + '?before=' + cursor)
      if (alive.current) { prepend.current = scroll.current?.scrollHeight || 0; follow.current = false; setOlder(previous => [...response.data.messages, ...previous]); setBefore(response.data.before) }
    } catch { if (alive.current) setError(t('agent.requestFailed')) }
    finally { sending.current = false; if (alive.current) setBusy(false) }
  }
  const messages = [...new Map([...older, ...(conversation.value?.messages || [])].map(item => [item.id, item])).values()].sort((a, b) => a.seq - b.seq)
  useLayoutEffect(() => {
    const element = scroll.current
    if (!element) return
    if (prepend.current !== null) { element.scrollTop += element.scrollHeight - prepend.current; prepend.current = null }
    else if (follow.current) element.scrollTop = element.scrollHeight
  }, [messages.length, messages[messages.length - 1]?.content.text])
  const projectId = task?.projectId || metadata.projectId
  const stopping = detail?.steering?.state === 'stopping'
  const disabled = busy || !task || snapshot.detail.failed || closed || closing || stopping
  return <div className="native-session">
    <header className="tt-pagehead native-session-head"><div><h2>{task ? taskTopic(task) || t('agent.task.untitled') : t('agent.session')}</h2>{projectId && <a className="tt-act" href={'#/projects/' + encodeURIComponent(projectId)}>{projects.find(project => project.id === projectId)?.name || t('agent.task.project')}</a>}</div><div className="agent-task-actions"><button type="button" className="tt-act" onClick={() => openAgentPage('tasks', metadata.taskId)}>{t('agent.task.details')}</button>{task && <span className="agent-muted" role="status">{t(closed ? 'agent.task.sessionClosed' : 'agent.state.' + task.state)}</span>}{active ? <Button disabled={disabled} danger onClick={() => { void mutation('cancel', {}) }}>{t('agent.cancelTask')}</Button> : !closed && <Button disabled={disabled || !detail?.attempts[0]?.finishedMs} onClick={() => setConfirm(true)}>{t('agent.task.completeAndClose')}</Button>}</div></header>
    <div ref={scroll} onScroll={event => { const element = event.currentTarget; follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80 }} className="native-session-messages" role="log" aria-label={t('agent.task.conversation')}>
      {(conversation.loading || (!detail && !snapshot.detail.failed)) && <Spin />}
      {(conversation.failed || snapshot.detail.failed) && <p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={() => { conversation.refresh(); snapshot.refresh() }}>{t('agent.retry')}</button></p>}
      {(before === undefined ? conversation.value?.before : before) && <button type="button" className="tt-act" disabled={busy} onClick={() => { void loadOlder() }}>{t('agent.task.moreConversation')}</button>}
      {messages.map(item => <AgentMessageView key={item.id} item={item} node={node} readOnly focused={false} author={t('agent.task.subagent')} remember={() => {}} canAnswer={!disabled && item.seq === messages[messages.length - 1]?.seq} answer={send} />)}
      {!conversation.loading && !conversation.failed && !messages.length && <p className="agent-muted">{t('agent.task.noConversation')}</p>}
    </div>
    <div className="native-session-composer">{steering?.state === 'blocked' && <p role="alert">{taskSessionError(steering.errorCode,t)}</p>}{error && <p role="alert">{error}</p>}{stopping && <p role="status">{t('agent.task.steering.stopping')}</p>}<Input.TextArea id="native-message" aria-label={t('agent.task.additionalRequirements')} value={draft} disabled={disabled} autoSize={{ minRows: 2, maxRows: 5 }} onChange={event => setDraft(event.target.value)} placeholder={t('agent.task.continuePlaceholder')} /><Button type="primary" disabled={disabled || !draft.trim()} loading={busy} onClick={() => { void send() }}>{t('agent.task.continue')}</Button></div>
    <Modal open={confirm} title={t('agent.task.closeSessionConfirm')} okText={t('agent.task.completeAndClose')} cancelText={t('common.cancel')} confirmLoading={busy} onCancel={() => { if (!busy) setConfirm(false) }} onOk={() => { void mutation('close-session', { revision: task?.revision, runId: detail?.attempts[0]?.id }).then(ok => { if (ok && alive.current) setConfirm(false) }) }}><p>{t('agent.task.closeSessionHint')}</p>{error && <p role="alert">{error}</p>}</Modal>
  </div>
}
