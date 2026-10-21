import type { AgentActivityItem } from './agent-protocol'

const settled = new Set(['succeeded', 'failed', 'cancelled', 'interrupted'])
export function mainTaskActivities(items: AgentActivityItem[]): AgentActivityItem[] {
  const tasks = new Map(items.filter(item => item.kind === 'task').map(item => [item.taskId, item]))
  return items.filter(item => {
    if (item.kind === 'turn') return true
    if (item.kind === 'tool') return item.state === 'unknown'
    if (!item.parentTaskId) return true
    const parent = tasks.get(item.parentTaskId)
    return (item.state === 'waiting_user' || item.state === 'unknown') && (!parent || !settled.has(parent.state) || item.state === 'unknown')
  })
}
