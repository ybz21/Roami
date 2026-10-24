import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Button, Input, Modal, Spin } from 'antd'
import { api } from '../../api'
import { agentName, isAgentKind } from '../../agent-kind'
import { AgentLogo, BotIcon, ChecklistIcon, CheckIcon, CircleIcon, ClockIcon, CloseIcon, QuestionIcon, WarnIcon, FolderIcon, TerminalIcon, ChevronLeft, ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import type { AgentTask } from './agent-protocol'
import { taskExecutor, taskGoal, taskInstructions } from './agent-task-protocol'
import AgentTaskRecord from './AgentTaskRecord'
import { taskTopic } from './task-topic'
import { taskOutcome, taskReportLinks } from './task-outcome'
import { useAgentData } from './useAgentData'
import { useAgentTask } from './useAgentTask'
import { useAgentDraft } from './useAgentDraft'
import { agentDataKey } from './agent-data-cache'
import { TaskArtifactPreview, canPreviewArtifact } from './TaskOutput'
import { taskFailureKey } from './task-failure'
import { taskSessionError as failure } from './task-session-error'
import { openAgentPage } from './agent-page-route'
import './agent-tasks.css'

const terminal = new Set(['succeeded', 'failed', 'cancelled', 'interrupted'])
const active = new Set(['queued', 'preparing', 'running', 'verifying', 'cancelling'])
const taskFilters = ['all', 'attention', 'active', 'open', 'ended'] as const
type TaskFilter = typeof taskFilters[number]

function matchesTaskFilter(task: AgentTask, filter: TaskFilter) {
  if (filter === 'all') return true
  if (filter === 'active') return active.has(task.state)
  if (filter === 'open') return !!(task.nativeSession || task.latestAttempt?.agentConversationId || task.latestAttempt?.sessionId && !terminal.has(task.state)) && task.sessionClosure?.state !== 'closed'
  if (filter === 'ended') return terminal.has(task.state)
  return !active.has(task.state) && task.state !== 'succeeded' && task.state !== 'cancelled'
}


type Props = { projects?: { id: string; name: string }[]; cid: string; onSession: (id: string) => void; onChanged: () => void; compact?: boolean; hideBack?: boolean; selectedTask?: string; onSelectTask?: (id: string) => void }

export default function AgentTasks({ projects = [], cid, onSession, onChanged, selectedTask, onSelectTask, compact = false, hideBack = false }: Props) {
  const { t } = useI18n()
  const [localSelected, setLocalSelected] = useState('')
  const filterKey = 'roami.task.filter.' + agentDataKey('/agent/tasks?conversationId=' + encodeURIComponent(cid))
  const [filter, changeFilter] = useState<TaskFilter>(() => { try { const saved = localStorage.getItem(filterKey) as TaskFilter; return taskFilters.includes(saved) ? saved : 'all' } catch { return 'all' } })
  const setFilter = (value: TaskFilter) => { changeFilter(value); try { localStorage.setItem(filterKey, value) } catch { /* Keep filtering without storage. */ } }
  const selected = selectedTask ?? localSelected
  const setSelected = (id: string) => { if (onSelectTask) onSelectTask(id); else setLocalSelected(id) }
  const list = useAgentData<AgentTask[]>(cid ? '/agent/tasks?conversationId=' + encodeURIComponent(cid) : null, 3000, 3000, 'GET', !selected)
  const tasks = list.value || [], { loading, failed } = list
  const roots = tasks.filter(task => !task.parent_task_id || !tasks.some(parent => parent.id === task.parent_task_id))
  const visible = roots.filter(task => matchesTaskFilter(task, filter))
  const container = useRef<HTMLDivElement>(null), restored = useRef('')
  const scrollKey = filterKey + ':scroll:' + filter
  useLayoutEffect(() => {
    if (selected || loading || restored.current === scrollKey) return
    const element = container.current?.closest<HTMLElement>('.agent-mobile-page, .ant-tabs-content-holder') || container.current
    if (element) { try { element.scrollTop = Number(localStorage.getItem(scrollKey)) || 0 } catch { /* Start at the top. */ }; restored.current = scrollKey }
  }, [selected, loading, scrollKey, tasks.length])
  useEffect(() => {
    if (selected) { restored.current = ''; return }
    const element = container.current?.closest<HTMLElement>('.agent-mobile-page, .ant-tabs-content-holder') || container.current
    let position = element?.scrollTop || 0
    const save = () => { if (element) position = element.scrollTop }
    element?.addEventListener('scroll', save, { passive: true })
    return () => { element?.removeEventListener('scroll', save); try { localStorage.setItem(scrollKey, String(position)) } catch { /* Keep navigation usable. */ } }
  }, [selected, scrollKey])
  return <div ref={container} className={`agent-tasks${compact ? ' agent-tasks-compact' : ''}`}>
    {selected ? <TaskInspector hideBack={hideBack} key={agentDataKey('/agent/tasks/' + encodeURIComponent(selected))} id={selected} onBack={() => { setSelected(''); list.refresh() }} select={setSelected} projects={projects} onSession={onSession} onChanged={() => { list.refresh(); onChanged() }} /> : <>
      {loading && <Spin />}{failed && <p role="alert">{t('agent.requestFailed')}</p>}
      {!loading && !failed && !tasks.length && (compact ? <div className="agent-workspace-empty"><ChecklistIcon size={28} /><strong>{t('agent.noTasks')}</strong></div> : <p className="agent-muted">{t('agent.noTasks')}</p>)}
      {!!roots.length && <div className="agent-task-filters" role="group" aria-label={t('agent.task.filter.label')}>{taskFilters.map(value => <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{t('agent.task.filter.' + value)}</button>)}</div>}
      {!loading && !failed && !!roots.length && !visible.length && <p className="agent-muted" role="status">{t('agent.task.filter.empty')}</p>}
      <TaskTimeline tasks={visible} compact={compact} select={setSelected} projects={projects} onSession={onSession} />
    </>}
  </div>
}

function taskTime(task: AgentTask) {
  return [task.updated_ms, task.created_ms].find(time => typeof time === 'number' && Number.isFinite(time) && time > 0) || 0
}
function TaskTimeline({ tasks, compact, select, projects, onSession }: { projects: { id: string; name: string }[]; onSession: (id: string) => void; tasks: AgentTask[]; compact: boolean; select: (id: string) => void }) {
  const { t, locale } = useI18n(), now = new Date(), yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const sorted = [...tasks].sort((a, b) => taskTime(b) - taskTime(a) || a.id.localeCompare(b.id))
  let previous = ''
  return <div className="agent-task-timeline">{sorted.map(task => {
    const date = taskTime(task) ? new Date(taskTime(task)) : null, day = date?.toDateString() || 'unknown'
    const heading = day !== previous; previous = day
    return <Fragment key={task.id}>{heading && <h4>{!date ? t('agent.workspace.timeUnknown') : day === now.toDateString() ? t('agent.workspace.today') : day === yesterday.toDateString() ? t('agent.workspace.yesterday') : new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date)}</h4>}<TaskRow task={task} compact={compact} select={select} projects={projects} onSession={onSession} /></Fragment>
  })}</div>
}

