import { api } from './api'

export type RegisteredAgent = {
  kind: string
  installed: boolean
  binary?: string
  version?: string
  versionState?: 'available' | 'unavailable'
  authentication?: 'unknown' | 'required' | 'expired'
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
