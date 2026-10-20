import { useEffect, useRef, useState } from 'react'
import { type InspectorPanelKind } from '../components/shell/InspectorPanels'
import { nextInspector, recallTabInspector, rememberTabInspector, tabKey } from '../components/shell/tab-inspector-memory'

import type { SessionDirectory } from './useSessionDirectory'
import type { TaskWorkspace } from './useTaskWorkspace'
export function useTabInspector(workspace: TaskWorkspace, sessIds: SessionDirectory['sessIds']) {
  const { active, activeFile, taskView, space } = workspace
  const [searchNonce, setSearchNonce] = useState(0)
  const [panel, setPanelLocal] = useState<InspectorPanelKind>(() => {
    try { const v = localStorage.getItem('roam.inspectorPanel'); return v === 'git' || v === 'worktree' ? v : 'files' } catch { return 'files' }
  })
  const setPanel = (p: InspectorPanelKind) => { setPanelLocal(p); try { localStorage.setItem('roam.inspectorPanel', p) } catch { /* 记不住而已 */ } }
  const insTab = tabKey({ active: (active && sessIds?.byName[active]) || active || '', activeFile })
  const rememberIns = (rec: { collapsed: boolean; panel: InspectorPanelKind }) => {
    if (taskView && space.large) rememberTabInspector(insTab, rec)
  }
  const toggleInspector = () => {
    const collapsed = !space.inspectorCollapsed
    space.setInspectorCollapsed(collapsed)
    rememberIns({ collapsed, panel })
  }
  /** 展开右栏（可顺带切面板）：⌘⇧E/G/F、对话工具行的 Git 都走这里 */
  const showInspector = (p?: InspectorPanelKind) => {
    if (p) setPanel(p)
    space.setInspectorCollapsed(false)
    rememberIns({ collapsed: false, panel: p || panel })
  }
  const pickPanel = (p: InspectorPanelKind) => {
    setPanel(p)
    rememberIns({ collapsed: space.inspectorCollapsed, panel: p })
  }
  const insTabRef = useRef('')
  // Only a tab change restores memory; panel changes must not replay that restore.
  useEffect(() => {
    if (!taskView || !space.large) return
    const prev = insTabRef.current
    if (prev === insTab) return
    insTabRef.current = insTab
    if (prev) rememberTabInspector(prev, { collapsed: space.inspectorCollapsed, panel })
    const next = nextInspector(recallTabInspector(insTab), { collapsed: space.inspectorCollapsed, panel })
    if (next.collapsed !== space.inspectorCollapsed) space.setInspectorCollapsed(next.collapsed)
    if (next.panel !== panel) setPanel(next.panel)
  }, [insTab, taskView, space.large])
  const search = () => { showInspector('files'); setSearchNonce(n => n + 1) }
  return { panel, pickPanel, toggleInspector, showInspector, searchNonce, search }
}
