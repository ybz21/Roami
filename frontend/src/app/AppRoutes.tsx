import { Spin } from 'antd'
import { Suspense, useEffect, useMemo, useRef } from 'react'
import { type AgentKind } from '../agent-kind'
import { useAgentInbox } from '../components/agent/useAgentInbox'
import { lazyRetry } from '../components/lazy-retry'
import MobileSubPage from '../components/MobileSubPage'
import Projects from '../components/projects/Projects'
import { type TreeSrc } from '../components/shell/task-tree-snapshot'
import { useI18n } from '../i18n'
import ViewBoundary from './ViewBoundary'
import { WorkspaceStateProvider, useWorkspaceStateStore } from '../view-state'
import { definePage } from './page-definition'
import type { AppRoute } from './useAppRoute'
import type { TaskWorkspace } from './useTaskWorkspace'
const OnboardingPage = lazyRetry(() => import('../components/onboarding/OnboardingPage'))
const OnboardingHome = lazyRetry(() => import('../components/onboarding/OnboardingHome'))
const FilesPage = lazyRetry(() => import('../components/files/FilesPage'))
const Sessions = lazyRetry(() => import('../components/sessions/Sessions'))
const SettingsPage = lazyRetry(() => import('../components/settings/SettingsPage'))
const CapabilitiesPage = lazyRetry(() => import('../components/capabilities/CapabilitiesPage'))
const MobileSessions = lazyRetry(() => import('../components/mobile/MobileSessions'))
const MobileHome = lazyRetry(() => import('../components/mobile/MobileHome'))
const InstallPage = lazyRetry(() => import('../components/install/InstallPage'))
const MobileTools = lazyRetry(() => import('../components/mobile/MobileTools'))
const BrowserView = lazyRetry(() => import('../components/mirror/BrowserView'))
const PhoneView = lazyRetry(() => import('../components/mirror/PhoneView'))
const ProjectOkr = lazyRetry(() => import('../components/projects/okr/ProjectOkr'))
const OkrProjects = lazyRetry(() => import('../components/projects/okr/OkrProjects'))
const Swarm = lazyRetry(() => import('../components/swarm/Swarm'))
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
  visible?: boolean
  openPages?: string[]
  hasDock?: boolean
  routing: AppRoute
  isMobile: boolean
  active: string | null
  projects: TreeSrc['projects']
  projectDirectory?: { loaded: boolean; error: boolean; retry: () => void }
  actions: RouteActions
  mobileProject: MobileProject
  mobileSearchNonce: number
  mobileActionsHost: HTMLSpanElement | null
  fullscreen?: { active: boolean; toggle: () => void }
  agent: { node: string | null; inbox: ReturnType<typeof useAgentInbox>; open: boolean; notifications: () => void }
}
export default function AppRoutes(props: AppRoutesProps) {
  return <WorkspaceStateProvider><RetainedRoutes key={JSON.stringify(props.agent.node)} {...props} /></WorkspaceStateProvider>
}

function RetainedRoutes(props: AppRoutesProps) {
  const store = useWorkspaceStateStore()
  const closed = useRef<string[]>([])
  const routes = useRef(new Map<string, { routing: AppRoute; searchNonce: number }>())
  const visible = props.visible !== false
  if (visible) routes.current.set(props.routing.tab, { routing: props.routing, searchNonce: props.mobileSearchNonce })
  for (const key of routes.current.keys()) {
    if (props.openPages && !props.isMobile && key !== props.routing.tab && !props.openPages.includes(key)) { routes.current.delete(key); closed.current.push(key) }
  }
  useEffect(() => { for (const key of closed.current.splice(0)) if (!routes.current.has(key)) store.node(props.agent.node).child('page', key).clear({ preserveDrafts: true }) })
  return <>{[...routes.current].map(([key, entry]) => {
    const foreground = visible && key === props.routing.tab
    return <AppRouteContent key={key} {...props} foreground={foreground} routing={entry.routing} mobileSearchNonce={entry.searchNonce} />
  })}</>
}

