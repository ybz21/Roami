import type { AgentActivityItem } from './agent-protocol'

export function mainTaskActivities(items: AgentActivityItem[]): AgentActivityItem[] {
  return [
    ...items.filter(item => item.kind !== 'tool').slice(-200),
    ...items.filter(item => item.kind === 'tool').slice(-200),
  ].sort((a, b) => a.startedMs - b.startedMs || a.id.localeCompare(b.id))
}

export function groupExecutionSteps(items: AgentActivityItem[]): AgentActivityItem[][] {
  const groups: AgentActivityItem[][] = []
  for (const item of items) {
    const previous = groups[groups.length - 1]
    if (previous && (previous[0].kind === 'tool') === (item.kind === 'tool')) previous.push(item)
    else groups.push([item])
  }
  return groups
}
