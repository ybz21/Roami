import { api } from '../../api'

export type AgentModelRole = { baseUrl: string; model: string; keyConfigured: boolean; images: boolean; contextWindow?: number | null; configuredContextWindow?: number | null }
export type AgentModelSettings = { main: AgentModelRole; worker: AgentModelRole; connection?: { baseUrl: string; keyConfigured: boolean } }
export const MODEL_SETTINGS_CHANGED = 'roami:agent-model-settings-changed'
export const agentSettingsRoute = '#/settings/agent/runtime'
export function modelFailure(error: any, t: (key: string) => string) {
  const code = error?.apiError?.code || error?.message
  return t(code === 'MODEL_CONFIGURATION_BUSY' ? 'agent.models.busy' : code === 'MODEL_KEY_REQUIRED_FOR_ENDPOINT' ? 'agent.models.newEndpointKey' : code === 'MODEL_ENDPOINT_REQUIRES_TLS' ? 'agent.models.httpsRequired' : 'agent.models.failed')
}
export async function saveAgentModels(patch: unknown) {
  const { data } = await api('PUT', '/agent/model-settings', patch)
  window.dispatchEvent(new Event(MODEL_SETTINGS_CHANGED))
  return data as AgentModelSettings
}

export function modelLabel(name: string): string {
  const characters = Array.from(name)
  return characters.length <= 16 ? name : characters.slice(0, 8).join('') + '…' + characters.slice(-7).join('')
}
