import { Layout } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useAgentKinds } from '../agent-kind'
import '../components/agent/agent-chat.css'
import { openAgentPage } from '../components/agent/agent-page-route'
import AgentNotifications from '../components/agent/AgentNotifications'
import { useAgentInbox } from '../components/agent/useAgentInbox'
import { hubReasonText } from '../components/cluster/hub-health'
import { useCurrentNodeId } from '../components/cluster/node-url'
import { NodeMark, nodeDotColor } from '../components/cluster/NodeMark'
import MobilePullRefresh from '../components/mobile/MobilePullRefresh'
import { ICONS } from '../components/nav-icons'
import { sessionDisplay, sessionLabel } from '../components/sessions/session-label'
import { useSessionProject } from '../components/sessions/session-project'
import { isLooseTask } from '../components/sessions/task-key'
import { InspectorPanels } from '../components/shell/InspectorPanels'
import { Navigation } from '../components/shell/Navigation'
import { GlobalSearch, openPalette, type PaletteActions, type PaletteItem } from '../components/shell/palette'
import { ProjectTree } from '../components/shell/ProjectTree'
import type { StatusAction } from '../components/shell/status-cells'
import { systemCells } from '../components/shell/status-system'
import { NAV_RAIL, NAV_WIDTH } from '../components/shell/useWorkspaceLayout'
import { SessionCapsule, Workspace } from '../components/shell/Workspace'
import { WorkspaceStatusBar } from '../components/shell/WorkspaceStatusBar'
import UpdateBanner from '../components/UpdateBanner'
import { useI18n } from '../i18n'
import { OPEN_FILE_INTENT, requestIntent } from '../intents'
import { useLayout } from '../layout'
import { startControlLink, stopControlLink } from '../p2p/transport'
import { useLinkStatus } from '../p2p/use-link-status'
import { usePreferences } from '../preferences'
import { useThemeMode } from '../theme'

import AppRoutes from './AppRoutes'
import { MobileBottomBar, MobileTopBar } from './MobileNavigation'
import { CQ_PAGES, NAV, NAV_TOOLS, NAV_WORKSPACE } from './navigation'
import type { AppRoute } from './useAppRoute'
import { useBrowserEnvironment } from './useBrowserEnvironment'
import { useCanvasScroll } from './useCanvasScroll'
import { useClusterNavigation } from './useClusterNavigation'
import { usePageTabs } from './usePageTabs'
import { useProjectActions } from './useProjectActions'
import { useProjectDirectory } from './useProjectDirectory'
import { useSessionDirectory } from './useSessionDirectory'
import { useTabInspector } from './useTabInspector'
import { useTaskWorkspace } from './useTaskWorkspace'
import { useTerminalRuntime } from './useTerminalRuntime'
import { useWorkspaceShortcuts } from './useWorkspaceShortcuts'
import WorkspaceTerminals from './WorkspaceTerminals'

const { Sider, Content } = Layout

