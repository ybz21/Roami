// ── 独立单终端页：新浏览器标签全屏打开单个会话（hash 路由 #/term/name）──
import { useEffect, useState } from 'react'
import { useAgentKindInventory } from '../../agent-kind'
import { api } from '../../api'
import { useBrowserEnvironment } from '../../app/useBrowserEnvironment'
import { useClusterNavigation } from '../../app/useClusterNavigation'
import { useTerminalRuntime } from '../../app/useTerminalRuntime'
import { useI18n } from '../../i18n'
import { ExitFullscreenIcon, FullscreenIcon, SearchIcon } from '../../icons'
import { useLayout } from '../../layout'
import { startControlLink, stopControlLink } from '../../p2p/transport'
import { useLinkStatus } from '../../p2p/use-link-status'
import { usePreferences } from '../../preferences'
import { pollWhileVisible } from '../../visible-poll'
import { hubReasonText } from '../cluster/hub-health'
import type { FileTabMode } from '../files/FilePathBar'
import { useNativeSessionList } from '../sessions/native-session-list'
import { sessionDisplay, sessionLabel, setSessionLabels, updateSessionLabel, useSessionLabel } from '../sessions/session-label'
import { SessionMemoryAlerts } from '../sessions/SessionMemoryControl'
import { buildSessionProjects, setSessionProjects, useSessionProject } from '../sessions/session-project'
import { nativeSessionId, nativeSessionName } from '../sessions/session-record'
import { taskKeyOf } from '../sessions/task-key'
import { InspectorColumn } from '../shell/InspectorColumn'
import { InspectorPanels, type InspectorPanelKind } from '../shell/InspectorPanels'
import { matchHotkey, useKeybindings } from '../shell/keybindings'
import { GlobalSearch, openPalette, type PaletteActions, type PaletteItem } from '../shell/palette'
import type { StatusAction } from '../shell/status-cells'
import { systemCells } from '../shell/status-system'
import { loadTreeSrc } from '../shell/task-tree-snapshot'
import { useWorkspaceLayout } from '../shell/useWorkspaceLayout'
import { WorkspaceStatusBar } from '../shell/WorkspaceStatusBar'
import UpdateBanner from '../UpdateBanner'
import type { FileTab } from './term-tabs-store'
import TerminalPane from './TerminalPane'

const isPreviewableFile = (path: string) => /\.(md|markdown|mdx|html?)$/i.test(path)