function TaskRow({ task, compact, select, projects, onSession }: { projects: { id: string; name: string }[]; onSession: (id: string) => void; task: AgentTask; compact: boolean; select: (id: string) => void }) {
  const { t, locale } = useI18n(), executor = taskExecutor(task)
  const state = ['queued', 'preparing', 'running', 'verifying', 'cancelling', 'waiting_user', 'succeeded', 'failed', 'cancelled', 'interrupted'].includes(task.state) ? task.state : 'unknown'
  const time = taskTime(task) ? new Date(taskTime(task)) : null
  const name = isAgentKind(executor) ? executor === 'claude' ? 'Claude Code' : agentName(executor) : executor === 'native' ? t('agent.workspace.native') : ''
  return <div className="agent-task-entry"><button type="button" className={`agent-task-link${compact ? ' agent-task-card' : ''}`} data-state={state} onClick={() => select(task.id)}>
    <span className="agent-task-status-icon" aria-hidden="true">{state === 'succeeded' ? <CheckIcon size={16} /> : state === 'failed' ? <WarnIcon size={16} /> : state === 'unknown' ? <QuestionIcon size={16} /> : state === 'cancelled' || state === 'interrupted' ? <CloseIcon size={16} /> : state === 'waiting_user' ? <ClockIcon size={16} /> : <CircleIcon size={16} />}</span>
    <span className="agent-task-row-copy">
      <b>{taskTopic(task) || t('agent.task.untitled')}</b>
      <small className="agent-task-card-meta"><span className="agent-task-state" data-state={state}>{t('agent.state.' + state)}</span>{executor && <span>{isAgentKind(executor) ? <AgentLogo kind={executor} size={14} /> : <BotIcon size={14} />}{name}</span>}{time && <time dateTime={time.toISOString()}>{time.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}</time>}</small>
    </span>
  </button>
    {task.projectId && <a className="tt-act agent-task-project" href={'#/projects/' + encodeURIComponent(task.projectId)}><FolderIcon size={14} /><span>{projects.find(project => project.id === task.projectId)?.name || t('agent.task.project')}</span></a>}
    <div className="agent-task-entry-actions">
      {task.nativeSession ? <button type="button" className="tt-act agent-task-session" aria-label={t('agent.task.enterSession')} onClick={() => openAgentPage('session', task.nativeSession!.id)}><TerminalIcon size={18} /></button> : task.latestAttempt?.sessionId && task.sessionClosure?.state !== 'closed' && <button type="button" className="tt-act agent-task-session" aria-label={t('agent.task.enterSession')} onClick={() => onSession(task.latestAttempt!.sessionId!)}><TerminalIcon size={18} /></button>}
    </div></div>
}

