import { createSessionPoll } from './session-poll'

export type AgentKind = 'claude' | 'codex' | 'opencode' | 'pi'

export const isAgentKind = (value: unknown): value is AgentKind =>
  value === 'claude' || value === 'codex' || value === 'opencode' || value === 'pi'

export const agentName = (kind: AgentKind): string =>
  ({ claude: 'Claude', codex: 'Codex', opencode: 'OpenCode', pi: 'Pi' })[kind]

const useKinds = createSessionPoll<Record<string, AgentKind>>('/sessions/agents', 6000, {}, response =>
  Object.fromEntries(Object.entries(response?.data || {}).filter(([, kind]) => isAgentKind(kind))) as Record<string, AgentKind>)

export function useAgentKinds(enabled = true): Record<string, AgentKind> {
  return useKinds(enabled).value
}
