import { useLayoutEffect, useRef } from 'react'
import { useI18n } from '../../i18n'
import MobileSubPage from '../MobileSubPage'
import AgentMemory from './AgentMemory'
import AgentTasks from './AgentTasks'
import AgentInbox from './AgentInbox'
import { backAgentPage, openAgentPage, type AgentPageRoute } from './agent-page-route'
import type { AgentInboxState } from './useAgentInbox'
import './agent-home-page.css'

export default function AgentHomePage({ page, inbox, projects, select, onSession, onChanged }: {
  page: AgentPageRoute; inbox: AgentInboxState; projects: { id: string; name: string }[]
  select: (cid: string, branch?: string, message?: string) => void
  onSession: (id: string) => void; onChanged: () => void
}) {
  const { t } = useI18n()
  const scroll = useRef<HTMLElement>(null), listScroll = useRef(0)
  useLayoutEffect(() => { if (scroll.current) scroll.current.scrollTop = page.task ? 0 : listScroll.current }, [page.task])
  const parts = page.origin.split('/')
  const cid = parts[0] === 'home' && parts[1] && parts[1] !== 'new' ? decodeURIComponent(parts[1]) : inbox.conversations[0]?.id || ''
  const title = t('agent.' + page.view)
  return <MobileSubPage title={title} onBack={() => backAgentPage(page)} manageHistory={false} keepBottomNav>
    <section ref={scroll} className="agent-mobile-page" aria-label={title}>
      {page.view === 'tasks' && <AgentTasks cid={cid} hideBack selectedTask={page.task} onSelectTask={id => { if (id) { if (!page.task) listScroll.current = scroll.current?.scrollTop || 0; openAgentPage('tasks', id) } else backAgentPage(page) }} onSession={onSession} onChanged={onChanged} />}
      {page.view === 'memory' && <AgentMemory cid={cid} projects={projects} select={select} />}
      {page.view === 'notifications' && <AgentInbox inbox={inbox} select={select} />}
    </section>
  </MobileSubPage>
}
