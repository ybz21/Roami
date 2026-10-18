import type { AgentActivityItem, AgentMessage } from './agent-protocol'

export type AgentTimelineEntry = { id: string; message: AgentMessage; activity?: never } | { id: string; activity: AgentActivityItem; message?: never }

export function agentTimeline(messages: AgentMessage[], activities: AgentActivityItem[]): AgentTimelineEntry[] {
  const positions = new Map(messages.map((message, index) => [message.id, index * 2]))
  const timed = messages.every(message => message.created_ms !== undefined)
  const entries = [
    ...messages.filter(m => m.content.text || m.content.question || m.content.taskStatus || m.content.attachments?.length || m.status === 'streaming').map(message => ({ id: message.id, message, time: message.created_ms, position: positions.get(message.id)! })),
    ...activities.map(activity => ({ id: activity.id, activity, time: activity.startedMs, position: (positions.get(activity.anchorMessageId) ?? messages.length * 2) + 1 })),
  ]
  return entries.sort((a, b) => timed && a.time !== undefined && b.time !== undefined && a.time !== b.time ? a.time - b.time : a.position - b.position || a.id.localeCompare(b.id))
}
