import {
  App as AntApp,
  Input,
  Modal,
  Select
} from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { agentCommand } from '../agent-command'
import { useAgentKinds, type AgentKind } from '../agent-kind'
import { api } from '../api'
import { NewProjectModal } from '../components/projects/Projects'
import RenameSessionModal from '../components/sessions/RenameSessionModal'
import { TaskComposer } from '../components/sessions/TaskComposer'
import { useSessionCloser } from '../components/sessions/session-closer'
import { sessionLabel } from '../components/sessions/session-label'
import { sessionProject } from '../components/sessions/session-project'
import { isLooseTask, looseSessionOf, type TaskKey } from '../components/sessions/task-key'
import { firstSessionOf, taskPathOf } from '../components/shell/ProjectTree'
import { lastTabOf } from '../components/shell/task-last-tab'
import { buildTaskTree, type TreeTask } from '../components/shell/task-tree'
import { type TreeSrc } from '../components/shell/task-tree-snapshot'
import { useI18n } from '../i18n'
import { savePreferences, usePreferences } from '../preferences'
import { TASK_ROUTE, getHashParams } from '../route-hash'

import type { ProjectDirectory } from './useProjectDirectory'
import type { SessionDirectory } from './useSessionDirectory'
import type { TaskWorkspace } from './useTaskWorkspace'
import type { useTerminalRuntime } from './useTerminalRuntime'

