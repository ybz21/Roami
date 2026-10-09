import { api } from './api'

export type RegisteredAgent = {
  kind: string
  installed: boolean
  quota: {
    state: 'available' | 'unknown'
    remainingPercent?: number
    windowMinutes?: number
    resetsAt?: number
    observedAt?: string
    source?: string
    windows?: { remainingPercent: number; windowMinutes: number; resetsAt?: number }[]
  }
}

const pluginId = 'roam.agent-discovery'

export async function discoverAgents(): Promise<RegisteredAgent[]> {
  const result = await api('POST', `/plugins/${pluginId}/run`, { command: 'agent-discovery.scan', args: {} })
  return result?.agents || []
}

export async function installAgent(kind: string): Promise<void> {
  await api('POST', `/plugins/${pluginId}/run`, { command: 'agent-discovery.install', args: { kind } })
}
