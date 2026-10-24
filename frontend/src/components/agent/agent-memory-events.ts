import { agentDataKey, invalidateAgentDataPrefix } from './agent-data-cache'
import type { AgentEvent } from './agent-protocol'

const listeners = new Map<string, Set<() => void>>()
export const memoryEventScope = () => agentDataKey('/agent/memories')
export function subscribeMemoryChanges(listener: () => void) {
  const scope = memoryEventScope(), group = listeners.get(scope) || new Set()
  group.add(listener); listeners.set(scope, group)
  return () => { group.delete(listener); if (!group.size) listeners.delete(scope) }
}
export function publishMemoryChanges(scope = memoryEventScope()) {
  invalidateAgentDataPrefix(scope)
  for (const listener of listeners.get(scope) || []) listener()
}
export function publishMemoryEvent(event: AgentEvent) {
  if (event.kind.startsWith('memory.')) publishMemoryChanges()
}