type ProjectActionOptions = {
  data: SessionDirectory
  directory: ProjectDirectory
  workspace: TaskWorkspace
  runtime: ReturnType<typeof useTerminalRuntime>
  isMobile: boolean
  agentKinds: ReturnType<typeof useAgentKinds>
  go: (route: string) => void
}
export function useProjectActions({ data, directory, workspace, runtime, isMobile, agentKinds, go }: ProjectActionOptions) {
  const { terms, active, activeTask, activeTaskRef, projTable, keyOf, space, returnToTask } = workspace
  const { sessIds, sessList, sessListLoaded } = data
  const { treeSrc, treeSrcRef, setTreeSrc } = directory
  const { claudeMap, codexMap, termRefs } = runtime
  const [prefs] = usePreferences()
  const { t } = useI18n()
  const openTerm = (name: string, task?: TaskKey) => {
    if (!sessList.some(s => s.name === name.replace(/[.:]/g, '_'))) directory.refresh()
    workspace.openTerm(name, task)
  }
  const closer = useSessionCloser(closeTerm, () => { data.refresh(); directory.refresh() })
  const [renameInTree, setRenameInTree] = useState<string | null>(null)
  const [renameTask, setRenameTask] = useState<{ key: TaskKey; name: string } | null>(null)
  const [renameTaskVal, setRenameTaskVal] = useState('')
  const [newTaskDir, setNewTaskDir] = useState<string | null>(null)
  const quickTaskOpening = useRef(false)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const { message: antMessage, modal: antModal } = AntApp.useApp()
  useEffect(() => {
    if (!isMobile) return
    const openQuickTask = () => {
      if (location.hash.split('?')[0] !== '#/projects' || getHashParams().get('compose') !== '1' || quickTaskOpening.current) return
      quickTaskOpening.current = true
      const open = (projects: TreeSrc['projects']) => {
        const params = getHashParams()
        params.delete('compose')
        const query = params.toString()
        history.replaceState(history.state, '', '#/projects' + (query ? '?' + query : ''))
        const dir = projects[0]?.dir
        if (dir) setNewTaskDir(dir)
        else setNewProjectOpen(true)
        quickTaskOpening.current = false
      }
      const known = treeSrcRef.current.projects
      if (known.length) { open(known); return }
      api('GET', '/projects').then((r) => {
        const projects = (r?.data?.projects || []) as TreeSrc['projects']
        setTreeSrc((cur) => ({ ...cur, projects }))
        open(projects)
      }).catch((e: Error) => { quickTaskOpening.current = false; antMessage.error(e.message) })
    }
    openQuickTask()
    window.addEventListener('hashchange', openQuickTask)
    return () => window.removeEventListener('hashchange', openQuickTask)
  }, [isMobile, antMessage])
  const tree = useMemo(() => buildTaskTree({
    projects: treeSrc.projects, worktrees: treeSrc.worktrees, sessions: sessList, placement: projTable,
    nameOf: (p) => prefs.taskNames?.[p] || undefined,
    agentOf: (n) => agentKinds[n] || (claudeMap[n]?.running ? 'claude' : codexMap[n]?.running ? 'codex' : undefined),
    sessionsLoaded: sessListLoaded,
    nameOfId: (id) => sessIds?.byId[id],
  }), [treeSrc, sessList, agentKinds, claudeMap, codexMap, projTable, prefs.taskNames, sessIds, sessListLoaded])

  const onTreeTask = (key: TaskKey) => {
    const open = terms.filter((n) => keyOf(n) === key)
    if (open.length) {
      const last = lastTabOf(key)
      returnToTask(key, active && open.includes(active) ? active : last?.session && open.includes(last.session) ? last.session : open[open.length - 1])
      return
    }
    else {
      const first = firstSessionOf(tree, key)
      if (first) { openTerm(first, key); return }
    }
    go(TASK_ROUTE)
    space.setDockOpen(true); space.setFocus('none')
  }
  const activeTaskLabel = activeTask
    ? (isLooseTask(activeTask) ? sessionLabel(looseSessionOf(activeTask)) : tree.projects.flatMap((p) => p.tasks).find((x) => x.key === activeTask)?.name || activeTask.split('/').pop() || '')
    : ''
  const onTreeProject = (key: string) => go('projects/' + encodeURIComponent(key))
  async function newTerminalInTask(kind: 'shell' | AgentKind = 'shell', keyArg?: TaskKey) {
    const key = keyArg ?? activeTaskRef.current
    const dir = key ? (taskPathOf(tree, key) || sessionProject(looseSessionOf(key))?.dir || '') : ''
    const first = key ? firstSessionOf(tree, key) : null
    await newTerminalAt(kind, dir, (first && sessionLabel(first)) || 'shell', key || undefined)
  }
  const newTerminalAt = async (kind: 'shell' | AgentKind, dir: string, baseArg?: string, key?: TaskKey) => {
    const base = baseArg || (dir ? dir.split('/').pop() : '') || 'shell'
    const suffix = ({ shell: 'sh', claude: 'cc', codex: 'cx', pi: 'pi', opencode: 'oc' } as const)[kind]
    let name = `${base}-${suffix}`
    const taken = new Set(sessList.map((s) => s.label || s.name))
    for (let i = 2; taken.has(name); i++) name = `${base}-${suffix}${i}`
    try {
      const res = await api('POST', '/sessions', dir ? { name, dir } : { name })
      const actual = res?.name || name
      if (kind !== 'shell') {
        const cmd = agentCommand(kind, prefs)
        await api('POST', '/tasks/_/send', { sess: actual, msg: cmd })
      }
      openTerm(actual, key)
    } catch (e: any) { antMessage.error(e.message) }
  }
  const renameOpenTerm = (oldName: string, newName: string) => { workspace.renameOpenTerm(oldName, newName); runtime.rename(oldName, newName) }
  function closeTerm(name: string) { workspace.closeTerm(name); delete termRefs.current[name] }
  const finishTask = (task: TreeTask) => {
    const [first, ...rest] = task.sessions.map((s) => s.name)
    if (!first) return
    if (!rest.length) { void closer.beginClose(first); return }
    antModal.confirm({
      title: t('tree.finishTaskConfirm', { name: task.name, n: task.sessions.length }),
      okText: t('common.confirm'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
      onOk: async () => { for (const n of rest) await closer.kill(n); await closer.beginClose(first) },
    })
  }
  const removeProject = (key: string) => antModal.confirm({
    title: t('project.removeConfirm'), okText: t('project.remove'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
    onOk: async () => { try { await api('DELETE', `/projects/${encodeURIComponent(key)}`); antMessage.success(t('project.removed')); directory.refresh() } catch (e: any) { antMessage.error(e.message) } },
  })
  const desktopDialogs = <>
    <RenameSessionModal session={renameInTree} onClose={() => setRenameInTree(null)} onDone={renameOpenTerm} />
    {closer.node}
    <Modal open={!!renameTask} title={t('tree.renameTask')} okText={t('common.confirm')} cancelText={t('common.cancel')} destroyOnClose
      onCancel={() => setRenameTask(null)}
      onOk={() => {
        if (!renameTask) return
        const v = renameTaskVal.trim()
        const next = { ...(prefs.taskNames || {}) }
        if (v) next[renameTask.key] = v; else delete next[renameTask.key]
        savePreferences({ taskNames: next })
        setRenameTask(null)
      }}>
      <Input autoFocus value={renameTaskVal} onChange={(e) => setRenameTaskVal(e.target.value)} placeholder={renameTask?.name}
        onPressEnter={() => document.querySelector<HTMLButtonElement>('.ant-modal .ant-btn-primary')?.click()} />
      <div style={{ marginTop: 'var(--sp-2)', color: 'var(--text-dimmer)', fontSize: 'var(--fs-meta)' }}>{t('tree.taskNameHint')}</div>
    </Modal>
  </>
  const dialogs = <>
    <Modal className="tt-newtask-modal" open={!!newTaskDir} footer={null} width={860} destroyOnClose onCancel={() => setNewTaskDir(null)} title={t('tree.newTask')}>
      {newTaskDir && (
        <>
          <div className="tt-lbl">{t('tree.projectField')}</div>
          <Select value={newTaskDir} onChange={(v) => setNewTaskDir(v)} style={{ width: '100%', marginBottom: 'var(--sp-3)' }}
            options={treeSrc.projects.map((p: any) => ({ value: p.dir, label: isMobile ? p.name : <span>{p.name} <span style={{ color: 'var(--text-dimmer)', fontFamily: 'var(--mono)', fontSize: 'var(--fs-micro)', marginLeft: 'var(--sp-2)' }}>{p.dir}</span></span> }))} />
          <TaskComposer key={newTaskDir} dir={newTaskDir} isGit={treeSrc.projects.find((p: any) => p.dir === newTaskDir)?.git !== false}
            openTerm={openTerm} onCreated={() => setNewTaskDir(null)} autoFocus={!isMobile} />
        </>
      )}
    </Modal>
    {/* 建完立刻刷树：项目列表 15s 一轮、worktree 60s 一轮，不刷就得等 */}
    <NewProjectModal open={newProjectOpen} onClose={() => setNewProjectOpen(false)} onCreated={() => directory.refresh()} />

  </>
  return {
    tree, openTerm, closeTerm, renameOpenTerm, onTreeTask, onTreeProject, newTerminalInTask, newTerminalAt, activeTaskLabel, finishTask, removeProject,
    newTask: (dir?: string) => { const d = dir || treeSrc.projects[0]?.dir; if (d) setNewTaskDir(d); else setNewProjectOpen(true) },
    setNewTaskDir, addProject: () => setNewProjectOpen(true), renameSession: setRenameInTree,
    renameTask: (key: TaskKey, name: string) => { setRenameTask({ key, name }); setRenameTaskVal(prefs.taskNames?.[key] || name) },
    kill: (name: string) => { void closer.beginClose(name) }, desktopDialogs, dialogs
  }
}
export type ProjectActions = ReturnType<typeof useProjectActions>