function TaskDescription({ content }: { content: string }) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false), [overflowing, setOverflowing] = useState(false)
  const text = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    const element = text.current
    if (!element) return
    const measure = () => { if (!expanded) setOverflowing(element.scrollHeight > element.clientHeight + 1) }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [content, expanded])
  return <section className="agent-task-section"><h4>{t('agent.task.description')}</h4><p ref={text} className={'agent-task-description' + (expanded ? '' : ' clipped')}>{content || t('agent.task.noDetails')}</p>{(overflowing || expanded) && <button type="button" className="tt-act agent-task-disclosure" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{t(expanded ? 'agent.task.collapseContent' : 'agent.task.expandContent')}</button>}</section>
}

function TaskInspector({ projects = [],  id, hideBack, onBack, select, onSession, onChanged }: { projects?: { id: string; name: string }[]; id: string; hideBack?: boolean; onBack: () => void; select: (id: string) => void; onSession: (id: string) => void; onChanged: () => void }) {
  const { t, locale } = useI18n()
  const snapshot = useAgentTask(id)
  const [busy, setBusy] = useState(''), [error, setError] = useState('')
  const draftKey = 'roami.agent.task.draft.' + agentDataKey('/agent/tasks/' + encodeURIComponent(id))
  const [draft, editDraft] = useAgentDraft(draftKey)
  const setDraft = (text: string) => {
    editDraft(text)
    try { if (text) localStorage.setItem(draftKey, text); else localStorage.removeItem(draftKey) } catch { /* Drafts remain usable without storage. */ }
  }
  const [closeConfirm, setCloseConfirm] = useState(false)
  const [history, setHistory] = useState(false), [preview, setPreview] = useState('')
  const alive = useRef(true), controlFence = useRef(0), busyRef = useRef(false)
  const pending = useRef<{ text: string; revision: number; key: string } | null>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const detail = snapshot.detail.value, task = detail?.task
  const detailSafe = snapshot.detail.version >= controlFence.current && !snapshot.detail.failed
  const controlSafe = detailSafe && snapshot.controls.version >= controlFence.current && !snapshot.controls.failed && !busy
  const controls = controlSafe ? snapshot.controls.value : null
  const latest = detail?.attempts[0], steering = detail?.steering
  const artifacts = useMemo(() => [...new Map([...(snapshot.artifacts.value || []), ...(detail?.delivery?.artifacts || [])].map(item => [item.id, item])).values()], [snapshot.artifacts.value, detail?.delivery?.artifacts])
  const sessionClosed = detail?.sessionClosure?.state === 'closed'
  const sessionClosing = ['closing', 'unknown'].includes(detail?.sessionClosure?.state || '')
  const sessionId = detail?.attempts.find(attempt => attempt.sessionId)?.sessionId || task?.latestAttempt?.sessionId
  const professional = !!task && isAgentKind(taskExecutor(task))
  const retainedSession = !!task?.nativeSession || professional && !!(task?.latestAttempt?.agentConversationId || detail?.attempts.some(attempt => attempt.sessionId === sessionId && attempt.agentConversationId))
  const ended = !!latest?.finishedMs || terminal.has(task?.state || '')
  const previewArtifact = useCallback((artifactId: string) => {
    setPreview(artifactId)
    requestAnimationFrame(() => document.getElementById('task-artifact-' + artifactId)?.scrollIntoView?.({ block: 'nearest' }))
  }, [])
  const stopping = steering?.state === 'stopping'
  const goal = task ? taskGoal(task) : ''
  const current = latest?.revision === task?.revision ? latest : undefined
  const outcome = taskOutcome(current), reportLinks = taskReportLinks(current)
  const failed = task?.state === 'failed' || task?.state === 'interrupted' || current?.result?.outcomeKnown === false
  const reason = failed ? taskFailureKey(detail?.outcome?.errorCode || current?.result?.summary || '') : undefined
  const mutate = async (name: string, path: string, body: unknown = {}) => {
    if (busyRef.current || !detailSafe) return
    busyRef.current = true
    setBusy(name); setError('')
    try { await api('POST', path, body); if (alive.current) onChanged() }
    catch (reason: any) { if (alive.current) setError(failure(reason?.apiError?.code, t)); return false }
    finally { if (alive.current) { controlFence.current = snapshot.refresh(); busyRef.current = false; setBusy('') } }
    return true
  }
  const continueTask = async (answer?: string) => {
    const text = (answer ?? draft).trim()
    if (!task || !text || busy || stopping) return false
    if (!pending.current || pending.current.text !== text) pending.current = { text, revision: task.revision, key: crypto.randomUUID() }
    const request = pending.current
    if (await mutate('steer', '/agent/tasks/' + encodeURIComponent(id) + '/steer', { requestKey: request.key, revision: request.revision, text })) {
      if (alive.current) { if (!answer || draft.trim() === text) setDraft(''); pending.current = null }
      return true
    }
    return false
  }
  return <>
    {!hideBack && <div className="agent-task-section-head"><button type="button" className="tt-act" onClick={onBack}><ChevronLeft />{t('agent.tasks')}</button></div>}
    {!task && !snapshot.detail.failed && <Spin />}
    {snapshot.detail.failed && <p role="alert">{t('agent.requestFailed')}</p>}
    {task && <>
      <div className="agent-task-heading"><h3>{taskTopic(task) || t('agent.task.untitled')}</h3><span className="agent-task-state" data-state={task.state}>{t('agent.state.' + task.state)}</span></div>
      <TaskDescription content={goal === task.id ? '' : goal} />
      <details className="agent-task-section agent-task-requirements"><summary><ChevronRight />{t('agent.task.instructions')}</summary><p>{taskInstructions(task) || t('agent.task.noInstructions')}</p>{steering?.text && steering.state !== 'applied' && <p><b>{t('agent.task.unappliedRequirements')}</b>{steering.text}</p>}<small className="agent-muted">{t('agent.task.revision', { n: task.revision })}</small>{task.latestAttempt?.workspace && <code className="agent-task-workspace">{task.latestAttempt.workspace.branch || task.latestAttempt.workspace.directory}</code>}</details>
      {failed ? <p className="agent-task-note error" role="status">{t(reason || 'agent.task.incomplete')}</p> : outcome && <section className="agent-task-section agent-task-outcome"><h4>{t('agent.task.result')}</h4>{task.state !== 'succeeded' && <p className="agent-muted">{t('agent.task.resultPending')}</p>}<p>{outcome}</p></section>}
      {!!reportLinks.length && <section className="agent-task-section"><h4>{t(task.state === 'succeeded' ? 'agent.task.deliveryLinks' : 'agent.task.reportedLinks')}</h4>{reportLinks.map(href => <a className="tt-act agent-task-delivery-link" key={href} href={href} target="_blank" rel="noopener noreferrer">{t('agent.task.openPullRequest', { n: href.split('/').pop()! })}</a>)}</section>}
      <div className="agent-task-actions">
        {task?.nativeSession && <Button onClick={() => openAgentPage('session', task.nativeSession!.id)}>{t('agent.task.enterSession')}</Button>}
        {task?.projectId && <a className="tt-act" href={'#/projects/' + encodeURIComponent(task.projectId)}>{projects.find(project => project.id === task.projectId)?.name || t('agent.task.project')}</a>}
        {sessionId && (!ended || retainedSession) && !sessionClosed && <Button onClick={() => onSession(sessionId)}>{t('agent.openSession')}</Button>}
        {retainedSession && (sessionId || task.nativeSession) && (terminal.has(task.state) || task.state === 'waiting_user') && !sessionClosed && <Button disabled={!detailSafe || !!busy || sessionClosing} onClick={() => setCloseConfirm(true)}>{t('agent.task.closeSession')}</Button>}
        {task.parent_task_id && <Button onClick={() => select(task.parent_task_id!)}>{t('agent.task.parent')}</Button>}
        {(!terminal.has(task.state) || stopping) && <Button danger disabled={!detailSafe || !!busy || (task.state === 'cancelling' && !stopping)} onClick={() => { void mutate('cancel', '/agent/tasks/' + encodeURIComponent(id) + '/cancel') }}>{t(stopping ? 'agent.task.cancelContinuation' : 'agent.cancelTask')}</Button>}
      </div>
      {steering && ['stopping', 'blocked', 'cancelled'].includes(steering.state) && <p className="agent-task-note" role="status">{steering.state === 'blocked' ? failure(steering.errorCode, t) : t('agent.task.steering.' + steering.state)}</p>}
      {error && !closeConfirm && <p className="agent-task-note error" role="alert">{error}</p>}
      {sessionClosed && <p className="agent-task-note" role="status">{t('agent.task.sessionClosed')}</p>}
      {sessionClosing && <p className="agent-task-note" role="status">{t('agent.task.sessionCloseUnknown')}</p>}
      <Modal open={closeConfirm} title={t('agent.task.closeSessionConfirm')} okText={t('agent.task.completeAndClose')} cancelText={t('common.cancel')} confirmLoading={busy === 'close-session'} onCancel={() => { if (!busy) setCloseConfirm(false) }} onOk={() => { void mutate('close-session', '/agent/tasks/' + encodeURIComponent(id) + '/close-session', { revision: task.revision, runId: latest?.id }).then(ok => { if (ok) setCloseConfirm(false) }) }}><p>{t('agent.task.closeSessionHint')}</p>{error && <p role="alert" className="agent-task-note error">{error}</p>}</Modal>
      {(artifacts.length > 0 || snapshot.artifacts.failed || !!detail?.delivery?.unavailable.length) && <section className="agent-task-section"><h4>{t('agent.task.artifacts')}</h4>
        {snapshot.artifacts.failed && <p role="alert">{t('agent.task.artifactsUnavailable')}</p>}
        {!snapshot.artifacts.value && !snapshot.artifacts.failed && <Spin size="small" />}
        {!!detail?.delivery?.unavailable.length && <p className="agent-task-note" role="status">{t('agent.task.outputsUnavailable')}<small>{detail.delivery.unavailable.map(item => item.sourcePath).join(' · ')}</small></p>}
        {artifacts.map((artifact) => <div className="agent-task-artifact" id={'task-artifact-' + artifact.id} key={artifact.id}><span>{artifact.name}<small className="agent-muted">{t('agent.task.artifactBytes', { n: artifact.sizeBytes.toLocaleString(locale) })}{artifact.createdMs && <time>{new Date(artifact.createdMs).toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' })}</time>}</small></span><div className="agent-task-actions">
          {canPreviewArtifact(artifact) && <button type="button" className="tt-act" aria-label={t('agent.task.previewNamed', { name: artifact.name })} onClick={() => setPreview(preview === artifact.id ? '' : artifact.id)}>{t('agent.task.preview')}</button>}
          <a className="tt-act" href={nodeApi('/agent/artifacts/' + encodeURIComponent(artifact.id) + '/content')} download={artifact.name}>{t('agent.task.download')}</a>
        </div>{preview === artifact.id && <TaskArtifactPreview artifact={artifact} />}</div>)}
      </section>}
      {task.state === 'waiting_user' && <section className="agent-task-section"><p>{t('agent.task.acceptanceHint')}</p><div className="agent-task-actions"><Button disabled={!!busy || !detailSafe} onClick={() => { if (retainedSession && (sessionId || task.nativeSession)) setCloseConfirm(true); else void mutate('accept', '/agent/tasks/' + encodeURIComponent(id) + '/verify', { accepted: true, revision: task.revision, runId: latest?.id }) }}>{t(retainedSession && (sessionId || task.nativeSession) ? 'agent.task.completeAndClose' : 'agent.task.accept')}</Button><Button disabled={!!busy || !detailSafe} onClick={() => { void mutate('reject', '/agent/tasks/' + encodeURIComponent(id) + '/verify', { accepted: false, revision: task.revision, runId: latest?.id }) }}>{t('agent.task.reject')}</Button></div></section>}
      {!!detail?.children.length && <section className="agent-task-section"><h4>{t('agent.task.children')}</h4>{detail.children.map((child) => <button type="button" className="agent-task-link" key={child.id} onClick={() => select(child.id)}><span><b>{taskTopic(child) || t('agent.task.untitled')}</b><small>{t('agent.state.' + child.state)}</small></span><ChevronRight /></button>)}{detail.childrenTruncated && <small className="agent-muted">{t('agent.task.moreChildren')}</small>}</section>}
      {(snapshot.controls.failed || !!snapshot.controls.value?.resources.length || !!controls?.actions.some(action => action.state === 'unknown' && action.outcomeKnown !== true)) && <section className="agent-task-section"><h4>{t('agent.task.control')}</h4>
        {snapshot.controls.failed && <p role="alert">{t('agent.task.controlUnavailable')}</p>}
        {(ended || snapshot.controls.failed) && <button type="button" className="tt-act" onClick={snapshot.refresh}>{t('agent.task.checkControl')}</button>}
        {!snapshot.controls.value && !snapshot.controls.failed && <Spin size="small" />}
        {snapshot.controls.value?.resources.map((resource) => {
          const safe = controlSafe
          const title = resource.observation?.title || t(resource.kind === 'browser' ? 'agent.task.browser' : 'agent.task.desktop')
          const status = !safe ? 'confirmingControl' : resource.takeoverReady ? 'controlReady' : resource.state === 'quarantined' ? 'reconcile' : resource.state === 'pausing' || resource.state === 'paused' ? 'waitForStop' : resource.state === 'idle' && resource.controlReleased ? 'controlIdle' : 'agentControlling'
          return <div className="agent-task-resource" key={resource.id}><b>{title}</b><span className="agent-muted" role="status">{t('agent.task.' + status)}</span><div className="agent-task-actions">
            {resource.canPause && <Button disabled={!safe || resource.state === 'pausing'} onClick={() => { void mutate('pause', '/agent/resources/' + encodeURIComponent(resource.id) + '/pause') }}>{t('agent.task.takeControl')}</Button>}
            {resource.canResume && <Button disabled={!safe} onClick={() => { void mutate('resume', '/agent/resources/' + encodeURIComponent(resource.id) + '/resume') }}>{t('agent.task.returnControl')}</Button>}
            {safe && resource.takeoverReady && resource.browserId && resource.targetId && <a className="tt-act agent-task-browser-link" href={'#/browser/task/' + encodeURIComponent(resource.browserId) + '/' + encodeURIComponent(resource.targetId)}>{t('agent.task.openBrowser')}</a>}
          </div></div>
        })}
        {controls?.actions.some((action) => action.state === 'unknown' && action.outcomeKnown !== true) && <p className="agent-task-note">{t('agent.task.reconcile')}</p>}
      </section>}

      <section className="agent-task-section"><button type="button" className="tt-act agent-task-disclosure" aria-expanded={history} onClick={() => setHistory(!history)}><ChevronRight />{t('agent.task.viewRecord')}</button>
        {history && <AgentTaskRecord id={id} active={!ended} attempts={detail?.attempts || []} truncated={!!detail?.attemptsTruncated} artifacts={artifacts} onPreview={previewArtifact} onSession={onSession} onAnswer={continueTask} canAnswer={detailSafe && !terminal.has(task.state) && !busy && !stopping} />}
      </section>
      <section className="agent-task-section"><label htmlFor={'agent-steer-' + id}>{t('agent.task.additionalRequirements')}</label><Input.TextArea id={'agent-steer-' + id} value={draft} disabled={!!busy || stopping || sessionClosed || sessionClosing} maxLength={10000} autoSize={{ minRows: 2, maxRows: 5 }} onChange={(event) => setDraft(event.target.value)} placeholder={t('agent.task.continuePlaceholder')} /><Button disabled={!draft.trim() || !!busy || stopping || !detailSafe || sessionClosed || sessionClosing} loading={busy === 'steer'} onClick={() => { void continueTask() }}>{t('agent.task.continue')}</Button></section>
    </>}
  </>
}
