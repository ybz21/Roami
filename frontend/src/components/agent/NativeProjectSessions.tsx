import './native-session.css'
import { useEffect, useRef, useState } from 'react'
import { Modal } from 'antd'
import { api } from '../../api'
import type { TaskDetail } from './agent-task-protocol'
import { taskSessionError } from './task-session-error'
import { agentDataKey } from './agent-data-cache'
import { useLayout } from '../../layout'
import { CloseIcon, RoamiLogo } from '../../icons'
import { relTime } from '../../time-format'
import { useI18n } from '../../i18n'
import { openAgentPage } from './agent-page-route'
import { useAgentData } from './useAgentData'

export type NativeProjectSession = { nativeSessionId: string; taskId?: string; title: string; taskState: string; projectId?: string; createdAt?: string; lifecycle?: string; closureError?: string }

export default function NativeProjectSessions({ projectId, entries, onChanged, failed = false }: { projectId: string; entries?: NativeProjectSession[]; onChanged?: () => void; failed?: boolean }) {
  const { t, locale } = useI18n(), { phone } = useLayout()
  const sessions = useAgentData<NativeProjectSession[]>(entries || failed ? null : '/agent/native-sessions?projectId=' + encodeURIComponent(projectId), 5000, 5000)
  const items = entries || sessions.value
  const [removing, setRemoving] = useState<NativeProjectSession | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const alive = useRef(true), sending = useRef(false)
  const scope = agentDataKey('/agent/native-sessions')
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [scope])
  useEffect(() => { setRemoving(null); setError('') }, [scope, projectId])
  const remove = async () => {
    if (!removing || sending.current) return
    sending.current = true; setBusy(true); setError('')
    try {
      const metadata = removing.taskId ? removing : (await api('GET', '/agent/native-sessions/' + encodeURIComponent(removing.nativeSessionId))).data
      if (!alive.current || scope !== agentDataKey('/agent/native-sessions')) return
      const path = '/agent/tasks/' + encodeURIComponent(metadata.taskId)
      const detail: TaskDetail = (await api('GET', path)).data
      if (!alive.current || scope !== agentDataKey('/agent/native-sessions')) return
      if (detail.task.nativeSession?.id !== removing.nativeSessionId) throw new Error('Session binding changed')
      if (detail.sessionClosure?.state !== 'closed') await api('POST', path + '/close-session', { revision: detail.task.revision, runId: detail.attempts[0]?.id })
      if (alive.current && scope === agentDataKey('/agent/native-sessions')) { setRemoving(null); sessions.refresh(); onChanged?.() }
    } catch (reason: any) { if (alive.current && scope === agentDataKey('/agent/native-sessions')) setError(taskSessionError(reason?.apiError?.code, t)) }
    finally { sending.current = false; if (alive.current) setBusy(false) }
  }
  if ((failed || sessions.failed) && !items?.length) return <div className="prj-in native-project-sessions"><p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={onChanged || sessions.refresh}>{t('agent.retry')}</button></p></div>
  const visible = items?.filter(session => session.lifecycle !== 'closed') || []
  if (!visible.length && !removing) return null
  return <section className="prj-in native-project-sessions" aria-label={t('agent.workspace.native')}>{visible.map(session => <div className="native-project-entry" key={session.nativeSessionId}><button type="button" className={phone ? 'tt-msess-row native-project-session' : 'prj-row native-project-session native-project-session-desktop'} onClick={() => openAgentPage('session', session.nativeSessionId)}>
    {phone ? <span className="ic"><RoamiLogo size={16} /></span> : <i className="native-project-status" data-state={['queued', 'preparing', 'running', 'verifying', 'cancelling'].includes(session.taskState) ? 'running' : 'idle'} aria-hidden />}
    <span className="t"><span className="native-project-title"><b>{session.title || t('agent.task.untitled')}</b>{!phone && <span className="tt-agentmark" aria-label={t('agent.workspace.native')}><RoamiLogo size={13} /></span>}</span><span className="st"><i>{t(session.closureError ? 'agent.task.sessionCloseFailed' : session.lifecycle === 'closing' ? 'agent.task.sessionClosing' : ['queued', 'preparing', 'running', 'verifying', 'cancelling'].includes(session.taskState) ? 'mobile.st.running' : 'mobile.st.idle')}</i>{phone && <span className="tail"> · {t('agent.workspace.native')}</span>}</span></span>
    {session.createdAt && Number.isFinite(Date.parse(session.createdAt)) && <em title={t('agent.task.startedAt', { time: new Date(session.createdAt).toLocaleString(locale) })}>{relTime(Date.parse(session.createdAt) / 1000, t)}</em>}
  </button><button type="button" className="tt-act danger native-project-remove" aria-label={t('agent.task.removeSession')} disabled={session.lifecycle === 'closing' || busy} onClick={() => { setError(session.closureError ? taskSessionError(session.closureError, t) : ''); setRemoving(session) }}><CloseIcon size={16} /></button></div>)}
    <Modal className="native-session-confirm" open={!!removing} title={t('agent.task.closeSessionConfirm')} okText={t('agent.task.removeSession')} cancelText={t('common.cancel')} confirmLoading={busy} onCancel={() => { if (!busy) setRemoving(null) }} onOk={() => { void remove() }}><p>{t('agent.task.closeSessionHint')}</p>{error && <p role="alert">{error}</p>}</Modal>
  </section>
}