export default function SoloTerminal({ name }: { name: string }) {
  const { t } = useI18n()
  const nativeId = nativeSessionId(name)
  const inventory = useAgentKindInventory(!nativeId)
  const agentKinds = inventory.value.kinds
  const { phone, desktop: hasSider } = useLayout()
  const native = useNativeSessionList(!!nativeId)
  const runtime = useTerminalRuntime(name, inventory, phone, { workspaceActivity: false, desktopClaude: false })
  const label = useSessionLabel(name)
  const activeProject = useSessionProject(name)
  const space = useWorkspaceLayout(true, true, { hasNav: false })
  const keys = useKeybindings()
  const [prefs] = usePreferences()
  const { online, roamVersion, isFs, fsSupported, toggleFs } = useBrowserEnvironment()
  const { clusterNodes, curNode, hubHealth } = useClusterNavigation((route) => { location.hash = '#/' + route })
  const link = useLinkStatus()
  useEffect(() => {
    if (prefs.p2pEnabled) startControlLink()
    else stopControlLink()
    return stopControlLink
  }, [prefs.p2pEnabled])

  const [tabBarHost, setTabBarHost] = useState<HTMLDivElement | null>(null)
  const [fileTabs, setFileTabs] = useState<FileTab[]>([])
  const [activeFile, setActiveFile] = useState('')
  const [reveal, setReveal] = useState<{ path: string; line: number; nonce: number } | undefined>()
  const [fetchedCwd, setFetchedCwd] = useState('')
  const [git, setGit] = useState<{ branch: string; ahead: number; behind: number; files: number; state: string; conflicts: number } | null>(null)
  const [searchNonce, setSearchNonce] = useState(0)
  const [panel, setPanelLocal] = useState<InspectorPanelKind>(() => {
    try {
      const saved = localStorage.getItem('roam.inspectorPanel')
      return saved === 'git' || saved === 'worktree' ? saved : 'files'
    } catch { return 'files' }
  })

  const setPanel = (next: InspectorPanelKind) => {
    setPanelLocal(next)
    try { localStorage.setItem('roam.inspectorPanel', next) } catch { /* ignore storage errors */ }
  }

  useEffect(() => {
    setFileTabs([])
    setActiveFile('')
    setReveal(undefined)
    setFetchedCwd('')
  }, [name])

  // 同步展示名与项目归属，与主页标签、路径条和右侧检查器保持一致。
  useEffect(() => {
    const cached = loadTreeSrc()
    if (cached.placement && Object.keys(cached.placement).length) setSessionProjects(cached.placement)
    let stop = false
    if (!nativeId) {
      api('GET', '/sessions').then((list) => {
        if (stop) return
        setSessionLabels(Object.fromEntries(
          (Array.isArray(list) ? list : [])
            .filter((s: any) => s?.name && s?.label)
            .map((s: any) => [s.name, s.label]),
        ))
      }).catch(() => {})
    }
    Promise.all([
      api('GET', '/projects').catch(() => null),
      api('GET', '/sessions/annotations').catch(() => null),
    ]).then(([pr, an]) => {
      if (stop) return
      const projects = pr?.data?.projects || []
      if (projects.length) setSessionProjects(buildSessionProjects(projects, an?.data || {}, native.value))
    }).catch(() => {})
    return () => { stop = true }
  }, [name, nativeId, native.value])

  const nativeRecord = nativeId ? native.value.find((item) => nativeSessionName(item.nativeSessionId) === name) : undefined
  useEffect(() => {
    if (nativeRecord?.title) updateSessionLabel(name, nativeRecord.title)
  }, [name, nativeRecord?.title])

  const runtimeDir = runtime.claudeMap[name]?.dir || runtime.codexMap[name]?.dir || runtime.openCodeMap[name]?.dir || ''
  const knownDir = activeProject?.worktree || nativeRecord?.directory || runtimeDir || ''

  useEffect(() => {
    if (knownDir) return
    const controller = new AbortController()
    api('GET', nativeId ? `/agent/native-sessions/${encodeURIComponent(nativeId)}` : `/sessions/${encodeURIComponent(name)}/cwd`, undefined, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setFetchedCwd(res?.data?.directory || res?.data?.dir || '')
      })
      .catch(() => {})
    return () => controller.abort()
  }, [name, nativeId, knownDir])

  const sessionDir = knownDir || fetchedCwd || activeProject?.dir || ''
  const sessionTaskKey = taskKeyOf(name, activeProject?.worktree)

  useEffect(() => {
    if (!hasSider || !sessionDir) { setGit(null); return }
    const poll = pollWhileVisible(async (signal) => {
      const d = (await api('GET', `/git/status?dir=${encodeURIComponent(sessionDir)}`, undefined, { signal }))?.data
      if (signal.aborted) return
      const len = (v: unknown) => (Array.isArray(v) ? v.length : Number(v) || 0)
      setGit(d?.repo ? {
        branch: d.branch || '', ahead: d.ahead || 0, behind: d.behind || 0,
        files: len(d.files), state: d.state || '', conflicts: len(d.conflicts),
      } : null)
    }, 15000)
    return poll.stop
  }, [hasSider, sessionDir])

  useEffect(() => { document.title = `Roami · ${sessionDisplay(name) || name}` }, [name, label])

  const openFileTab = (path: string, line?: number) => {
    setFileTabs((list) => (
      list.some((file) => file.path === path)
        ? list
        : [...list, { path, preview: false, mode: isPreviewableFile(path) ? 'preview' : 'source', task: sessionTaskKey, session: name }]
    ))
    setActiveFile(path)
    if (line && line > 0) setReveal((prev) => ({ path, line, nonce: (prev?.nonce || 0) + 1 }))
  }

  const closeFileTab = (path: string) => {
    setFileTabs((list) => {
      const index = list.findIndex((file) => file.path === path)
      const next = list.filter((file) => file.path !== path)
      setActiveFile((cur) => (cur === path ? (next[index - 1] || next[index])?.path || '' : cur))
      return next
    })
  }

  const pinFileTab = (path: string) => {
    setFileTabs((list) => list.map((file) => (file.path === path ? { ...file, preview: false } : file)))
  }

  const setFileMode = (path: string, mode: FileTabMode) => {
    setFileTabs((list) => list.map((file) => (file.path === path ? { ...file, mode, preview: false } : file)))
  }

  const toggleInspector = () => space.setInspectorCollapsed(!space.inspectorCollapsed)
  const showInspector = (next?: InspectorPanelKind) => {
    if (next) setPanel(next)
    space.setInspectorCollapsed(false)
  }

  useEffect(() => {
    if (!hasSider) return
    const onKey = (e: KeyboardEvent) => {
      if (matchHotkey(e, keys.toggleInspector.key)) {
        e.preventDefault()
        toggleInspector()
      } else if (matchHotkey(e, keys.searchContent.key)) {
        e.preventDefault()
        showInspector('files')
        setSearchNonce((n) => n + 1)
      } else if (matchHotkey(e, keys.panelFiles.key)) {
        e.preventDefault()
        showInspector('files')
      } else if (matchHotkey(e, keys.panelGit.key)) {
        e.preventDefault()
        showInspector('git')
      } else if (activeFile && matchHotkey(e, keys.closeTab.key)) {
        e.preventDefault()
        closeFileTab(activeFile)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [hasSider, keys, activeFile, space.inspectorCollapsed]) // eslint-disable-line react-hooks/exhaustive-deps

  const paletteItems: PaletteItem[] = [
    { key: 'page:home', group: t('workspace.groupPages'), title: t('nav.home'), keywords: 'home', run: () => { location.hash = '#/home' } },
    { key: `term:${name}`, group: t('workspace.groupSessions'), title: sessionDisplay(name), desc: t('workspace.current'), run: () => setActiveFile('') },
  ]

  const paletteActions: PaletteActions = {
    openRoute: (hash: string) => { location.hash = hash },
    openSession: (next: string) => { location.hash = '#/term/' + encodeURIComponent(next) },
    openFile: (path: string) => openFileTab(path),
  }

  const displayName = sessionLabel(name) || name
  const inspectorScope = activeProject ? `${activeProject.name} · ${displayName}` : displayName

  const statusCells = systemCells({
    online,
    node: curNode ? { name: curNode.name, online: curNode.online, latencyMs: curNode.latencyMs } : null,
    hubAlarm: hubHealth.level === 'ok' ? undefined : hubReasonText(hubHealth, t),
    clustered: clusterNodes.length > 0,
    sessions: 1,
    waiting: runtime.activityMap[name]?.waiting ? 1 : 0,
    unfinished: 0,
    agents: agentKinds[name] || nativeId ? 1 : 0,
    version: roamVersion,
    git,
    projectKey: activeProject?.key || '',
    swarms: 0,
    link,
    t,
  })
  const onStatusAction = (a: StatusAction) => {
    if (a.kind === 'route') location.hash = a.id
    else if (a.kind === 'pluginView') location.hash = '#/capabilities/plugins/' + encodeURIComponent(a.id)
  }

  const tabLead = hasSider ? (
    <a href="#/home" className="tt-solo-brand" title={t('nav.home')} aria-label={t('nav.home')}>
      <img src="/logo-mark.svg" width={20} height={20} alt="" aria-hidden="true" />
      <strong className="wd">Roami</strong>
    </a>
  ) : undefined

  const tabEnd = hasSider ? (
    <>
      <button type="button" className="tt-tbtn ico" onClick={openPalette}
        title={`${t('workspace.search')} (${keys.search.label})`} aria-label={t('workspace.search')}>
        <SearchIcon size={15} />
      </button>
      {fsSupported && (
        <button type="button" className="tt-tbtn ico" onClick={toggleFs}
          title={t(isFs ? 'common.exitFullscreen' : 'common.fullscreen')}
          aria-label={t(isFs ? 'common.exitFullscreen' : 'common.fullscreen')} aria-pressed={isFs}>
          {isFs ? <ExitFullscreenIcon size={15} /> : <FullscreenIcon size={15} />}
        </button>
      )}
    </>
  ) : undefined

  return (
    <div className="tt-solo-shell">
      <SessionMemoryAlerts onOpen={paletteActions.openSession} visibleSession={!activeFile ? name : undefined} />
      <UpdateBanner />
      <GlobalSearch items={paletteItems} actions={paletteActions} dir={sessionDir} />
      {hasSider && <div className="tt-global-tabs" ref={setTabBarHost} />}
      <div className="tt-solo-workspace">
        <div className="tt-solo-main">
          <TerminalPane
            terms={[name]}
            active={name}
            setActive={() => setActiveFile('')}
            closeTerm={() => window.close()}
            tabBarHost={hasSider ? tabBarHost : null}
            tabLead={tabLead}
            tabEnd={tabEnd}
            {...runtime}
            sendKey={(seq) => runtime.termRefs.current[name]?.send(seq)}
            agentKinds={agentKinds}
            sessionVisible={!activeFile}
            onCollapse={hasSider ? undefined : () => { location.hash = '#/home' }}
            onOpenSession={paletteActions.openSession}
            onRename={(_, newName) => { location.hash = '#/term/' + encodeURIComponent(newName) }}
            onOpenFile={(path, line) => openFileTab(path, line)}
            onOpenGit={hasSider ? () => showInspector('git') : undefined}
            inspector={hasSider ? { open: !space.inspectorCollapsed, toggle: toggleInspector } : undefined}
            fileTabs={fileTabs}
            activeFile={activeFile}
            sessionTask={() => sessionTaskKey}
            onReturnToSession={activeFile ? () => setActiveFile('') : undefined}
            taskDir={sessionDir}
            onFileTab={(path) => setActiveFile(path)}
            onCloseFile={closeFileTab}
            onPinFile={pinFileTab}
            onFileMode={setFileMode}
            reveal={reveal}
          />
        </div>
        {hasSider && (
          <InspectorColumn
            width={space.inspectorWidth}
            bounds={space.inspectorBounds}
            overlay={!space.large}
            onResize={space.setInspectorWidth}
            onReset={space.resetInspectorWidth}
            collapsed={space.inspectorCollapsed}
            onToggleCollapsed={toggleInspector}
          />
        )}
      </div>
      {hasSider && (
        <InspectorPanels
          open={space.large || !space.inspectorCollapsed}
          panel={panel}
          onPanel={setPanel}
          dir={sessionDir}
          scope={inspectorScope}
          openTerm={paletteActions.openSession}
          onOpenFile={(path) => openFileTab(path)}
          selectedPath={activeFile}
          searchNonce={searchNonce}
          onOpenLine={(path, line) => openFileTab(path, line)}
          onClose={() => { if (!space.inspectorCollapsed) toggleInspector() }}
        />
      )}
      {hasSider && <WorkspaceStatusBar system={statusCells} onAction={onStatusAction} />}
    </div>
  )
}
