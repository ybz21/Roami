import { useAgentKinds, type AgentKind } from '../agent-kind'
import { ICONS } from '../components/nav-icons'
import { useKeybindings } from '../components/shell/keybindings'
import TerminalPane from '../components/terminal/TerminalPane'
import { useI18n } from '../i18n'
import { CloudIcon } from '../icons'
import { TASK_ROUTE } from '../route-hash'

import { NAV } from './navigation'
import type { AppRoute } from './useAppRoute'
import type { usePageTabs } from './usePageTabs'
import type { useTabInspector } from './useTabInspector'
import type { TaskWorkspace } from './useTaskWorkspace'
import type { useTerminalRuntime } from './useTerminalRuntime'

type TerminalActions = {
  openTerm: TaskWorkspace['openTerm']
  closeTerm: (name: string) => void
  renameOpenTerm: (oldName: string, newName: string) => void
  newTerminalInTask: (kind: 'shell' | AgentKind) => Promise<void>
}
type WorkspaceTerminalsProps = {
  workspace: TaskWorkspace
  runtime: ReturnType<typeof useTerminalRuntime>
  inspector: ReturnType<typeof useTabInspector>
  pages: ReturnType<typeof usePageTabs>
  routing: AppRoute
  hasSider: boolean
  agentKinds: ReturnType<typeof useAgentKinds>
  activeTaskLabel: string
  taskDir: string
  actions: TerminalActions
}
export default function WorkspaceTerminals({ workspace, runtime, inspector, pages, routing, hasSider, agentKinds, activeTaskLabel, taskDir, actions }: WorkspaceTerminalsProps) {
  const { t } = useI18n()
  const keys = useKeybindings()
  const { terms, active, taskView, space, activateSession, setOverlay, fileTabs, curFile, setActiveFile, closeFileTab, pinFileTab, setFileMode, reveal, openFileTab, reorderTerm } = workspace
  const { fontSize, setFontSize, statusMap, setStatus, activityMap, termRefs, claudeMap, claudeView, setClaudeView, codexMap, codexView, setCodexView, setMobileWaiting } = runtime
  const { pageTabs, closePageTab, closePageTabs, tabBarHost } = pages
  const { openTerm, closeTerm, renameOpenTerm, newTerminalInTask } = actions
  const { toggleInspector, showInspector } = inspector
  const { tab, go } = routing
  const sendKey = (seq: string) => active && termRefs.current[active]?.send(seq)
  return (
    <TerminalPane
      terms={terms} active={active} setActive={(n) => { activateSession(n); if (hasSider) go(TASK_ROUTE) }} closeTerm={closeTerm}
      pageTabs={hasSider ? pageTabs.map((key) => ({ key, label: t(key === 'hub' ? 'hub.title' : NAV.find((n) => n.key === key)?.labelKey || `nav.${key}`), icon: key === 'hub' ? <CloudIcon size={16} /> : ICONS[key] })) : undefined}
      activePage={hasSider && !taskView ? tab : undefined}
      onPageTab={go} onClosePage={closePageTab} onClosePages={closePageTabs} tabBarHost={hasSider ? tabBarHost : null}
      fontSize={fontSize} setFontSize={setFontSize} statusMap={statusMap} setStatus={setStatus}
      activityMap={activityMap}
      termRefs={termRefs} sendKey={sendKey}
      claudeMap={claudeMap} claudeView={claudeView} setClaudeView={setClaudeView}
      codexMap={codexMap} codexView={codexView} setCodexView={setCodexView}
      agentKinds={agentKinds}
      onRename={renameOpenTerm}
      onCollapse={hasSider ? undefined : () => { setOverlay(false); space.setDockOpen(false) }}
      onReorder={reorderTerm}
      onNeedsInput={setMobileWaiting}
      onOpenSession={(n) => openTerm(n)}
      onNew={taskView ? { terminal: () => { void newTerminalInTask('shell') }, claude: () => { void newTerminalInTask('claude') }, codex: () => { void newTerminalInTask('codex') }, pi: () => { void newTerminalInTask('pi') }, opencode: () => { void newTerminalInTask('opencode') }, taskLabel: activeTaskLabel } : undefined}
      onOpenFile={taskView ? (path, line) => openFileTab(path, line) : undefined}
      onOpenGit={taskView ? () => showInspector('git') : undefined}
      inspector={taskView ? { open: !space.inspectorCollapsed, toggle: toggleInspector } : undefined}
      fileTabs={hasSider ? fileTabs : undefined} activeFile={hasSider ? curFile : undefined}
      taskDir={taskDir}
      onFileTab={(path) => { setActiveFile(path); if (hasSider) go(TASK_ROUTE) }} onCloseFile={closeFileTab} onPinFile={pinFileTab} onFileMode={setFileMode} reveal={reveal}
      focus={!hasSider || taskView ? undefined : { on: space.focus !== 'none', toggle: space.toggleFocus, hint: keys.focus.label }}
    />
  )
}
