import { useEffect } from 'react'
import { useSessionProject } from '../components/sessions/session-project'
import { matchHotkey, useKeybindings } from '../components/shell/keybindings'
import { buildTaskTree } from '../components/shell/task-tree'

import type { useTabInspector } from './useTabInspector'
import type { TaskWorkspace } from './useTaskWorkspace'

type ShortcutOptions = {
  hasSider: boolean
  workspace: TaskWorkspace
  inspector: ReturnType<typeof useTabInspector>
  tree: ReturnType<typeof buildTaskTree>
  activeProject: ReturnType<typeof useSessionProject>
  newTerminalInTask: (kind: 'shell') => Promise<void>
  closeTerm: (name: string) => void
  setNewTaskDir: (dir: string) => void
}
export function useWorkspaceShortcuts({ hasSider, workspace, inspector, tree, activeProject, newTerminalInTask, closeTerm, setNewTaskDir }: ShortcutOptions) {
  const keys = useKeybindings()
  const { taskView, space, curFile, active, activeTask, closeFileTab } = workspace
  const { toggleInspector, showInspector, search } = inspector
  useEffect(() => {
    if (!hasSider) return
    const onKey = (e: KeyboardEvent) => {
      const k = keys
      if (matchHotkey(e, k.toggleInspector.key)) {
        e.preventDefault()
        if (taskView) toggleInspector(); else { space.setFocus('none'); space.toggleDock() }
        return
      }
      if (matchHotkey(e, k.focus.key)) {
        e.preventDefault()
        if (taskView) space.setNavCollapsed(!space.navCollapsed); else space.toggleFocus()
        return
      }
      if (matchHotkey(e, k.newTask.key)) {
        e.preventDefault()
        const key = activeTask
        const tr = tree
        const proj = key && tr ? tr.projects.find((p) => p.tasks.some((x) => x.key === key)) : undefined
        const dir = proj?.dir || activeProject?.dir || tr?.projects[0]?.dir
        if (dir) setNewTaskDir(dir)
        return
      }
      if (taskView && matchHotkey(e, k.newTerminal.key)) { e.preventDefault(); void newTerminalInTask('shell'); return }
      if (taskView && matchHotkey(e, k.closeTab.key)) {
        e.preventDefault()
        if (curFile) closeFileTab(curFile); else if (active) closeTerm(active)
        return
      }
      if (taskView && matchHotkey(e, k.searchContent.key)) {
        e.preventDefault()
        search()
        return
      }
      if (taskView && (matchHotkey(e, k.panelFiles.key) || matchHotkey(e, k.panelGit.key))) {
        e.preventDefault()
        showInspector(matchHotkey(e, k.panelFiles.key) ? 'files' : 'git')
        return
      }
      if (e.key === 'Escape') {
        if (taskView) return // 任务视图里 focus 是常态，Esc 没有可退的层
        if (space.mode === 'overlay') space.setDockOpen(false)
        else if (space.focus !== 'none') space.setFocus('none')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [hasSider, space, taskView, curFile, active, keys, activeTask, tree, activeProject, toggleInspector, newTerminalInTask, closeFileTab, closeTerm, showInspector, search, setNewTaskDir])

  return keys
}
