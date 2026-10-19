import type { ReactNode } from 'react'
import { Tabs } from 'antd'
import { BellIcon, ChecklistIcon, NotebookIcon, PanelRightIcon } from '../../icons'
import { useI18n } from '../../i18n'
import AgentTasks from './AgentTasks'
import AgentMemory from './AgentMemory'
import AgentInbox from './AgentInbox'
import type { AgentInboxState } from './useAgentInbox'
import type { WorkspaceTab } from './useAgentWorkspace'
import './agent-workspace.css'

export default function AgentWorkspaceRail({ cid, connected, actions, inbox, tab, task, change, close, onTask, onSession, onChanged, projects, select }: {
  cid: string; connected: boolean; tab: WorkspaceTab; task: string
  actions?: ReactNode; inbox: AgentInboxState
  change: (tab: WorkspaceTab) => void; close: () => void; onTask: (id: string) => void; onSession: (id: string) => void; onChanged: () => void
  projects: { id: string; name: string }[]; select: (cid: string, branch?: string, message?: string) => void
}) {
  const { t } = useI18n()
  const label = (key: WorkspaceTab, icon: ReactNode) => <span className="agent-workspace-tab">{icon}{t('agent.workspace.' + key)}</span>
  return <aside className="agent-workspace-rail" aria-label={t('agent.workspace.title')}>
    <Tabs activeKey={tab} onChange={key => change(key as WorkspaceTab)} tabBarExtraContent={{ right: <div className="agent-workspace-toolbar">
      <span className="agent-workspace-connection" data-connected={connected} role="img" aria-label={t(connected ? 'agent.workspace.connected' : 'agent.workspace.reconnecting')} title={t(connected ? 'agent.workspace.connected' : 'agent.workspace.reconnecting')} />
      {actions}
      <button type="button" className="tt-act" aria-label={t('agent.workspace.close')} title={t('agent.workspace.close')} onClick={close}><PanelRightIcon size={18} /></button>
    </div> }} destroyInactiveTabPane items={[
      { key: 'tasks', label: label('tasks', <ChecklistIcon size={15} />), children: <AgentTasks compact cid={cid} selectedTask={task} onSelectTask={onTask} onSession={onSession} onChanged={onChanged} /> },
      { key: 'messages', label: <>{label('messages', <BellIcon size={15} />)}{!!inbox.unread && <span className="agent-workspace-unread">{inbox.unread > 99 ? '99+' : inbox.unread}</span>}</>, children: <AgentInbox inbox={inbox} select={select} /> },
      { key: 'memory', label: label('memory', <NotebookIcon size={15} />), children: <AgentMemory compact cid={cid} defaultGroup="all" projects={projects} select={select} /> },
    ]} />
  </aside>
}
