import { getHashParams, normalizeRoute } from '../../route-hash'

export type AgentPageView = 'tasks' | 'memory' | 'notifications' | 'debug' | 'improvement'
export type AgentPageRoute = { view: AgentPageView; origin: string; task: string }
const views = new Set(['tasks', 'memory', 'notifications', 'debug', 'improvement'])
const FROM = 'roamiAgentPageFrom'

export function readAgentPage(route: string): AgentPageRoute | null {
  const parts = route.split('/')
  if (parts[0] !== 'home' || !views.has(parts[1]) || !parts[2] || parts.length > 4) return null
  try {
    const origin = decodeURIComponent(parts[2]), task = parts[3] ? decodeURIComponent(parts[3]) : ''
    if (!origin || origin.startsWith('/') || origin.includes('?') || origin.includes('#') || (task && !['tasks', 'debug'].includes(parts[1]))) return null
    for (const part of origin.split('/')) decodeURIComponent(part)
    return { view: parts[1] as AgentPageView, origin, task }
  } catch { return null }
}

export function agentPagePath(view: AgentPageView, origin: string, task = '') {
  return `home/${view}/${encodeURIComponent(origin)}${task ? '/' + encodeURIComponent(task) : ''}`
}

export function openAgentPage(view: AgentPageView, task = '') {
  const current = normalizeRoute(location.hash.replace(/^#\/?/, '') || 'home')
  const page = readAgentPage(current)
  const next = '#/' + agentPagePath(view, page?.origin || current, task)
  const params = getHashParams().toString(), target = next + (params ? '?' + params : '')
  const state = { ...history.state, [FROM]: location.hash }
  if (page?.task && page.view === view && (view === 'tasks' || view === 'debug')) {
    history.replaceState(history.state, '', target)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  } else {
    location.hash = target
    history.replaceState(state, '', target)
  }
}

export function backAgentPage(page: AgentPageRoute) {
  const parent = page.task ? agentPagePath(page.view, page.origin) : page.origin
  const previous = history.state?.[FROM]
  const previousRoute = typeof previous === 'string' ? normalizeRoute(previous.replace(/^#\/?/, '')) : ''
  const previousPage = readAgentPage(previousRoute)
  if (previousRoute === parent || (page.task && previousRoute === page.origin) || (previousPage?.origin === page.origin && previousPage.view !== page.view)) history.back()
  else {
    const params = getHashParams().toString()
    location.replace('#/' + parent + (params ? '?' + params : ''))
  }
}
