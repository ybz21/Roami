// 项目下按会话的派生关系组织导航，目录归属只用于打开目标。
import { useState, type ReactNode } from 'react'
import { Dropdown, Tooltip } from 'antd'
import { useI18n } from '../../i18n'
import type { AgentKind } from '../../agent-kind'

import { AgentLogo, ChevronDown, CloseIcon, HomeIcon, MoreIcon, OpenInIcon, PencilIcon, PlusIcon, TerminalIcon, TrashIcon } from '../../icons'
import { isLooseTask, taskKeyOf, type TaskKey } from '../sessions/task-key'
import { sessionBranches, type SessionBranch } from './session-lineage'
import type { TaskTree, TreeSession } from './task-tree'

const CLOSED_KEY = 'roam.tree.closed'

/** 行尾的紧凑时间（Orca 的「1d」）：刚刚 / 3m / 2h / 1d——整句「1 分钟前」在 30px 高的行尾放不下 */
function ago(sec: number, t: (k: string) => string): string {
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec))
  if (d < 60) return t('time.justNow')
  if (d < 3600) return `${Math.floor(d / 60)}m`
  if (d < 86400) return `${Math.floor(d / 3600)}h`
  return `${Math.floor(d / 86400)}d`
}

/** 折叠态记本机：默认全展开，只记「收起了哪些项目」，新项目一出现就是展开的 */
function readClosed(): Set<string> {
  try {
    const v = JSON.parse(localStorage.getItem(CLOSED_KEY) || '[]')
    return new Set(Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [])
  } catch { return new Set() }
}
function writeClosed(s: Set<string>) {
  try { localStorage.setItem(CLOSED_KEY, JSON.stringify([...s])) } catch { /* 记不住而已 */ }
}

/** 状态属于具体会话，不向父会话汇总。 */
function dot(o: { running?: boolean; waiting?: boolean }, label: string): ReactNode {
  const tone = o.waiting ? 'wait' : o.running ? 'run' : ''
  return tone ? <i className={`dot ${tone}`} role="img" aria-label={label} /> : null
}

