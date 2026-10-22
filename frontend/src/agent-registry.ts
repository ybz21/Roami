import { api } from './api'

export type RegisteredAgent = {
  kind: string
  installed: boolean
  binary?: string
  version?: string
  versionState?: 'available' | 'unavailable'
  authentication?: 'unknown' | 'required' | 'expired'
  canUpgrade?: boolean
  upgradeMethod?: 'native' | 'npm'
  modelPreset?: string
  quota: {
    state: 'available' | 'unknown'
    reason?: 'provider_managed' | 'login_required' | 'login_expired' | 'no_snapshot' | 'request_failed' | 'rate_limited'
    remainingPercent?: number
    windowMinutes?: number
    resetsAt?: number
    observedAt?: string
    source?: string
    windows?: { remainingPercent: number; windowMinutes: number; resetsAt?: number }[]
  }
}

export async function discoverAgents(signal?: AbortSignal): Promise<RegisteredAgent[]> {
  const result = await api('GET', '/agent/professional', undefined, { signal })
  return result?.agents || []
}

export async function installAgent(kind: string): Promise<void> {
  await api('POST', `/agent/professional/${encodeURIComponent(kind)}/install`)
}

export async function checkAgent(kind: string): Promise<RegisteredAgent> {
  const result = await api('POST', `/agent/professional/${encodeURIComponent(kind)}/check`)
  return result.agent
}

export async function upgradeAgent(kind: string): Promise<RegisteredAgent> {
  const result = await api('POST', `/agent/professional/${encodeURIComponent(kind)}/upgrade`)
  return result.agent
}

export type AgentModelProfile = {
  id: string
  name: string
  baseUrl: string
  model: string
  protocol: string
  authMode: string
  keyEnv?: string
  reasoningEffort?: string
  hasKey: boolean
  applied: boolean
}

export type AgentModelInput = Omit<AgentModelProfile, 'id' | 'hasKey' | 'applied'> & { apiKey?: string }
export type AgentModelView = {
  profiles: AgentModelProfile[]
  current: { provider?: string; model?: string }
  revision: string
  activeId?: string
  changed: boolean
  canRestore: boolean
  configPaths: string[]
  opencodeMajor?: number
}

const modelPath = (kind: string) => `/agent/professional/${encodeURIComponent(kind)}/models`

export async function agentModels(kind: string, signal?: AbortSignal): Promise<AgentModelView> {
  return api('GET', modelPath(kind), undefined, { signal })
}

export async function saveAgentModel(kind: string, id: string | undefined, input: AgentModelInput): Promise<AgentModelProfile> {
  const result = await api(id ? 'PUT' : 'POST', modelPath(kind) + (id ? '/' + encodeURIComponent(id) : ''), input)
  return result.profile
}

export async function deleteAgentModel(kind: string, id: string): Promise<void> {
  await api('DELETE', modelPath(kind) + '/' + encodeURIComponent(id))
}

export async function applyAgentModel(kind: string, id: string, revision: string): Promise<AgentModelView> {
  return api('POST', modelPath(kind) + '/' + encodeURIComponent(id) + '/apply', { revision })
}

export async function restoreAgentModel(kind: string, revision: string): Promise<AgentModelView> {
  return api('POST', modelPath(kind) + '/restore', { revision })
}
