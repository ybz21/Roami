import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import { agentName, isAgentKind, type AgentKind } from '../../agent-kind'
import { useCurrentNodeId, nodeApi } from '../cluster/node-url'
import { MODEL_SETTINGS_CHANGED, type AgentModelSettings } from '../agent/agent-models'
import { discoverAgents, type RegisteredAgent } from '../../agent-registry'
import { MODEL_CATALOG_CHANGED, type ModelCatalog } from '../capabilities/model-hub-api'
import { getPreferences, preferencesLoaded, usePreferences } from '../../preferences'

export const ONBOARDING_CHANGED = 'roami:onboarding-changed'
export const steps = ['model', 'agents', 'project', 'task'] as const
export type OnboardingStep = typeof steps[number]
export type OnboardingProgress = { started?: boolean; dismissed?: boolean; completed?: boolean; project?: string; session?: string }
export type OnboardingProject = { key: string; name: string; dir: string; git: boolean }
export type OnboardingSnapshot = { models: AgentModelSettings; agents: RegisteredAgent[]; projects: OnboardingProject[]; catalog: ModelCatalog }
const entries = new Map<string, { value?: OnboardingSnapshot; pending?: Promise<OnboardingSnapshot>; at: number }>()

export function onboardingChanged() { entries.clear(); window.dispatchEvent(new Event(ONBOARDING_CHANGED)) }
export function nextOnboardingStep(value: OnboardingSnapshot, progress: OnboardingProgress): OnboardingStep {
  if (!value.catalog.models.length) return 'model'
  if (!value.models.verified) return 'agents'
  if (!value.agents.some(agent => agent.installed && agent.verified)) return 'agents'
  if (!value.projects.length) return 'project'
  return 'task'
}
export function agentReadiness(agent: RegisteredAgent): 'ready' | 'pending' | 'missing' {
  return agent.installed && agent.verified ? 'ready' : agent.installed ? 'pending' : 'missing'
}
export function useOnboardingState(enabled = true) {
  const node = useCurrentNodeId(), [prefs, savePrefs] = usePreferences()
  const scope = nodeApi('/onboarding'), progressKey = node || 'local'
  const [state, setState] = useState<{ scope: string; value?: OnboardingSnapshot; failed: boolean }>({ scope: '', failed: false })
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => { entries.delete(scope); setRevision(value => value + 1) }, [scope])
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let entry = entries.get(scope)
    if (!entry || (!entry.pending && Date.now() - entry.at > 60_000)) { entry = { at: 0 }; entries.set(scope, entry) }
    const current = entry
    if (!current.pending) {
      const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 15_000)
      current.pending = (current.value ? Promise.resolve(current.value) : Promise.all([
        api('GET', '/agent/model-settings', undefined, { signal: abort.signal }).then(result => result.data), discoverAgents(abort.signal),
        api('GET', '/projects', undefined, { signal: abort.signal }).then(result => result.data.projects),
        api('GET', '/agent/model-gateway/catalog', undefined, { signal: abort.signal }).then(result => result.data),
      ]).then(([models, agents, projects, catalog]) => {
        if (!models?.main || !models?.worker || !Array.isArray(agents) || !Array.isArray(projects) || !Array.isArray(catalog?.models) || !Array.isArray(catalog?.sources)) throw new Error('INVALID_ONBOARDING_STATE')
        return { models, agents, projects, catalog }
      })).finally(() => clearTimeout(timeout))
    }
    void current.pending.then(value => {
      if (entries.get(scope) === current) { current.value = value; current.at = Date.now() }
      if (!cancelled) setState({ scope, value, failed: false })
    }).catch(() => { if (!cancelled) setState(previous => ({ scope, value: previous.scope === scope ? previous.value : undefined, failed: true })) })
      .finally(() => { current.pending = undefined })
    return () => { cancelled = true }
  }, [scope, revision, enabled])
  useEffect(() => {
    const changed = () => refresh()
    window.addEventListener(MODEL_CATALOG_CHANGED, changed)
    window.addEventListener(ONBOARDING_CHANGED, changed)
    window.addEventListener(MODEL_SETTINGS_CHANGED, changed)
    window.addEventListener('roam:agent-models-changed', changed)
    return () => { window.removeEventListener(MODEL_CATALOG_CHANGED, changed); window.removeEventListener(ONBOARDING_CHANGED, changed); window.removeEventListener(MODEL_SETTINGS_CHANGED, changed); window.removeEventListener('roam:agent-models-changed', changed) }
  }, [refresh])
  const value = state.scope === scope ? state.value : undefined
  const progress = prefs.onboarding?.[progressKey] || {}
  const change = async (patch: Partial<OnboardingProgress>) => {
    if (!preferencesLoaded()) return false
    const all = getPreferences().onboarding || {}
    return savePrefs({ onboarding: { ...all, [progressKey]: { ...all[progressKey], ...patch } } })
  }
  const configured = !!value?.models.main.model && !!(value.models.connection?.baseUrl || value?.models.main.baseUrl)
  const hasModels = !!value?.catalog.models.length
  const fresh = !!value && !configured && !value.catalog.sources.length && !value.projects.length
  const readyAgents = value?.agents.filter(agent => agent.installed && agent.verified && isAgentKind(agent.kind)).map(agent => ({ kind: agent.kind as AgentKind, name: agentName(agent.kind as AgentKind) })) || []
  return { value, progress, change, refresh, readyAgents, configured, hasModels, failed: state.scope === scope && state.failed, loading: !value && !(state.scope === scope && state.failed), visible: preferencesLoaded() && !!value && !progress.dismissed && !progress.completed && !!(fresh || progress.started) }
}
