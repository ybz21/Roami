import './agent-tasks.css'
import { useI18n } from '../../i18n'
import { openAgentPage } from './agent-page-route'
import { useAgentData } from './useAgentData'

export type NativeProjectSession = { nativeSessionId: string; title: string; taskState: string; projectId?: string }

export default function NativeProjectSessions({ projectId, entries }: { projectId: string; entries?: NativeProjectSession[] }) {
  const { t } = useI18n()
  const sessions = useAgentData<NativeProjectSession[]>(entries ? null : '/agent/native-sessions?projectId=' + encodeURIComponent(projectId), 5000)
  const items = entries || sessions.value
  if (sessions.failed) return <div className="prj-in native-project-sessions"><p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={sessions.refresh}>{t('agent.retry')}</button></p></div>
  if (!items?.length) return null
  return <section className="prj-in native-project-sessions" aria-label={t('agent.workspace.native')}>{items.map(session => <button key={session.nativeSessionId} type="button" className="agent-task-link" onClick={() => openAgentPage('session', session.nativeSessionId)}><span><b>{session.title || t('agent.task.untitled')}</b><small>{t('agent.workspace.native')} · {t('agent.state.' + session.taskState)}</small></span>{t('agent.task.enterSession')}</button>)}</section>
}
