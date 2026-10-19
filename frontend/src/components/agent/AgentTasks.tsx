import { useEffect, useRef, useState } from 'react'
import { Button, Input, Spin } from 'antd'
import { api } from '../../api'
import { ChevronLeft, ChevronRight, RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import type { AgentTask } from './agent-protocol'
import { taskExecutor, taskGoal } from './agent-task-protocol'
import { useAgentTask } from './useAgentTask'
import './agent-tasks.css'

const terminal = new Set(['succeeded', 'failed', 'cancelled', 'interrupted'])

function failure(code: string | undefined, t: (key: string) => string) {
  if (code === 'TASK_OUTCOME_UNRESOLVED') return t('agent.task.reconcile')
  if (code === 'RESOURCE_STOP_UNCONFIRMED' || code === 'TASK_RESOURCE_NOT_RELEASED') return t('agent.task.waitForControl')
  if (code === 'TASK_REVISION_CHANGED' || code === 'TASK_RESULT_SUPERSEDED' || code === 'TASK_STEER_PENDING') return t('agent.task.changed')
  if (code === 'TASK_SOURCE_FORGOTTEN' || code === 'CONTEXT_SOURCE_FORGOTTEN') return t('agent.task.forgotten')
  if (code === 'PARENT_TASK_NOT_RUNNING') return t('agent.task.parentStopped')
  return t('agent.requestFailed')
}

type Props = { cid: string; onSession: (id: string) => void; onChanged: () => void; selectedTask?: string; onSelectTask?: (id: string) => void }

export default function AgentTasks({ cid, onSession, onChanged, selectedTask, onSelectTask }: Props) {
  const { t, locale } = useI18n()
  const [tasks, setTasks] = useState<AgentTask[]>([]), [localSelected, setLocalSelected] = useState('')
  const selected = selectedTask ?? localSelected
  const setSelected = (id: string) => { if (onSelectTask) onSelectTask(id); else setLocalSelected(id) }
  const [failed, setFailed] = useState(false), [loading, setLoading] = useState(true), [version, setVersion] = useState(0)
  useEffect(() => {
    if (!cid || selected) { setLoading(false); return }
    let cancelled = false
    const controller = new AbortController()
    void api('GET', '/agent/tasks?conversationId=' + encodeURIComponent(cid), undefined, { signal: controller.signal })
      .then((result) => { if (!cancelled) { setTasks(result.data); setFailed(false) } })
      .catch(() => { if (!cancelled) setFailed(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true; controller.abort() }
  }, [cid, selected, version])
  useEffect(() => { const timer = setInterval(() => { if (document.visibilityState === 'visible') setVersion((value) => value + 1) }, 3000); return () => clearInterval(timer) }, [])
  const roots = tasks.filter(task => !task.parent_task_id || !tasks.some(parent => parent.id === task.parent_task_id))
  return <div className="agent-tasks">
    {selected ? <TaskInspector key={selected} id={selected} onBack={() => { setSelected(''); setVersion((value) => value + 1) }} select={setSelected} onSession={onSession} onChanged={onChanged} /> : <>
      <div className="agent-task-section-head"><span className="agent-muted">{t('agent.task.listHint')}</span><button type="button" className="tt-act" aria-label={t('agent.retry')} onClick={() => setVersion((value) => value + 1)}><RefreshIcon /></button></div>
      {loading && <Spin />}{failed && <p role="alert">{t('agent.requestFailed')}</p>}
      {!loading && !failed && !tasks.length && <p className="agent-muted">{t('agent.noTasks')}</p>}
      {(['attention', 'active', 'recent'] as const).map(group => {
        const current = roots.filter(task => (['queued', 'preparing', 'running', 'verifying', 'cancelling'].includes(task.state) ? 'active' : ['succeeded', 'cancelled'].includes(task.state) ? 'recent' : 'attention') === group)
          .sort((a, b) => (b.updated_ms || b.created_ms || 0) - (a.updated_ms || a.created_ms || 0))
        if (!current.length) return null
        return <section className="agent-task-list-group" key={group}><h4>{t('agent.workspace.taskGroup.' + group)}<span>{current.length}</span></h4>{current.map(task => { const executor = taskExecutor(task); const time = typeof task.updated_ms === 'number' && Number.isFinite(task.updated_ms) && task.updated_ms > 0 ? new Date(task.updated_ms) : null; return <button type="button" className="agent-task-link" key={task.id} onClick={() => setSelected(task.id)}>
          <span><b>{taskGoal(task)}</b><small>{t('agent.state.' + (['queued', 'preparing', 'running', 'verifying', 'cancelling', 'waiting_user', 'succeeded', 'failed', 'cancelled', 'interrupted'].includes(task.state) ? task.state : 'unknown'))}{task.revision > 1 && t('agent.task.revision', { n: task.revision })}</small>{(executor || time) && <small>{executor === 'codex' ? 'Codex' : executor === 'claude' ? 'Claude Code' : executor === 'native' ? t('agent.workspace.native') : ''}{time && <time dateTime={time.toISOString()}>{time.toLocaleString(locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>}</small>}</span><ChevronRight />
        </button> })}</section>
      })}
    </>}
  </div>
}

function TaskInspector({ id, onBack, select, onSession, onChanged }: { id: string; onBack: () => void; select: (id: string) => void; onSession: (id: string) => void; onChanged: () => void }) {
  const { t, locale } = useI18n()
  const snapshot = useAgentTask(id)
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [draft, setDraft] = useState('')
  const [history, setHistory] = useState(false), [fullGoal, setFullGoal] = useState(false), [preview, setPreview] = useState('')
  const alive = useRef(true), controlFence = useRef(0), busyRef = useRef(false)
  const pending = useRef<{ text: string; revision: number; key: string } | null>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const detail = snapshot.detail.value, task = detail?.task
  const controlSafe = snapshot.controls.version >= controlFence.current && !snapshot.controls.failed && !busy
  const controls = controlSafe ? snapshot.controls.value : null
  const latest = detail?.attempts[0], steering = detail?.steering
  const stopping = steering?.state === 'stopping'
  const goal = task ? taskGoal(task) : ''
  const mutate = async (name: string, path: string, body: unknown = {}) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(name); setError('')
    try { await api('POST', path, body); if (alive.current) onChanged() }
    catch (reason: any) { if (alive.current) setError(failure(reason?.apiError?.code, t)); return false }
    finally { if (alive.current) { controlFence.current = snapshot.refresh(); busyRef.current = false; setBusy('') } }
    return true
  }
  const continueTask = async () => {
    const text = draft.trim()
    if (!task || !text || busy || stopping) return
    if (!pending.current || pending.current.text !== text) pending.current = { text, revision: task.revision, key: crypto.randomUUID() }
    const request = pending.current
    if (await mutate('steer', '/agent/tasks/' + encodeURIComponent(id) + '/steer', { requestKey: request.key, revision: request.revision, text })) {
      if (alive.current) { setDraft(''); pending.current = null }
    }
  }
  return <>
    <div className="agent-task-section-head"><button type="button" className="tt-act" onClick={onBack}><ChevronLeft />{t('agent.tasks')}</button><button type="button" className="tt-act" aria-label={t('agent.retry')} onClick={() => snapshot.refresh()}><RefreshIcon /></button></div>
    {!task && !snapshot.detail.failed && <Spin />}
    {snapshot.detail.failed && <p role="alert">{t('agent.requestFailed')}</p>}
    {task && <>
      <div className="agent-task-heading"><h3 className={fullGoal ? '' : 'agent-task-goal'}>{goal}</h3><span className="agent-task-state" data-state={task.state}>{t('agent.state.' + task.state)}</span></div>
      {(goal.length > 300 || (steering?.text?.length || 0) > 300) && <button type="button" className="tt-act" aria-expanded={fullGoal} onClick={() => setFullGoal(!fullGoal)}>{t(fullGoal ? 'agent.task.hideGoal' : 'agent.task.showGoal')}</button>}
      <p className="agent-muted">{t('agent.task.revision', { n: task.revision })}</p>
      {steering?.text && <p className={fullGoal ? 'agent-task-requirements' : 'agent-task-requirements clipped'}><b>{t('agent.task.latestRequirements')}</b>{steering.text}</p>}
      {task.latestAttempt?.workspace && <code className="agent-task-workspace">{task.latestAttempt.workspace.branch || task.latestAttempt.workspace.directory}</code>}
      <div className="agent-task-actions">
        {task.latestAttempt?.sessionId && <Button onClick={() => onSession(task.latestAttempt!.sessionId!)}>{t('agent.openSession')}</Button>}
        {task.parent_task_id && <Button onClick={() => select(task.parent_task_id!)}>{t('agent.task.parent')}</Button>}
        {(!terminal.has(task.state) || stopping) && <Button danger disabled={!!busy || (task.state === 'cancelling' && !stopping)} onClick={() => { void mutate('cancel', '/agent/tasks/' + encodeURIComponent(id) + '/cancel') }}>{t(stopping ? 'agent.task.cancelContinuation' : 'agent.cancelTask')}</Button>}
      </div>
      {steering && ['stopping', 'blocked', 'cancelled'].includes(steering.state) && <p className="agent-task-note" role="status">{steering.state === 'blocked' ? failure(steering.errorCode, t) : t('agent.task.steering.' + steering.state)}</p>}
      {error && <p className="agent-task-note error" role="alert">{error}</p>}
      {typeof latest?.result?.summary === 'string' && latest.result.summary && <section className="agent-task-section"><h4>{t('agent.task.result')}</h4><p className="agent-task-result">{latest.result.summary}</p></section>}
      {task.state === 'waiting_user' && <section className="agent-task-section"><p>{t('agent.task.acceptanceHint')}</p><div className="agent-task-actions"><Button disabled={!!busy || snapshot.detail.failed} onClick={() => { void mutate('accept', '/agent/tasks/' + encodeURIComponent(id) + '/verify', { accepted: true, revision: task.revision, runId: latest?.id }) }}>{t('agent.task.accept')}</Button><Button disabled={!!busy || snapshot.detail.failed} onClick={() => { void mutate('reject', '/agent/tasks/' + encodeURIComponent(id) + '/verify', { accepted: false, revision: task.revision, runId: latest?.id }) }}>{t('agent.task.reject')}</Button></div></section>}
      {!!detail?.children.length && <section className="agent-task-section"><h4>{t('agent.task.children')}</h4>{detail.children.map((child) => <button type="button" className="agent-task-link" key={child.id} onClick={() => select(child.id)}><span><b>{taskGoal(child)}</b><small>{t('agent.state.' + child.state)}</small></span><ChevronRight /></button>)}{detail.childrenTruncated && <small className="agent-muted">{t('agent.task.moreChildren')}</small>}</section>}
      <section className="agent-task-section"><h4>{t('agent.task.control')}</h4>
        {snapshot.controls.failed && <p role="alert">{t('agent.task.controlUnavailable')}</p>}
        {!snapshot.controls.value && !snapshot.controls.failed && <Spin size="small" />}
        {controls?.resources.length === 0 && <p className="agent-muted">{t('agent.task.noControl')}</p>}
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
      </section>
      <section className="agent-task-section"><h4>{t('agent.task.artifacts')}</h4>
        {snapshot.artifacts.failed && <p role="alert">{t('agent.task.artifactsUnavailable')}</p>}
        {!snapshot.artifacts.value && !snapshot.artifacts.failed && <Spin size="small" />}
        {snapshot.artifacts.value?.length === 0 && <p className="agent-muted">{t('agent.task.noArtifacts')}</p>}
        {snapshot.artifacts.value?.map((artifact) => <div className="agent-task-artifact" key={artifact.id}><span>{artifact.name}<small className="agent-muted">{t('agent.task.artifactBytes', { n: artifact.sizeBytes.toLocaleString(locale) })}{artifact.createdMs && <time>{new Date(artifact.createdMs).toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' })}</time>}</small></span><div className="agent-task-actions">
          {artifact.mimeType === 'image/png' && artifact.sizeBytes <= 2 * 1024 * 1024 && <button type="button" className="tt-act" aria-label={t('agent.task.previewNamed', { name: artifact.name })} onClick={() => setPreview(preview === artifact.id ? '' : artifact.id)}>{t('agent.task.preview')}</button>}
          <a className="tt-act" href={nodeApi('/agent/artifacts/' + encodeURIComponent(artifact.id) + '/content')} download={artifact.name}>{t('agent.task.download')}</a>
        </div>{preview === artifact.id && <img className="agent-task-preview" src={nodeApi('/agent/artifacts/' + encodeURIComponent(artifact.id) + '/content')} alt={artifact.name} />}</div>)}
      </section>
      <section className="agent-task-section"><label htmlFor={'agent-steer-' + id}>{t('agent.task.additionalRequirements')}</label><Input.TextArea id={'agent-steer-' + id} value={draft} disabled={!!busy || stopping} maxLength={10000} autoSize={{ minRows: 2, maxRows: 5 }} onChange={(event) => setDraft(event.target.value)} placeholder={t('agent.task.continuePlaceholder')} /><Button disabled={!draft.trim() || !!busy || stopping || snapshot.detail.failed} loading={busy === 'steer'} onClick={() => { void continueTask() }}>{t('agent.task.continue')}</Button></section>
      <section className="agent-task-section"><button type="button" className="tt-act agent-task-disclosure" aria-expanded={history} onClick={() => setHistory(!history)}><ChevronRight />{t('agent.task.history')}</button>
        {history && detail?.attempts.map((attempt) => <div className="agent-task-attempt" key={attempt.id}><b>{t('agent.task.revision', { n: attempt.revision })}</b><span>{t('agent.state.' + attempt.state)}</span>{attempt.finishedMs && <time>{new Date(attempt.finishedMs).toLocaleString(locale)}</time>}{attempt.id !== latest?.id && typeof attempt.result?.summary === 'string' && attempt.result.summary && <p className="agent-task-result">{attempt.result.summary}</p>}</div>)}
        {history && detail?.attemptsTruncated && <small className="agent-muted">{t('agent.task.moreHistory')}</small>}
      </section>
    </>}
  </>
}
