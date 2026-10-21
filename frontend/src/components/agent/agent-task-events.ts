import { agentDataKey, invalidateAgentData } from './agent-data-cache'
import type { AgentEvent } from './agent-protocol'

const listeners = new Map<string, Set<() => void>>()
export function subscribeTaskChanges(id: string, listener: () => void) {
  const key = agentDataKey('/agent/tasks/' + encodeURIComponent(id))
  const group = listeners.get(key) || new Set()
  group.add(listener); listeners.set(key, group)
  return () => { group.delete(listener); if (!group.size) listeners.delete(key) }
}
export function publishTaskEvent(event: AgentEvent) {
  if (!event.kind.startsWith('task.') || event.payload.toolName || event.payload.activity?.kind === 'tool') return
  const ids = new Set([event.payload.taskId, event.payload.activity?.taskId, event.payload.activity?.parentTaskId].filter(Boolean))
  for (const id of ids) {
    const path = '/agent/tasks/' + encodeURIComponent(id), key = agentDataKey(path)
    for (const entry of [path, path + '/resources', '/agent/artifacts?taskId=' + encodeURIComponent(id)]) invalidateAgentData(agentDataKey(entry))
    for (const listener of listeners.get(key) || []) listener()
  }
}
