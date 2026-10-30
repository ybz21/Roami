import { useEffect, useMemo, useRef, useState, type SetStateAction } from 'react'
import type { FileTabMode } from '../components/files/FilePathBar'
import { useSessionProjects } from '../components/sessions/session-project'
import { isLooseTask, taskKeyOf, type TaskKey } from '../components/sessions/task-key'
import { pruneTabInspector } from '../components/shell/tab-inspector-memory'
import { reorderTabs } from '../components/shell/tabs'
import { lastTabOf, rememberLastTab } from '../components/shell/task-last-tab'
import { useBackDismiss } from '../components/shell/useBackDismiss'
import { useWorkspaceLayout } from '../components/shell/useWorkspaceLayout'
import { dropDeadTokens, type FileTab } from '../components/terminal/term-tabs-store'
import { TASK_ROUTE } from '../route-hash'
import { useWorkspaceState } from './useWorkspaceState'

import type { SessionDirectory } from './useSessionDirectory'
type TaskWorkspaceOptions = {
  directory: SessionDirectory
  nodeId: string | null
  desktop: boolean
  mobile: boolean
  page: string
  navigate: (route: string) => void
}

export function useTaskWorkspace({ directory: data, nodeId: curNodeId, desktop: hasSider, mobile: isMobile, page: tab, navigate: go }: TaskWorkspaceOptions) {
  const { sessIds, sessList } = data
  const saved = useWorkspaceState(curNodeId, data)
  useEffect(() => {
    if (!sessIds || !data.sessListLoaded || !saved.loaded) return
    saved.update(state => {
      const terms = [...new Set(dropDeadTokens(state.terms, sessIds.byId).map(id => sessIds.byName[id] || id))]
      const selected = sessIds.byName[state.active] || state.active
      return { ...state, terms, active: terms.includes(selected) ? selected : terms[terms.length - 1] || '' }
    })
  }, [sessIds, data.sessListLoaded, saved.loaded, saved.update])
  const toName = (id: string) => sessIds?.byId[id] || id
  const toId = (name: string) => sessIds?.byName[name] || name
  const terms = useMemo(() => saved.state.terms.map(id => sessIds?.byId[id] || id), [saved.state.terms, sessIds])
  const active = saved.state.active ? toName(saved.state.active) : null
  const valueOf = <T,>(action: SetStateAction<T>, value: T): T => typeof action === 'function' ? (action as (value: T) => T)(value) : action
  const setTerms = (action: SetStateAction<string[]>) => saved.update(state => ({ ...state, terms: valueOf(action, state.terms.map(toName)).map(toId) }))
  const setActive = (action: SetStateAction<string | null>) => saved.update(state => ({ ...state, active: toId(valueOf(action, state.active ? toName(state.active) : null) || '') }))
  const projTable = useSessionProjects()
  const taskHint = useRef<Record<string, TaskKey>>({})
  const keyOf = (n: string) => {
    const k = taskKeyOf(n, projTable[n]?.worktree)
    return isLooseTask(k) && taskHint.current[n] ? taskHint.current[n] : k
  }
  const fileTabs = saved.state.files
  const setFileTabs = (action: SetStateAction<FileTab[]>) => saved.update(state => ({ ...state, files: valueOf(action, state.files) }))
  const fileTabsRef = useRef<FileTab[]>([])
  fileTabsRef.current = fileTabs
  const activeFile = saved.state.activeFile
  const setActiveFile = (action: SetStateAction<string>) => saved.update(state => ({ ...state, activeFile: valueOf(action, state.activeFile) }))
  const [reveal, setReveal] = useState<{ path: string; line: number; nonce: number } | undefined>()
  const curFile = activeFile
  const curFileTab = curFile ? fileTabs.find((f) => f.path === curFile) : undefined
  const activeTask: TaskKey | null = curFileTab ? (curFileTab.task || null) : active ? keyOf(active) : null
  const activeTaskRef = useRef<TaskKey | null>(null)
  activeTaskRef.current = activeTask
  useEffect(() => { if (activeTask) rememberLastTab(activeTask, { session: active || undefined, file: curFile || undefined }) }, [activeTask, active, curFile])
  /** 回到任务上次看的那个标签；文件标签还开着才回文件，否则退回会话 */
  const returnToTask = (key: TaskKey, session: string) => {
    const last = lastTabOf(key)
    const file = last?.session === session && last.file && fileTabsRef.current.some((f) => f.path === last.file) ? last.file : ''
    setActive(session); setActiveFile(file)
    go(TASK_ROUTE)
    space.setDockOpen(true); space.setFocus('none')
  }
  const isMd = (p: string) => /\.(md|markdown|mdx|html?)$/i.test(p)
  const openFileTab = (path: string, line?: number) => {
    const key = activeTaskRef.current || ''
    setFileTabs((list) => (list.some((f) => f.path === path) ? list : [...list, { path, preview: false, mode: isMd(path) ? 'preview' : 'source', task: key }]))
    setActiveFile(path)
    if (line && line > 0) setReveal((prev) => ({ path, line, nonce: (prev?.nonce || 0) + 1 }))
  }
  const pinFileTab = (path: string) => setFileTabs((list) => list.map((f) => (f.path === path ? { ...f, preview: false } : f)))
  const setFileMode = (path: string, mode: FileTabMode) => setFileTabs((list) => list.map((f) => (f.path === path ? { ...f, mode, preview: false } : f)))
  const closeFileTab = (path: string) => saved.update(state => {
    const i = state.files.findIndex(file => file.path === path)
    const files = state.files.filter(file => file.path !== path)
    return { ...state, files, activeFile: state.activeFile === path ? (files[i - 1] || files[i])?.path || '' : state.activeFile }
  })
  const activateSession = (n: string) => { setActive(n); setActiveFile('') }
  const [overlay, setOverlay] = useState(false) // 手机/平板全屏终端
  useBackDismiss(isMobile && overlay, () => setOverlay(false))
  const taskView = hasSider && tab === TASK_ROUTE
  const space = useWorkspaceLayout(terms.length > 0 || taskView, taskView)
  useEffect(() => { if (saved.loaded && !terms.length) setOverlay(false) }, [saved.loaded, terms.length])

  useEffect(() => {
    pruneTabInspector([...saved.state.terms.map(id => `s:${id}`), ...fileTabs.map(file => `f:${file.path}`)])
  }, [saved.state.terms, fileTabs])

  const openTerm = (rawName: string, task?: TaskKey) => {
    const name = rawName.replace(/[.:]/g, '_')
    if (!sessList.some((s) => s.name === name)) { data.refresh() }
    setTerms((ts) => ts.includes(name) ? ts : [...ts, name])
    if (task) taskHint.current[name] = task
    setActive(name); setActiveFile('')
    if (hasSider) {
      go(TASK_ROUTE)
      space.setDockOpen(true); space.setFocus('none')
    }
    else setOverlay(true)           // 手机/平板：全屏
  }
  const renameOpenTerm = (oldName: string, newName: string) => {
    if (oldName === newName) return
    // Stable IDs keep the same tab when its display name changes.
    data.rename(oldName, newName)
  }
  const closeTerm = (name: string) => {
    const next = terms.filter(t => t !== name)
    const current = activeTaskRef.current
    const pool = current ? next.filter(n => keyOf(n) === current) : next
    saved.update(state => ({ ...state, terms: state.terms.filter(id => id !== toId(name)), active: state.active === toId(name) ? toId(pool[pool.length - 1] || next[next.length - 1] || '') : state.active }))
    if (!next.length) { setOverlay(false); space.setFocus('none') }
  }
  const reorderTerm = (name: string, to: number) => setTerms((ts) => {
    const cur = activeTaskRef.current
    if (!cur) return reorderTabs(ts, name, to)
    const inTask = (n: string) => keyOf(n) === cur
    const vis = reorderTabs(ts.filter(inTask), name, to)
    let i = 0
    return ts.map((n) => (inTask(n) ? vis[i++] : n))
  })

  return { terms, active, activeFile, fileTabs, curFile, activeTask, activeTaskRef, projTable, keyOf, space, taskView, overlay, setOverlay, openTerm, closeTerm, renameOpenTerm, returnToTask, activateSession, openFileTab, pinFileTab, closeFileTab, setFileMode, setActiveFile, reorderTerm, reveal }
}
export type TaskWorkspace = ReturnType<typeof useTaskWorkspace>