function AppRouteContent({ foreground, routing, isMobile, hasDock, active, projects, projectDirectory, actions, mobileProject, mobileSearchNonce, mobileActionsHost, fullscreen, agent }: AppRoutesProps & { foreground: boolean }) {
  const store = useWorkspaceStateStore()
  const scope = useMemo(() => store.node(agent.node).child('page', routing.tab), [store, agent.node, routing.tab])
  const { route, tab, go, selectAgent, agentPage, agentParts, agentCID, agentBranch, agentMessage, swarmSub, projectSub, projectView, pluginSub, settingsSub } = routing
  const { openTerm, closeTerm, newTerminalAt, logout } = actions
  const { node: curNodeId, inbox: agentInbox, open: agentInboxOpen } = agent
  const { t } = useI18n()
  const okrProject = tab === 'okr' && route.includes('/') ? decodeURIComponent(route.split('/')[1]) : ''
  const mobileSessions = (
    <MobileSessions initialProjectKey={projectSub || undefined} onOpen={(n) => openTerm(n)} openProject={mobileProject} searchNonce={mobileSearchNonce}
      onNewTask={actions.newTask}
      onNewInWorktree={(kind, path) => { void newTerminalAt(kind, path) }} />
  )
  const pages = {
    okr: definePage(okrProject ? <ProjectOkr key={`${curNodeId || 'local'}:${okrProject}`} projectId={okrProject} projectName={projects.find(p => p.key === okrProject)?.name} projectDir={projects.find(p => p.key === okrProject)?.dir} onSession={openTerm} fromOverview />
      : <OkrProjects projects={projects} loaded={projectDirectory?.loaded ?? true} error={projectDirectory?.error ?? false} retry={projectDirectory?.retry || (() => {})} />, { lifetime: 'retain' }),
    swarm: definePage(<Swarm openTerm={openTerm} initialSwarm={swarmSub || undefined} onNav={(n) => { location.hash = n ? '#/swarm/' + encodeURIComponent(n) : '#/swarm' }} />, { lifetime: 'retain' }),
    projects: definePage(projectSub && projectView === 'okr' ? <ProjectOkr key={`${curNodeId || 'local'}:${projectSub}`} projectId={projectSub} projectName={projects.find(p => p.key === projectSub)?.name} projectDir={projects.find(p => p.key === projectSub)?.dir} onSession={openTerm} /> : isMobile
      ? mobileSessions
      : <Projects openTerm={openTerm} closeTerm={closeTerm} initialKey={projectSub || undefined} activeTerm={active} />, { lifetime: 'retain' }),
    sessions: definePage(isMobile
      ? mobileSessions
      : <Sessions openTerm={openTerm} closeTerm={closeTerm} activeTerm={active} />, { lifetime: 'retain' }),
    files: definePage(<FilesPage key={curNodeId || 'local'} openTerm={openTerm} />, { scroll: 'content' }),
    settings: definePage(<SettingsPage sub={settingsSub} onNav={(r) => go(r)} onLogout={logout} searchNonce={mobileSearchNonce}
      onInstall={() => go('install')} fullscreen={fullscreen} />, { lifetime: 'retain', scroll: 'content' }),
    hub: definePage(<HubPage />, { lifetime: 'retain' }),
    capabilities: definePage(<CapabilitiesPage sub={pluginSub} onNav={go} onLaunchAgent={kind => newTerminalAt(kind, '')} />, { lifetime: 'retain', scroll: 'content' }),
    onboarding: definePage(<OnboardingPage key={curNodeId || 'local'} sub={route.split('/').slice(1).join('/')} onNav={go} onLaunch={kind => newTerminalAt(kind, '')} onSession={openTerm} />, { lifetime: 'retain', scroll: 'content' }),
    home: definePage(<OnboardingHome active={!agentPage} onNav={go}>
      {(!agentPage || agentParts[0] === 'home') && <AgentChat inactive={!!agentPage} cid={agentCID} branch={agentBranch} focusMessage={agentMessage} node={curNodeId} inbox={agentInbox} inboxOpen={agentInboxOpen} select={selectAgent} notifications={agent.notifications} projects={projects.map((p) => ({ id: p.key, name: p.name }))} onSession={openTerm} onOverview={() => go('activity')} mobileActionsHost={mobileActionsHost} />}
      {agentPage && <AgentHomePage key={`${curNodeId || 'local'}:${agentPage.view}:${agentPage.origin}`} page={agentPage} node={curNodeId} inbox={agentInbox} projects={projects.map(p => ({ id: p.key, name: p.name }))} select={selectAgent} onSession={openTerm} onChanged={agentInbox.refresh} />}
    </OnboardingHome>, { lifetime: 'retain', scroll: 'content' }),
    activity: definePage(<MobileHome key={curNodeId || ''} last={active} onOpen={(n) => openTerm(n)} onNav={(k) => go(k)}
      onOpenProject={actions.openProject}
    />, { lifetime: 'retain' }),
    install: definePage(isMobile ? <MobileSubPage title={t('install.pageTitle')} onBack={() => go('settings')} manageHistory={false} keepBottomNav><InstallPage /></MobileSubPage> : <InstallPage />, { lifetime: 'retain' }),
    tools: definePage(<MobileTools onNav={(k) => go(k)} />, { lifetime: 'retain' }),
    browser: definePage(<BrowserView key={route} initialTarget={route.startsWith('browser/task/') ? route.split('/')[3] || '' : ''} browserInstance={route.startsWith('browser/task/') ? route.split('/')[2] || '' : ''} />, { scroll: 'content', resource: route }),
    phone: definePage(<PhoneView />, { scroll: 'content' }),
  }
  const lazyFallback = <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}><Spin /></div>
  const definition = pages[tab as keyof typeof pages] || pages.projects
  const viewScope = useMemo(() => definition.resource ? scope.child('resource', definition.resource) : scope, [scope, definition.resource])
  return <ViewBoundary page={tab} scope={viewScope} active={foreground} mobile={isMobile} hasDock={!!hasDock} lifetime={definition.lifetime} scroll={definition.scroll}>
    <Suspense fallback={lazyFallback}>{definition.content}</Suspense>
  </ViewBoundary>
}
