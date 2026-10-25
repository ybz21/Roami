import './native-session.css'
import { useLayout } from '../../layout'
import { BotIcon } from '../../icons'
import { relTime } from '../../time-format'
import { useI18n } from '../../i18n'
import { openAgentPage } from './agent-page-route'
import { useAgentData } from './useAgentData'

export type NativeProjectSession = { nativeSessionId: string; title: string; taskState: string; projectId?: string; createdAt?: string; lifecycle?: string }

export default function NativeProjectSessions({ projectId, entries }: { projectId: string; entries?: NativeProjectSession[] }) {
  const { t, locale } = useI18n(), { phone } = useLayout()
  const sessions = useAgentData<NativeProjectSession[]>(entries ? null : '/agent/native-sessions?projectId=' + encodeURIComponent(projectId), 5000)
  const items = entries || sessions.value
  if (sessions.failed) return <div className="prj-in native-project-sessions"><p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={sessions.refresh}>{t('agent.retry')}</button></p></div>
  if (!items?.length) return null
  return <section className="prj-in native-project-sessions" aria-label={t('agent.workspace.native')}>{items.map(session => <button key={session.nativeSessionId} type="button" className={phone ? 'tt-msess-row native-project-session' : 'prj-row native-project-session native-project-session-desktop'} onClick={() => openAgentPage('session', session.nativeSessionId)}>
    {phone ? <span className="ic"><BotIcon size={16} /></span> : <i className="native-project-status" data-state={session.taskState} aria-hidden />}
    <span className="t"><span className="native-project-title"><b>{session.title || t('agent.task.untitled')}</b>{!phone && <span className="tt-agentmark" aria-label={t('agent.workspace.native')}><BotIcon size={13} /></span>}</span><span className="st"><i>{t(session.lifecycle === 'closed' ? 'agent.task.sessionClosed' : 'agent.state.' + session.taskState)}</i>{phone && <span className="tail"> · {t('agent.workspace.native')}</span>}</span></span>
    {session.createdAt && Number.isFinite(Date.parse(session.createdAt)) && <em title={t('agent.task.startedAt', { time: new Date(session.createdAt).toLocaleString(locale) })}>{relTime(Date.parse(session.createdAt) / 1000, t)}</em>}
  </button>)}</section>
}
