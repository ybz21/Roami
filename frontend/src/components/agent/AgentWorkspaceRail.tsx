import type { ReactNode } from 'react'
import { Tabs } from 'antd'
import { BotIcon, ChecklistIcon, ClockIcon, CloseIcon, NotebookIcon, TerminalIcon } from '../../icons'
import { useI18n } from '../../i18n'
import AgentWorkspaceActivity from './AgentWorkspaceActivity'
import AgentTasks from './AgentTasks'
import AgentMemory from './AgentMemory'
import AgentReminders from './AgentReminders'
import type { AgentActivityItem } from './agent-protocol'
import type { WorkspaceTab } from './useAgentWorkspace'
import './agent-notifications.css'
import './agent-workspace.css'

export default function AgentWorkspaceRail({ cid, branch, activities, connected, tab, task, change, close, onTask, onSession, onChanged, projects, select }: {
  cid: string; branch: string; activities: AgentActivityItem[]; connected: boolean; tab: WorkspaceTab; task: string
  change: (tab: WorkspaceTab) => void; close: () => void; onTask: (id: string) => void; onSession: (id: string) => void; onChanged: () => void
  projects: { id: string; name: string }[]; select: (cid: string, branch?: string, message?: string) => void
}) {
  const { t } = useI18n()
  const label = (key: WorkspaceTab, icon: ReactNode) => <span className="agent-workspace-tab">{icon}{t('agent.workspace.' + key)}</span>
  return <aside className="agent-workspace-rail" aria-label={t('agent.workspace.title')}>
    <header><div><BotIcon size={20} /><strong>{t('agent.workspace.title')}</strong></div><button type="button" className="tt-act" aria-label={t('agent.workspace.close')} onClick={close}><CloseIcon size={17} /></button></header>
    <p className="agent-workspace-connection" data-connected={connected}><span />{t(connected ? 'agent.workspace.connected' : 'agent.workspace.reconnecting')}</p>
    <Tabs activeKey={tab} onChange={key => change(key as WorkspaceTab)} destroyInactiveTabPane items={[
      { key: 'activity', label: label('activity', <TerminalIcon size={15} />), children: <AgentWorkspaceActivity items={activities} cid={cid} branch={branch} onSession={onSession} onTask={onTask} /> },
      { key: 'tasks', label: label('tasks', <ChecklistIcon size={15} />), children: <AgentTasks cid={cid} selectedTask={task} onSelectTask={onTask} onSession={onSession} onChanged={onChanged} /> },
      { key: 'reminders', label: label('reminders', <ClockIcon size={15} />), children: <AgentReminders select={select} /> },
      { key: 'memory', label: label('memory', <NotebookIcon size={15} />), children: <><p className="agent-muted agent-workspace-memory-note">{t('agent.workspace.memoryHint')}</p><AgentMemory cid={cid} defaultGroup="all" projects={projects} select={select} /></> },
    ]} />
  </aside>
}