export default function AppShell({ routing, logout }: { routing: AppRoute; logout: () => void }) {
  const { setRoute, tab, go, selectAgent, inboxSub } = routing
  const agentKinds = useAgentKinds()
  const [agentInboxOpen, setAgentInboxOpen] = useState(false)
  const notifications = () => { agentInbox.refresh(); if (isMobile) openAgentPage('notifications'); else setAgentInboxOpen(true) }
  const { mode } = useThemeMode()
  const { t } = useI18n()
  const [prefs] = usePreferences()
  const { phone: isMobile, desktop: hasSider } = useLayout()
  const curNodeId = useCurrentNodeId()
  const agentInbox = useAgentInbox(true, curNodeId, tab === 'home' && !routing.agentPage && !routing.agentBranch)
  const data = useSessionDirectory()
  const workspace = useTaskWorkspace({ directory: data, nodeId: curNodeId, desktop: hasSider, mobile: isMobile, page: tab, navigate: go })
  const { terms, active, curFile, activeTask, space, taskView, overlay, returnToTask, openFileTab } = workspace
  const cluster = useClusterNavigation(go)
  const { clusterNodes, curNode, hubHealth, nodeItems } = cluster
  const activeProject = useSessionProject(active)
  const directory = useProjectDirectory(hasSider, activeProject?.worktree || activeProject?.dir || '')
  const { treeSrc, unfinished, swarmCount, git } = directory
  const runtimeTerms = useMemo(() => isMobile ? (overlay && active ? [active] : []) : terms, [terms, active, isMobile, overlay])
  const runtime = useTerminalRuntime(runtimeTerms, isMobile)
  const { claudeMap, codexMap, mobileWaiting } = runtime
  const inspector = useTabInspector(workspace, data.sessIds)
  const { panel, pickPanel, toggleInspector, searchNonce } = inspector
  const pageTabsState = usePageTabs(tab, terms, go)
  const { setTabBarHost } = pageTabsState
  const { online, offline, roamVersion, isFs, fsSupported, toggleFs } = useBrowserEnvironment()
  const canvasRef = useCanvasScroll(hasSider, space.mode)
  const [mobileSearchNonce, setMobileSearchNonce] = useState(0)
  const [mobileActionsHost, setMobileActionsHost] = useState<HTMLSpanElement | null>(null)
  const openTermRef = useRef<((n: string) => void) | null>(null)
  useEffect(() => {
    if (!inboxSub) return
    const name = inboxSub
    const qi = location.hash.indexOf('?')
    history.replaceState(history.state, '', '#/projects' + (qi >= 0 ? location.hash.slice(qi) : ''))
    setRoute('projects')
    setTimeout(() => openTermRef.current?.(name), 60)
  }, [inboxSub]) // eslint-disable-line react-hooks/exhaustive-deps

  const [mobileProject, setMobileProject] = useState<{ name: string; dir: string; at: number } | null>(null)
  const link = useLinkStatus()
  useEffect(() => {
    if (prefs.p2pEnabled) startControlLink()
    else stopControlLink()
    return stopControlLink
  }, [prefs.p2pEnabled])

  const projectActions = useProjectActions({ data, directory, workspace, runtime, isMobile, agentKinds, go })
  const { tree, openTerm, closeTerm, renameOpenTerm, onTreeTask, onTreeProject, newTerminalInTask, newTerminalAt, activeTaskLabel, finishTask } = projectActions
  const keys = useWorkspaceShortcuts({ hasSider, workspace, inspector, tree, activeProject, newTerminalInTask, closeTerm, setNewTaskDir: projectActions.setNewTaskDir })
  const termPane = <WorkspaceTerminals workspace={workspace} runtime={runtime} inspector={inspector} pages={pageTabsState}
    routing={routing} hasSider={hasSider} agentKinds={agentKinds} activeTaskLabel={activeTaskLabel}
    taskDir={activeTask && !isLooseTask(activeTask) ? activeTask : (activeProject?.dir || '')}
    actions={{ openTerm, closeTerm, renameOpenTerm, newTerminalInTask }} />
  openTermRef.current = (n) => openTerm(n)
  const page = taskView ? null : <AppRoutes routing={routing} isMobile={isMobile} active={active} projects={treeSrc.projects}
    actions={{ openTerm, closeTerm, newTerminalAt, logout, newTask: projectActions.newTask, openProject: (p) => { setMobileProject({ ...p, at: Date.now() }); go('projects') } }}
    mobileProject={mobileProject} mobileSearchNonce={mobileSearchNonce} mobileActionsHost={mobileActionsHost}
    fullscreen={isMobile && fsSupported ? { active: isFs, toggle: toggleFs } : undefined}
    agent={{ node: curNodeId, inbox: agentInbox, open: agentInboxOpen, notifications }} />
  const pageNode = <div className={`tt-page tt-page-${tab}${isMobile ? ' tt-page-mobile' : ''}${isMobile && terms.length ? ' has-dock' : ''}`}>{page}</div>
  const paletteItems: PaletteItem[] = [
    ...NAV.map((n) => ({
      key: `page:${n.key}`, group: t('workspace.groupPages'), title: t(n.labelKey),
      keywords: n.key, icon: ICONS[n.key], run: () => go(n.key),
    })),
    ...terms.map((name) => ({
      key: `term:${name}`, group: t('workspace.groupSessions'),
      title: sessionDisplay(name), desc: name === active ? t('workspace.current') : undefined,
      run: () => openTerm(name),
    })),
  ]

  const paletteActions: PaletteActions = {
    openRoute: (hash: string) => { location.hash = hash },
    openSession: (name: string) => openTerm(name),
    openFile: (path: string) => { if (taskView) openFileTab(path); else { go('files'); requestIntent(OPEN_FILE_INTENT, { path }) } },
  }

  const canvasNode = (
    <Content ref={canvasRef} className="tt-canvas" data-cq={CQ_PAGES.has(tab) ? 'on' : undefined} style={{
      flex: 1, minWidth: 0, minHeight: 0, height: '100%', padding: 0,
      overflow: tab === 'onboarding' || tab === 'capabilities' || tab === 'home' || tab === 'browser' || tab === 'phone' || tab === 'files' ? 'hidden' : 'auto',
    }}>{pageNode}</Content>
  )
  const dockNode = (
    <div onTransitionEnd={() => window.dispatchEvent(new Event('resize'))}
      style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>{termPane}</div>
  )

  const navGroups = [
    { label: '', items: [...NAV_WORKSPACE, ...NAV_TOOLS] },
  ].map((g) => ({
    label: g.label,
    items: g.items.map((key) => {
      const n = NAV.find((x) => x.key === key)!
      return {
        key: n.key, label: t(n.labelKey), icon: ICONS[n.key],
        badge: n.key === 'home' ? agentInbox.unread : n.key === 'projects' ? unfinished : undefined,
        badgeTone: n.key === 'home' ? 'danger' : undefined,
        badgeTitle: n.key === 'projects' ? t('overview.unfinishedN', { count: unfinished }) : undefined,
      }
    }),
  }))

  const navRail = space.navCollapsed || (space.mode === 'focus' && !taskView)

  const statusCells = systemCells({
    online,
    node: curNode ? { name: curNode.name, online: curNode.online, latencyMs: curNode.latencyMs } : null,
    hubAlarm: hubHealth.level === 'ok' ? undefined : hubReasonText(hubHealth, t),
    clustered: clusterNodes.length > 0,
    sessions: terms.length,
    waiting: Object.values(mobileWaiting).filter(Boolean).length,
    unfinished,
    agents: terms.filter((n) => agentKinds[n] || claudeMap[n]?.running || codexMap[n]?.running).length,
    version: roamVersion,
    git,
    projectKey: activeProject?.key || '',
    swarms: swarmCount,
    link,
    t,
  })
  const onStatusAction = (a: StatusAction) => {
    if (a.kind === 'route') location.hash = a.id
    else if (a.kind === 'pluginView') location.hash = '#/capabilities/plugins/' + encodeURIComponent(a.id)
  }

  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-base)' }}>

      {isMobile && <MobileTopBar tab={tab} route={routing.route} go={go} unread={agentInbox.unread} notifications={notifications}
        newTask={projectActions.newTask}
        search={() => setMobileSearchNonce(n => n + 1)} actionsHost={setMobileActionsHost} />}
      {/* clip prevents focus inside the hidden dock from scrolling the shell. */}
      <Layout style={{ flex: 1, minHeight: 0, overflow: 'clip', background: 'var(--bg-base)' }}>
        <UpdateBanner />

        {hasSider && (
          <Sider collapsible trigger={null} collapsedWidth={NAV_RAIL} width={NAV_WIDTH} theme={mode}
            collapsed={navRail}
            style={{ position: 'sticky', top: 0, height: '100%', background: 'var(--bg-base)', borderRight: '1px solid var(--border-subtle)' }}>
            <Navigation
              rail={navRail} active={tab} groups={navGroups} onGo={go}
              settings={{ key: 'settings', label: t('nav.env'), icon: ICONS.settings }}
              nodeMenu={nodeItems}
              onSearch={openPalette}
              searchHint={keys.search.label}
              tree={<ProjectTree tree={tree} activeTask={activeTask} activeSession={active}
                onProject={onTreeProject} onTask={onTreeTask} onSession={(key, name) => (terms.includes(name) ? returnToTask(key, name) : openTerm(name, key))}
                onAddProject={projectActions.addProject}
                onRename={projectActions.renameSession}
                onRenameTask={projectActions.renameTask}
                onNewTask={projectActions.newTask} onKill={projectActions.kill} onFinishTask={finishTask}
                onNewInTask={(key, kind) => { void newTerminalInTask(kind, key) }}
                onRemoveProject={projectActions.removeProject} />}
              hubAlarm={hubHealth.level === 'ok' ? undefined : hubReasonText(hubHealth, t)}
              node={curNode ? {
                name: curNode.name,
                mark: <NodeMark name={curNode.name} size="sm" />,
                dot: nodeDotColor(curNode),
                latency: curNode.online ? t('node.latencyMs', { ms: curNode.latencyMs }) : t('node.offline'),
              } : null}
              onToggleRail={() => space.setNavCollapsed(!space.navCollapsed)}
            />
            {projectActions.desktopDialogs}
          </Sider>
        )}

        {projectActions.dialogs}

        <Layout style={{ background: 'var(--bg-base)', minWidth: 0 }}>
          {hasSider && <div className="tt-global-tabs" ref={setTabBarHost} />}

          {hasSider ? (
            <Workspace
              mode={space.mode} canvas={canvasNode} dock={dockNode}
              onDismiss={() => space.setDockOpen(false)}
              inspectorCollapsed={space.inspectorCollapsed}
              onToggleInspector={toggleInspector}
              inspectorWidth={space.inspectorWidth} inspectorBounds={space.inspectorBounds}
              inspectorOverlay={!space.large} canvasFitsInspector={space.canvasFitsInspector}
              onInspectorResize={space.setInspectorWidth} onInspectorReset={space.resetInspectorWidth}
              capsule={space.overlayCapable && space.mode === 'page' ? (
                <SessionCapsule
                  label={sessionLabel(active) || active} count={terms.length}
                  onOpen={() => { space.setFocus('none'); space.setDockOpen(true) }}
                  title={`${sessionDisplay(active)} · ${t('terminal.expandTitle')} (${keys.toggleInspector.label})`}
                />
              ) : null}
            />
          ) : (
            <div style={{ position: 'relative', display: 'flex', flex: 1, minHeight: 0 }}>
              {canvasNode}

            </div>
          )}
        </Layout>
        <MobilePullRefresh enabled={isMobile && ['home', 'projects', 'sessions', 'tools', 'settings', 'install'].includes(tab)} />

        {hasSider && (() => {
          const loose = activeTask ? isLooseTask(activeTask) : false
          const owner = activeTask && !loose ? tree.projects.find((p) => p.tasks.some((x) => x.key === activeTask)) : undefined
          const task = owner?.tasks.find((x) => x.key === activeTask)
          const dir = activeTask && !loose ? activeTask : (activeProject?.dir || '')
          const scope = owner && task ? `${owner.name} · ${task.name}` : (active ? sessionLabel(active) || active : '')
          return (
            <InspectorPanels open={taskView} panel={panel} onPanel={pickPanel} dir={dir} scope={scope}
              openTerm={openTerm}
              onOpenFile={(p) => openFileTab(p)} selectedPath={curFile}
              searchNonce={searchNonce} onOpenLine={(p, line) => openFileTab(p, line)}
              onClose={() => { if (!space.inspectorCollapsed) toggleInspector() }} />
          )
        })()}

        {isMobile && <MobileBottomBar tab={tab} route={routing.route} go={go} offline={offline} />}

        <AgentNotifications node={curNodeId} open={agentInboxOpen} close={() => setAgentInboxOpen(false)} inbox={agentInbox} select={selectAgent} />
        <GlobalSearch items={paletteItems} actions={paletteActions} dir={activeProject?.worktree || activeProject?.dir} />

        {isMobile && overlay && (
          <div style={{ position: 'fixed', inset: 0, zIndex: 'var(--z-session)' as unknown as number, background: 'var(--bg-term)', display: 'flex', flexDirection: 'column' }}>
            {termPane}
          </div>
        )}
      </Layout>

      {hasSider && <WorkspaceStatusBar system={statusCells} onAction={onStatusAction} />}
    </div>
  )

}
