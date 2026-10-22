import { useI18n } from '../../i18n'
import MobileSubPage from '../MobileSubPage'
import AgentMemory from './AgentMemory'
import AgentTasks from './AgentTasks'
import AgentInbox from './AgentInbox'
import AgentDebug from './AgentDebug'
import NativeSession from './NativeSession'
import { backAgentPage, openAgentPage, type AgentPageRoute } from './agent-page-route'
import type { AgentInboxState } from './useAgentInbox'
import './agent-home-page.css'

export default function AgentHomePage({ page, node, inbox, projects, select, onSession, onChanged }: {
  node: string | null
  page: AgentPageRoute; inbox: AgentInboxState; projects: { id: string; name: string }[]
  select: (cid: string, branch?: string, message?: string) => void
  onSession: (id: string) => void; onChanged: () => void
}) {
  const { t } = useI18n()
  const parts = page.origin.split('/')
  const cid = parts[0] === 'home' && parts[1] && parts[1] !== 'new' ? decodeURIComponent(parts[1]) : inbox.conversations[0]?.id || ''
  const title = t('agent.' + page.view)
  if (page.view === 'memory') return <AgentMemory cid={cid} fullPage projects={projects} select={select} onBack={() => backAgentPage(page)} />
  return <MobileSubPage title={title} onBack={() => backAgentPage(page)} manageHistory={false} keepBottomNav={page.view !== 'session'}>
    <section className={'agent-mobile-page' + (page.view === 'session' ? ' agent-session-page' : '')} aria-label={title}>
      {page.view === 'tasks' && <AgentTasks projects={projects} cid={cid} hideBack selectedTask={page.task} onSelectTask={id => { if (id) { openAgentPage('tasks', id) } else backAgentPage(page) }} onSession={onSession} onChanged={onChanged} />}
      {page.view === 'notifications' && <AgentInbox inbox={inbox} select={select} />}
      {page.view === 'session' && <NativeSession id={page.task} node={node} projects={projects} onChanged={onChanged} />}
      {page.view === 'debug' && <AgentDebug cid={cid} branch={parts[2] ? decodeURIComponent(parts[2]) : ''} node={node} selected={page.task} unavailable={inbox.unavailable} onSelect={value => openAgentPage('debug', value)} />}
    </section>
  </MobileSubPage>
}
