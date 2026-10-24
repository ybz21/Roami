import { Spin } from 'antd'
import type { ReactNode } from 'react'
import { Suspense } from 'react'
import { type AgentKind } from '../agent-kind'
import { useAgentInbox } from '../components/agent/useAgentInbox'
import FilesPage from '../components/files/FilesPage'
import { lazyRetry } from '../components/lazy-retry'
import MobileSubPage from '../components/MobileSubPage'
import Sessions from '../components/sessions/Sessions'
import SettingsPage from '../components/settings/SettingsPage'
import { type TreeSrc } from '../components/shell/task-tree-snapshot'
import { useLayout } from '../layout'
import { backAgentPage } from '../components/agent/agent-page-route'
import { useI18n } from '../i18n'
import type { AppRoute } from './useAppRoute'
import type { TaskWorkspace } from './useTaskWorkspace'
const CapabilitiesPage = lazyRetry(() => import('../components/capabilities/CapabilitiesPage'))
const MobileSessions = lazyRetry(() => import('../components/mobile/MobileSessions'))
const MobileHome = lazyRetry(() => import('../components/mobile/MobileHome'))
const InstallPage = lazyRetry(() => import('../components/install/InstallPage'))
const MobileTools = lazyRetry(() => import('../components/mobile/MobileTools'))
const BrowserView = lazyRetry(() => import('../components/mirror/BrowserView'))
const PhoneView = lazyRetry(() => import('../components/mirror/PhoneView'))
const Swarm = lazyRetry(() => import('../components/swarm/Swarm'))
const Projects = lazyRetry(() => import('../components/projects/Projects'))
const HubPage = lazyRetry(() => import('../components/cluster/HubPage'))
const AgentHomePage = lazyRetry(() => import('../components/agent/AgentHomePage'))
const AgentChat = lazyRetry(() => import('../components/agent/AgentChat'))


type RouteActions = {
  openTerm: TaskWorkspace['openTerm']
  closeTerm: (name: string) => void
  newTerminalAt: (kind: 'shell' | AgentKind, dir: string) => Promise<void>
  newTask: (dir?: string) => void
  openProject: (project: { name: string; dir: string }) => void
  logout: () => void
}
export type MobileProject = { name: string; dir: string; at: number } | null

type AppRoutesProps = {
  routing: AppRoute
  isMobile: boolean
  active: string | null
  projects: TreeSrc['projects']
  actions: RouteActions
  mobileProject: MobileProject
  mobileSearchNonce: number
  mobileActionsHost: HTMLSpanElement | null
  fullscreen?: { active: boolean; toggle: () => void }
  agent: { node: string | null; inbox: ReturnType<typeof useAgentInbox>; open: boolean; notifications: () => void }
}
export default function AppRoutes({ routing, isMobile, active, projects, actions, mobileProject, mobileSearchNonce, mobileActionsHost, fullscreen, agent }: AppRoutesProps) {
  const { route, tab, go, selectAgent, agentPage, agentParts, agentCID, agentBranch, agentMessage, swarmSub, projectSub, pluginSub, settingsSub } = routing
  const { openTerm, closeTerm, newTerminalAt, logout } = actions
  const { node: curNodeId, inbox: agentInbox, open: agentInboxOpen } = agent
  const { t } = useI18n()
  const { size } = useLayout()
  const inlineNative = agentPage?.view === 'session' && size === 'large' && !isMobile
  const mobileSessions = (
    <MobileSessions initialProjectKey={projectSub || undefined} onOpen={(n) => openTerm(n)} openProject={mobileProject} searchNonce={mobileSearchNonce}
      onNewTask={actions.newTask}
      onNewInWorktree={(kind, path) => { void newTerminalAt(kind, path) }} />
  )
  const pages: Record<string, ReactNode> = {
    swarm: <Swarm openTerm={openTerm} initialSwarm={swarmSub || undefined} onNav={(n) => { location.hash = n ? '#/swarm/' + encodeURIComponent(n) : '#/swarm' }} />,
    projects: isMobile
      ? mobileSessions
      : <Projects openTerm={openTerm} closeTerm={closeTerm} initialKey={projectSub || undefined} activeTerm={active} />,
    sessions: isMobile
      ? mobileSessions
      : <Sessions openTerm={openTerm} closeTerm={closeTerm} activeTerm={active} />,
    files: <FilesPage openTerm={openTerm} />,
    settings: <SettingsPage sub={settingsSub} onNav={(r) => go(r)} onLogout={logout} searchNonce={mobileSearchNonce}
      onInstall={() => go('install')} fullscreen={fullscreen} />,
    hub: <HubPage />,
    capabilities: <CapabilitiesPage sub={pluginSub} onNav={go} onLaunchAgent={kind => newTerminalAt(kind, '')} />,
    home: <>
      {(!agentPage || agentParts[0] === 'home' || inlineNative) && <AgentChat inactive={!!agentPage} nativeSession={inlineNative ? agentPage?.task : undefined} onCloseNative={() => { if (agentPage) backAgentPage(agentPage) }} cid={inlineNative ? agentCID || agentInbox.conversations[0]?.id || '' : agentCID} branch={agentBranch} focusMessage={agentMessage} node={curNodeId} inbox={agentInbox} inboxOpen={agentInboxOpen} select={selectAgent} notifications={agent.notifications} projects={projects.map((p) => ({ id: p.key, name: p.name }))} onSession={openTerm} onOverview={() => go('activity')} mobileActionsHost={mobileActionsHost} />}
      {agentPage && !inlineNative && <AgentHomePage key={`${curNodeId || 'local'}:${agentPage.view}:${agentPage.origin}`} page={agentPage} node={curNodeId} inbox={agentInbox} projects={projects.map(p => ({ id: p.key, name: p.name }))} select={selectAgent} onSession={openTerm} onChanged={agentInbox.refresh} />}
    </>,
    activity: <MobileHome key={curNodeId || ''} last={active} onOpen={(n) => openTerm(n)} onNav={(k) => go(k)}
      onOpenProject={actions.openProject}
    />,
    install: isMobile ? <MobileSubPage title={t('install.pageTitle')} onBack={() => go('settings')} manageHistory={false} keepBottomNav><InstallPage /></MobileSubPage> : <InstallPage />,
    tools: <MobileTools onNav={(k) => go(k)} />,
    browser: <BrowserView key={route} initialTarget={route.startsWith('browser/task/') ? route.split('/')[3] || '' : ''} browserInstance={route.startsWith('browser/task/') ? route.split('/')[2] || '' : ''} />,
    phone: <PhoneView />,
  }
  const lazyFallback = <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}><Spin /></div>
  return <Suspense fallback={lazyFallback}>{pages[tab] || pages.projects}</Suspense>
}
