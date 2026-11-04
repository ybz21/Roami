import type { AgentModelRole } from './agent-models'

const levels = ['low', 'medium', 'high']
export function reasoningKnown(role?: AgentModelRole) { return role?.reasoningSupport === 'supported' }
export function reasoningChoices(role?: AgentModelRole) {
  return ['default', ...levels.filter(value => reasoningKnown(role) && role?.reasoningEfforts?.includes(value))]
}
export function reasoningValue(effort?: string | null) { return effort || 'default' }
export function reasoningLabel(effort?: string | null) {
  const value = reasoningValue(effort)
  return 'agent.reasoning.' + (value === 'default' || levels.includes(value) ? value : 'custom')
}
export function reasoningCustom(effort?: string | null) { return reasoningLabel(effort) === 'agent.reasoning.custom' }
export function reasoningRawChoices(role?: AgentModelRole) {
  return [...new Set(['default', ...(reasoningKnown(role) ? role?.reasoningEfforts || [] : []), ...(role?.reasoningEffort ? [role.reasoningEffort] : [])])]
}
