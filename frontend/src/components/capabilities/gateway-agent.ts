import { useMemo } from 'react'
import { useRegisteredAgents } from '../../agent-registry'

export function useGatewayAgentNames(enabled = true): Record<string, string> {
  const agents = useRegisteredAgents(enabled)
  return useMemo(() => ({ ...Object.fromEntries(agents.map(agent => [agent.kind, agent.displayName])), roami: 'Roami' }), [agents])
}
