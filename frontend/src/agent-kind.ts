import { agentDefinition } from './agent-registry'
import { createSessionPoll } from './session-poll'

// Kinds are registered by the host; this layer validates wire identifiers only.
export type AgentKind = string
export const isAgentKind = (value: unknown): value is AgentKind =>
  typeof value === 'string' && /^[a-z][a-z0-9-]{0,63}$/.test(value) && !['native', 'roami', 'none', 'shell', 'terminal', 'auto', 'unknown', 'cli', 'roami-cli'].includes(value)

const names: Record<string, string> = { native: 'Roami', claude: 'Claude', codex: 'Codex', opencode: 'OpenCode', pi: 'Pi' }
export const agentName = (kind: string): string => names[kind] || agentDefinition(kind)?.displayName || kind
export const hasRenderedChat = (kind: string): boolean => ['claude', 'codex', 'opencode', 'pi'].includes(kind)

const useKinds = createSessionPoll<Record<string, AgentKind>>('/sessions/agents', 6000, {}, response =>
  Object.fromEntries(Object.entries(response?.data || {}).filter(([, kind]) => isAgentKind(kind))) as Record<string, AgentKind>)

export function useAgentKinds(enabled = true): Record<string, AgentKind> {
  return useKinds(enabled).value
}