export function ProjectTree({ tree, activeTask, activeSession, onProject, onSession, onAddProject, onRename, onNewTask, onKill, onNewInTask, onRemoveProject }: {
  tree: TaskTree
  activeTask: TaskKey | null
  /** 当前会话用文字和选中线标识。 */
  activeSession: string | null
  onProject: (key: string) => void
  onSession: (key: TaskKey, name: string) => void
  onAddProject?: () => void
  /** 双击 / 右键会话行：改会话展示名 */
  onRename?: (session: string) => void
  /** 项目行右键「开新任务」：弹 composer，目录预设成这个项目、默认新建 worktree */
  onNewTask?: (dir: string) => void
  /** 右键会话行「关闭会话」：真的结束它（标签条的 × 只是收起标签） */
  onKill?: (session: string) => void
  /** 从选中的会话派生子会话，保留实际目录归属。 */
  onNewInTask?: (key: TaskKey, kind: 'shell' | AgentKind, parent?: string) => void
  /** 项目行「…」菜单里的「移除项目」（只动台账，不动目录和会话） */
  onRemoveProject?: (key: string) => void
}) {
  const { t } = useI18n()
  const [closed, setClosed] = useState<Set<string>>(readClosed)
  const toggle = (key: string) => setClosed((cur) => {
    const next = new Set(cur)
    if (next.has(key)) next.delete(key); else next.add(key)
    writeClosed(next)
    return next
  })

  // 所有行都操作真实会话，菜单派生明确绑定当前行。
  const openItem = (task: TaskKey, s: TreeSession) =>
    ({ key: 'open', icon: <OpenInIcon size={14} />, label: t('tree.menu.open'), onClick: () => onSession(task, s.name) })
  const renameSession = (s: TreeSession) => onRename
    ? [{ key: 'rename', icon: <PencilIcon size={14} />, label: t('session.rename'), onClick: () => onRename(s.name) }] : []
  const derive = (task: TaskKey, parent: string) => onNewInTask
    ? [{ type: 'group' as const, label: t('tree.menu.deriveHere'), children: [
      { key: 'sh', icon: <TerminalIcon size={14} />, label: t('tabs.newTerminal'), onClick: () => onNewInTask(task, 'shell', parent) },
      { key: 'cc', icon: <AgentLogo kind="claude" size={14} />, label: t('tabs.newClaude'), onClick: () => onNewInTask(task, 'claude', parent) },
      { key: 'cx', icon: <AgentLogo kind="codex" size={14} />, label: t('tabs.newCodex'), onClick: () => onNewInTask(task, 'codex', parent) },
      { key: 'pi', icon: <AgentLogo kind="pi" size={14} />, label: t('tabs.newPi'), onClick: () => onNewInTask(task, 'pi', parent) },
      { key: 'oc', icon: <AgentLogo kind="opencode" size={14} />, label: t('tabs.newOpenCode'), onClick: () => onNewInTask(task, 'opencode', parent) },
    ] }] : []
  const killSession = (s: TreeSession) => onKill
    ? [{ type: 'divider' as const }, { key: 'kill', icon: <CloseIcon size={14} />, label: t('tree.menu.close'), danger: true, onClick: () => onKill(s.name) }] : []
  const sessionMenu = (task: TaskKey, s: TreeSession) => ({ items: [openItem(task, s), ...renameSession(s), ...derive(task, s.name), ...killSession(s)] })

  // 互审陪跑那一行：缩进半格挂在被审会话下面，名字写「互审 · 被审的是谁」——
  // 它自己的会话名是一串 id（<被审id>-review），照原样印出来没人认得出这是什么。
  const rowLabel = (s: TreeSession) => (s.reviewOf ? t('tree.reviewOf', { name: s.reviewOf }) : s.label)

  const sessionRow = (task: TaskKey, s: TreeSession, showTime: boolean) => (
    <Dropdown key={s.name} trigger={['contextMenu']} menu={sessionMenu(task, s)}>
      <button type="button"
        className={`tt-nav-item tt-tree-row${activeTask === task && activeSession === s.name ? ' on' : ''}${s.dormant ? ' dormant' : ''}`}
        onClick={() => onSession(task, s.name)} title={s.dormant ? t('session.dormant.hint') : s.name} onDoubleClick={onRename ? () => onRename(s.name) : undefined}
        aria-current={activeTask === task && activeSession === s.name ? 'true' : undefined}>
        <span className="ic">{s.agent ? <AgentLogo kind={s.agent} size={15} /> : <TerminalIcon size={15} />}</span>
        <span className="nm">{rowLabel(s)}</span>
        {s.dormant ? <span className="dot sleep" role="img" aria-label={t('tree.dormant')} /> : dot(s, t(s.waiting ? 'mobile.st.waiting' : 'mobile.st.running'))}
        {showTime && !s.dormant && s.at ? <span className="tm">{ago(s.at, t)}</span> : null}
      </button>
    </Dropdown>
  )

  const branchRows = (branch: SessionBranch, depth = 0): ReactNode => (
    <div key={branch.session.name} className="tt-tree-session-branch">
      {sessionRow(branch.task?.key || taskKeyOf(branch.session.name), branch.session, depth === 0)}
      {branch.children.length > 0 && <div className="tt-tree-children" role="group" aria-label={t('session.fork.childOf', { parent: branch.session.label })}>{branch.children.map(child => branchRows(child, depth + 1))}</div>}
    </div>
  )

  return (
    <div className="tt-tree">
      <div className="tt-tree-head">
        <span className="gl">{t('nav.projects')}</span>
        {onAddProject && (
          <Tooltip title={t('tree.addProject')} placement="right">
            <button type="button" className="tt-act ico" onClick={onAddProject} aria-label={t('tree.addProject')}><PlusIcon size={13} /></button>
          </Tooltip>
        )}
      </div>

      {tree.projects.map((p) => {
        const open = !closed.has(p.key)
        const branches = sessionBranches(p.tasks.flatMap(task => task.sessions.map(session => ({ session, task }))))
        return (
          <div key={p.key} className="tt-tree-proj">
            {/* 项目展开状态本地保留；项目主页从菜单进入。 */}
            <button type="button" className={`tt-nav-item tt-tree-row proj${open ? '' : ' closed'}`} title={p.dir}
              aria-expanded={open} onClick={() => toggle(p.key)}>
              <span className="ic"><span className="av">{p.name.slice(0, 1).toUpperCase()}</span></span>
              <span className="nm">{p.name}</span>
              {p.needs > 0 && <span className="bd">{p.needs}</span>}
              <Dropdown trigger={['click']} placement="bottomRight" menu={{ items: [
                { key: 'home', icon: <HomeIcon size={14} />, label: t('tree.menu.projectHome'), onClick: () => onProject(p.key) },
                ...(onRemoveProject ? [{ type: 'divider' as const }, { key: 'remove', icon: <TrashIcon size={14} />, label: t('project.remove'), danger: true, onClick: () => onRemoveProject(p.key) }] : []),
              ] }}>
                <span className="act" role="button" aria-label={t('common.more')} onClick={(e) => e.stopPropagation()}><MoreIcon size={14} /></span>
              </Dropdown>
              {onNewTask && (
                <span className="act" role="button" aria-label={t('tree.menu.newTask')} title={t('tree.menu.newTask')}
                  onClick={(e) => { e.stopPropagation(); onNewTask(p.dir) }}><PlusIcon size={13} /></span>
              )}
              <span className="chev" role="button" aria-label={open ? t('common.collapse') : t('common.expand')}
                onClick={(e) => { e.stopPropagation(); toggle(p.key) }}><ChevronDown size={14} /></span>
            </button>
            {open && <div className="tt-tree-sessions tt-tree-roots">{branches.map(branch => branchRows(branch))}</div>}
          </div>
        )
      })}

      {tree.loose.length > 0 && (
        <div className="tt-tree-proj loose">
          <div className="gl">{t('tree.loose')}</div>
          <div className="tt-tree-sessions tt-tree-roots">{sessionBranches(tree.loose.map(session => ({ session, task: null }))).map(branch => branchRows(branch))}</div>
        </div>
      )}

      {!tree.projects.length && !tree.loose.length && (
        <div className="tt-tree-empty">{t('tree.empty')}</div>
      )}
    </div>
  )
}

/** 树里当前任务的第一个会话名（切任务时没有已开标签就打开它） */
export function firstSessionOf(tree: TaskTree, key: TaskKey): string | null {
  if (isLooseTask(key)) return key.slice('loose:'.length)
  for (const p of tree.projects) for (const task of p.tasks) if (task.key === key) return task.sessions[0]?.name || null
  return null
}

/** 任务的 worktree 路径（散会话没有） */
export function taskPathOf(tree: TaskTree, key: TaskKey): string | null {
  if (isLooseTask(key)) return null
  for (const p of tree.projects) for (const task of p.tasks) if (task.key === key) return task.path
  return null
}
