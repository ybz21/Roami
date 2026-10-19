import type { AgentModelRole } from './agent-models'

export const genericReasoningEfforts = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
export function reasoningChoices(role?: AgentModelRole) {
  return ['default', ...(role?.reasoningEfforts || genericReasoningEfforts)]
}
export function reasoningValue(effort?: string | null) { return effort || 'default' }
