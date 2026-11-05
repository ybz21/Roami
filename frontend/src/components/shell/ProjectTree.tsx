// 项目 → 工作区 → 会话；单会话同名时合成一行。
import { useState, type ReactNode } from 'react'
import { Dropdown, Tooltip } from 'antd'
import { useI18n } from '../../i18n'
import type { AgentKind } from '../../agent-kind'

import { AgentLogo, ArchiveIcon, ChevronDown, CloseIcon, HomeIcon, MoreIcon, OpenInIcon, PencilIcon, PlusIcon, TerminalIcon, TrashIcon, WorktreeIcon } from '../../icons'
import { isLooseTask, taskKeyOf, type TaskKey } from '../sessions/task-key'
import { sessionBranches, type SessionBranch } from './session-lineage'
import type { TaskTree, TreeSession, TreeTask } from './task-tree'

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

/** 工作区不重复汇总会话状态。 */
function dot(o: { running?: boolean; waiting?: boolean }, label: string): ReactNode {
  const tone = o.waiting ? 'wait' : o.running ? 'run' : ''
  return tone ? <i className={`dot ${tone}`} role="img" aria-label={label} /> : null
}

export function ProjectTree({ tree, activeTask, activeSession, onProject, onTask, onSession, onAddProject, onRename, onRenameTask, onNewTask, onKill, onFinishTask, onNewInTask, onRemoveProject }: {
  tree: TaskTree
  activeTask: TaskKey | null
  /** 当前会话用文字和选中线标识。 */
  activeSession: string | null
  onProject: (key: string) => void
  onTask: (key: TaskKey) => void
  onSession: (key: TaskKey, name: string) => void
  onAddProject?: () => void
  /** 双击 / 右键会话行：改会话展示名 */
  onRename?: (session: string) => void
  /** 双击 / 右键任务行：给任务起名（偏好 taskNames），不动会话和分支 */
  onRenameTask?: (key: TaskKey, name: string) => void
  /** 项目行右键「开新任务」：弹 composer，目录预设成这个项目、默认新建 worktree */
  onNewTask?: (dir: string) => void
  /** 右键会话行「关闭会话」：真的结束它（标签条的 × 只是收起标签） */
  onKill?: (session: string) => void
  /** 右键任务行「收尾」：关掉它的会话并处理 worktree */
  onFinishTask?: (task: TreeTask) => void
  /** 右键任务行：在它的 worktree 里派生一个终端 / Claude / Codex */
  onNewInTask?: (key: TaskKey, kind: 'shell' | AgentKind, parent?: string) => void
  /** 项目行「…」菜单里的「移除项目」（只动台账，不动目录和会话） */
  onRemoveProject?: (key: string) => void
}) {
  const { t, locale } = useI18n()
  const tasks = new Map(tree.projects.flatMap(project => project.tasks.map(task => [task.key, task] as const)))
  const [closed, setClosed] = useState<Set<string>>(readClosed)
  // 「显示空闲 worktree」：没会话的 worktree 平时不进树（Orca 的 hidden worktrees），从「…」菜单打开才列出来；纯视图态
  const [showIdle, setShowIdle] = useState<Set<string>>(() => new Set())
  const toggle = (key: string) => setClosed((cur) => {
    const next = new Set(cur)
    if (next.has(key)) next.delete(key); else next.add(key)
    writeClosed(next)
    return next
  })

  // 合成行保留会话动作，分组标题保留工作区动作。
  const openItem = (task: TaskKey, s: TreeSession) =>
    ({ key: 'open', icon: <OpenInIcon size={14} />, label: t('tree.menu.open'), onClick: () => onSession(task, s.name) })
  const renameSession = (s: TreeSession) => onRename
    ? [{ key: 'rename', icon: <PencilIcon size={14} />, label: t('session.rename'), onClick: () => onRename(s.name) }] : []
  const renameTask = (task: TreeTask) => onRenameTask
    ? [{ key: 'name', icon: <PencilIcon size={14} />, label: t('tree.renameTask'), onClick: () => onRenameTask(task.key, task.name) }] : []
  const derive = (task: TreeTask, parent?: string) => onNewInTask
    ? [{ type: 'group' as const, label: t('tree.menu.deriveHere'), children: [
      { key: 'sh', icon: <TerminalIcon size={14} />, label: t('tabs.newTerminal'), onClick: () => onNewInTask(task.key, 'shell', parent) },
      { key: 'cc', icon: <AgentLogo kind="claude" size={14} />, label: t('tabs.newClaude'), onClick: () => onNewInTask(task.key, 'claude', parent) },
      { key: 'cx', icon: <AgentLogo kind="codex" size={14} />, label: t('tabs.newCodex'), onClick: () => onNewInTask(task.key, 'codex', parent) },
      { key: 'pi', icon: <AgentLogo kind="pi" size={14} />, label: t('tabs.newPi'), onClick: () => onNewInTask(task.key, 'pi', parent) },
      { key: 'oc', icon: <AgentLogo kind="opencode" size={14} />, label: t('tabs.newOpenCode'), onClick: () => onNewInTask(task.key, 'opencode', parent) },
    ] }] : []
  const killSession = (s: TreeSession) => onKill
    ? [{ type: 'divider' as const }, { key: 'kill', icon: <CloseIcon size={14} />, label: t('tree.menu.close'), danger: true, onClick: () => onKill(s.name) }] : []
  const finishTask = (task: TreeTask) => onFinishTask && !task.main
    ? [{ type: 'divider' as const }, { key: 'finish', icon: <ArchiveIcon size={14} />, label: t('tree.menu.finish'), danger: true, onClick: () => onFinishTask(task) }] : []

  const sessionMenu = (task: TaskKey, s: TreeSession) => ({ items: [openItem(task, s), ...renameSession(s), ...(tasks.has(task) ? derive(tasks.get(task)!, s.name) : []), ...killSession(s)] })
  const taskMenu = (task: TreeTask) => ({ items: [...renameTask(task), ...derive(task), ...finishTask(task)] })

  /**
   * 合成行的菜单（见下面 soleRow）。**不是把两张菜单拼起来**——拼出来的那张里，
   * 同一件事印了两遍：任务只有一个会话时，「收尾」走的就是 finishTask → beginClose(那个会话)，
   * 和「关闭会话」一字不差，而且两枚都是红的；两个「重命名」也只是改同一个名字
   * （任务没单独起过名时，任务名本来就跟着这个会话的 label 走）。
   * 所以各留一枚：重命名留会话那枚（它改的是真名字，标签、树、CLI 都跟着变），
   * 红的那枚留「关闭会话」（它写明了后果是结束进程；worktree 怎么处置由随后的弹窗问）。
   */
  const soleMenu = (task: TreeTask, s: TreeSession) => ({ items: [
    openItem(task.key, s),
    ...renameSession(s),
    ...derive(task, s.name),
    ...(onKill ? killSession(s) : finishTask(task)),
  ] })

  // 互审陪跑那一行：缩进半格挂在被审会话下面，名字写「互审 · 被审的是谁」——
  // 它自己的会话名是一串 id（<被审id>-review），照原样印出来没人认得出这是什么。
  const rowLabel = (s: TreeSession) => (s.reviewOf ? t('tree.reviewOf', { name: s.reviewOf }) : s.label)

  const sessionRow = (task: TaskKey, s: TreeSession, showTime = true, workspace?: string) => (
    <Dropdown key={s.name} trigger={['contextMenu']} menu={sessionMenu(task, s)}>
      <button type="button"
        className={`tt-nav-item tt-tree-row${activeTask === task && activeSession === s.name ? ' on' : ''}${s.dormant ? ' dormant' : ''}`}
        onClick={() => onSession(task, s.name)} title={s.dormant ? t('session.dormant.hint') : s.name} onDoubleClick={onRename ? () => onRename(s.name) : undefined}
        aria-current={activeTask === task && activeSession === s.name ? 'true' : undefined}>
        <span className="ic">{s.agent ? <AgentLogo kind={s.agent} size={15} /> : <TerminalIcon size={15} />}</span>
        <span className="session-title">
          <span className="nm">{rowLabel(s)}</span>
          {workspace && <span className="lineage-origin">{t('tree.workspaceName', { name: workspace })}</span>}
        </span>
        {s.dormant ? <span className="dot sleep" role="img" aria-label={t('tree.dormant')} /> : dot(s, t(s.waiting ? 'mobile.st.waiting' : 'mobile.st.running'))}
        {showTime && !s.dormant && s.at ? <span className="tm">{ago(s.at, t)}</span> : null}
      </button>
    </Dropdown>
  )

  // 类型文字与层级线区分工作区和同名会话。
  const taskHead = (task: TreeTask, badge: ReactNode, on: boolean) => (
    <Dropdown trigger={['contextMenu']} menu={taskMenu(task)}>
      <button type="button" className={`tt-nav-item tt-tree-row head workspace-head${on ? ' on' : ''}`}
        onClick={() => onTask(task.key)} title={task.path} aria-current={on ? 'true' : undefined}
        onDoubleClick={onRenameTask ? () => onRenameTask(task.key, task.name) : undefined}>
        <span className="ic"><WorktreeIcon size={15} /></span>
        <span className="workspace-title">
          <span className="nm">{task.name}</span>
          <span className="workspace-meta">{task.sessions.length ? t('tree.workspaceSessions', { n: new Intl.NumberFormat(locale).format(task.sessions.length) }) : t('tree.workspace')}</span>
        </span>
        {badge}
      </button>
    </Dropdown>
  )

  // 任务徽标：只剩「未合入」。「主仓库」那一枚去掉了——项目行下面第一张卡本来就是主仓库，
  // 它不是需要被指出来的状态，只是把每一行都挤窄一截。
  const taskBadge = (task: TreeTask) => task.unfinished
    ? <span className="bd" title={t('tree.unfinished', { n: task.ahead })}>{t('tree.unfinishedShort', { n: task.ahead })}</span>
    : null

  // 同名且只有一个会话时，保留紧凑的合成行。
  const soleRow = (task: TreeTask, s: TreeSession) => (
    <Dropdown key={s.name} trigger={['contextMenu']} menu={soleMenu(task, s)}>
      <button type="button"
        className={`tt-nav-item tt-tree-row head${activeTask === task.key && (!activeSession || activeSession === s.name) ? ' on' : ''}${s.dormant ? ' dormant' : ''}`}
        onClick={() => onSession(task.key, s.name)} title={s.dormant ? t('session.dormant.hint') : task.path}
        onDoubleClick={onRename ? () => onRename(s.name) : undefined}
        aria-current={activeTask === task.key && (!activeSession || activeSession === s.name) ? 'true' : undefined}>
        <span className="ic">{s.agent ? <AgentLogo kind={s.agent} size={15} /> : <TerminalIcon size={15} />}</span>
        <span className="nm">{s.label}</span>
        {task.unfinished && taskBadge(task)}
        {s.dormant ? <span className="dot sleep" role="img" aria-label={t('tree.dormant')} /> : dot(s, t(s.waiting ? 'mobile.st.waiting' : 'mobile.st.running'))}
        {!s.dormant && s.at ? <span className="tm">{ago(s.at, t)}</span> : null}
      </button>
    </Dropdown>
  )

  const branchRows = (branch: SessionBranch, anchor: TreeTask | null, showTime: boolean): ReactNode => (
    <div key={branch.session.name} className="tt-tree-session-branch">
      {sessionRow(branch.task?.key || taskKeyOf(branch.session.name), branch.session, showTime,
        branch.task && branch.task.key !== anchor?.key ? branch.task.name : undefined)}
      {branch.children.length > 0 && <div className="tt-tree-children" role="group" aria-label={t('session.fork.childOf', { parent: branch.session.label })}>{branch.children.map(child => branchRows(child, anchor, showTime))}</div>}
    </div>
  )

  const taskRows = (task: TreeTask, branches: SessionBranch[], projName?: string) => {
    if (!branches.length) return null
    const on = activeTask === task.key
    const hasActive = task.sessions.some((s) => s.name === activeSession)
    const own = task.sessions.filter((x) => !x.reviewOf) // 互审是附属，不算「这个任务有几个会话」
    const sole = own.length === 1 && task.sessions.length === 1 && own[0].label === task.name ? own[0] : null
    if (sole) return <div key={task.key} className={`tt-tree-task${on ? ' on' : ''}`}>
      {soleRow(task, sole)}
      {branches[0].children.length > 0 && <div className="tt-tree-sessions tt-tree-children" role="group" aria-label={t('session.fork.childOf', { parent: sole.label })}>{branches[0].children.map(child => branchRows(child, task, false))}</div>}
    </div>
    // 「项目目录」这张兜底卡（非 git 项目的会话都挂在这儿）跟项目行同名：
    // 头行再印一遍项目名是纯噪音——项目行本来就在它上面一行。只画会话，
    // 派生/收尾这些动作项目行的 ⋯ 里都有。
    const bare = !!task.main && !!projName && task.name === projName
    return (
      <div key={task.key} className={`tt-tree-task${bare ? '' : ' grouped'}${on ? ' on' : ''}`} role="group" aria-label={t('tree.workspaceName', { name: task.name })}>
        {!bare && taskHead(task, taskBadge(task), on && !hasActive)}
        <div className="tt-tree-sessions">{branches.map(branch => branchRows(branch, task, bare))}</div>
      </div>
    )
  }

  // 空闲 / 待收尾的 worktree：淡一档的卡，没有会话行；右键（或「…」）能派生、收尾
  const idleCard = (task: TreeTask) => (
    <div key={task.key} className="tt-tree-task idle">
      {taskHead(task, <span className="bd">{task.unfinished ? t('tree.unfinishedShort', { n: task.ahead }) : t('tree.idle')}</span>, false)}
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
        // 项目下只列**有会话的任务**。没会话的 worktree（待收尾 / 空闲）不进树：它们是 worktree
        // 不是活着的任务，用户记不住也不该在这里管——待收尾的数量在项目行徽标上，处理去右栏
        // Worktree 面板或项目主页
        const branches = sessionBranches(p.tasks.flatMap(task => task.sessions.map(session => ({ session, task }))))
        const live = p.tasks.filter((x) => x.sessions.length > 0)
        const idle = p.tasks.filter((x) => x.sessions.length === 0)
        return (
          <div key={p.key} className="tt-tree-proj">
            {/* 项目行右端照 Orca：[…] 菜单 · [+] 开任务 · [˅] 折叠，都是看得见的按钮，不靠右键 */}
            {/* 点整行 = 展开/收起，不是跳项目主页：树是拿来找会话的，找会话的动作应该就地发生，
                点一下却整页换掉，回头还得再点回来。去主页留在「…」菜单第一项。
                展开状态跟任务卡共用同一份 localStorage（roam.tree.closed），刷新/重开都还在。 */}
            <button type="button" className={`tt-nav-item tt-tree-row proj${open ? '' : ' closed'}`} title={p.dir}
              aria-expanded={open} onClick={() => toggle(p.key)}>
              <span className="ic"><span className="av">{p.name.slice(0, 1).toUpperCase()}</span></span>
              <span className="nm">{p.name}</span>
              {p.needs > 0 && <span className="bd">{p.needs}</span>}
              <Dropdown trigger={['click']} placement="bottomRight" menu={{ items: [
                { key: 'home', icon: <HomeIcon size={14} />, label: t('tree.menu.projectHome'), onClick: () => onProject(p.key) },
                { key: 'idle', icon: <WorktreeIcon size={14} />, label: showIdle.has(p.key) ? t('tree.menu.hideIdle') : t('tree.menu.showIdle', { n: idle.length }), disabled: !idle.length && !showIdle.has(p.key),
                  onClick: () => setShowIdle((cur) => { const next = new Set(cur); if (next.has(p.key)) next.delete(p.key); else next.add(p.key); return next }) },
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
            {open && (
              <>
                {live.map((x) => taskRows(x, branches.filter(branch => branch.task?.key === x.key), p.name))}
                {showIdle.has(p.key) && idle.map((x) => idleCard(x))}
              </>
            )}
          </div>
        )
      })}

      {tree.loose.length > 0 && (
        <div className="tt-tree-proj loose">
          <div className="gl">{t('tree.loose')}</div>
          {sessionBranches(tree.loose.map(session => ({ session, task: null }))).map(branch => branchRows(branch, null, true))}
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
