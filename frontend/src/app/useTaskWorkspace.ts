import { useEffect, useRef, useState } from 'react'
import type { FileTabMode } from '../components/files/FilePathBar'
import { useSessionProjects } from '../components/sessions/session-project'
import { isLooseTask, taskKeyOf, type TaskKey } from '../components/sessions/task-key'
import { pruneTabInspector } from '../components/shell/tab-inspector-memory'
import { reorderTabs } from '../components/shell/tabs'
import { lastTabOf, rememberLastTab } from '../components/shell/task-last-tab'
import { useBackDismiss } from '../components/shell/useBackDismiss'
import { useWorkspaceLayout } from '../components/shell/useWorkspaceLayout'
import { dropDeadTokens, loadTabs, saveTabs, type FileTab } from '../components/terminal/term-tabs-store'
import { TASK_ROUTE, getHashParams, readTermTokens, setHashParams } from '../route-hash'

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
  const [terms, setTerms] = useState<string[]>([])
  const [active, setActive] = useState<string | null>(null)
  const projTable = useSessionProjects()
  const taskHint = useRef<Record<string, TaskKey>>({})
  const keyOf = (n: string) => {
    const k = taskKeyOf(n, projTable[n]?.worktree)
    return isLooseTask(k) && taskHint.current[n] ? taskHint.current[n] : k
  }
  const [fileTabs, setFileTabs] = useState<FileTab[]>([])
  const fileTabsRef = useRef<FileTab[]>([])
  fileTabsRef.current = fileTabs
  const [activeFile, setActiveFile] = useState('')
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
  const closeFileTab = (path: string) => {
    setFileTabs((list) => {
      const i = list.findIndex((f) => f.path === path)
      const next = list.filter((f) => f.path !== path)
      setActiveFile((cur) => (cur === path ? (next[i - 1] || next[i])?.path || '' : cur))
      return next
    })
  }
  const activateSession = (n: string) => { setActive(n); setActiveFile('') }
  const urlTerms = useRef<string[]>(readTermTokens().terms)
  const urlActive = useRef<string>(readTermTokens().active)
  const noTabs = useRef(readTermTokens().none)
  const restored = useRef(false) // 还原完成前不许回写 URL，否则会把待还原的参数抹掉
  const [overlay, setOverlay] = useState(false) // 手机/平板全屏终端
  useBackDismiss(isMobile && overlay, () => setOverlay(false))
  const taskView = hasSider && tab === TASK_ROUTE
  const space = useWorkspaceLayout(terms.length > 0 || taskView, taskView)

  useEffect(() => {
    if (!sessIds || restored.current) return
    restored.current = true
    const toName = (tok: string) => sessIds.byId[tok] || tok
    const fromUrl = urlTerms.current
    const saved = fromUrl.length || noTabs.current ? null : loadTabs(curNodeId)
    if (saved && !urlActive.current) urlActive.current = saved.active
    const names = Array.from(new Set(dropDeadTokens(saved ? saved.terms : fromUrl, sessIds.byId).map(toName)))
    if (!names.length) return
    const stored = saved || loadTabs(curNodeId)
    if (stored.files.length) { setFileTabs(stored.files); setActiveFile(stored.activeFile) }
    setTerms((cur) => (cur.length ? cur : names))
    setActive((cur) => {
      if (cur) return cur
      const a = urlActive.current ? toName(urlActive.current) : ''
      return a && names.includes(a) ? a : names[names.length - 1]
    })
  }, [sessIds, curNodeId])

  useEffect(() => {
    if (!restored.current) return
    if (noTabs.current) {
      // A clean mirror page must not erase another page's saved workspace.
      if (!terms.length) return   // 还是那页干净的镜像页：URL 保持 terms=none，本机记忆不动
      noTabs.current = false      // 这页开了会话 → 回到普通页面的存续规则
    }
    const toTok = (n: string) => sessIds?.byName[n] || n
    const toks = terms.map(toTok)
    const activeTok = active ? toTok(active) : ''
    setHashParams({
      ...Object.fromEntries(getHashParams()),
      terms: toks.map(encodeURIComponent).join(','),
      active: activeTok ? encodeURIComponent(activeTok) : '',
    })
    saveTabs(curNodeId, toks, activeTok, fileTabs, activeFile)
    pruneTabInspector([...toks.map((t) => `s:${t}`), ...fileTabs.map((f) => `f:${f.path}`)])
  }, [terms, active, fileTabs, activeFile, sessIds, curNodeId])

  const openTerm = (rawName: string, task?: TaskKey) => {
    const name = rawName.replace(/[.:]/g, '_')
    if (!sessList.some((s) => s.name === name)) { data.refresh() }
    setTerms((ts) => (hasSider ? (ts.includes(name) ? ts : [...ts, name]) : [name]))
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
    setTerms((ts) => Array.from(new Set(ts.map((t) => (t === oldName ? newName : t)))))
    setActive((a) => (a === oldName ? newName : a))
    // Preserve the URL identity while the next directory refresh catches up.
    data.rename(oldName, newName)
  }
  const closeTerm = (name: string) => {
    setTerms((ts) => {
      const next = ts.filter((t) => t !== name)
      const cur = activeTaskRef.current
      const pool = cur ? next.filter((n) => keyOf(n) === cur) : next
      setActive((a) => (a === name ? (pool[pool.length - 1] || null) : a))
      if (next.length === 0) { setOverlay(false); space.setFocus('none') }
      return next
    })
  }
  const reorderTerm = (name: string, to: number) => setTerms((ts) => {
    const cur = activeTaskRef.current
    if (!cur) return reorderTabs(ts, name, to)
    const inTask = (n: string) => keyOf(n) === cur
    const vis = reorderTabs(ts.filter(inTask), name, to)
    let i = 0
    return ts.map((n) => (inTask(n) ? vis[i++] : n))
  })

  return { terms, active, activeFile, fileTabs, curFile, activeTask, activeTaskRef, projTable, keyOf, space, taskView, overlay, setOverlay, noTabs, openTerm, closeTerm, renameOpenTerm, returnToTask, activateSession, openFileTab, pinFileTab, closeFileTab, setFileMode, setActiveFile, reorderTerm, reveal }
}
export type TaskWorkspace = ReturnType<typeof useTaskWorkspace>
