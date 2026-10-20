import { useCallback, useEffect, useState } from 'react'
import { readAgentPage } from '../components/agent/agent-page-route'
import { getHashParams, normalizeRoute } from '../route-hash'

export function useAppRoute() {
  const [route, setRoute] = useState(() => normalizeRoute(location.hash.replace(/^#\/?/, '') || 'home'))
  const agentPage = readAgentPage(route)
  const agentParts = (agentPage?.origin || route).split('/')
  const agentCID = agentParts[0] === 'home' && agentParts[1] && agentParts[1] !== 'new' ? decodeURIComponent(agentParts[1]) : ''
  const agentBranch = agentParts[0] === 'home' && agentParts[2] ? decodeURIComponent(agentParts[2]) : ''
  const agentMessage = agentParts[0] === 'home' && agentParts[3] ? decodeURIComponent(agentParts[3]) : ''
  const tab = route.split('/')[0]                                  // 基础页（swarm/leave → swarm）
  const swarmSub = tab === 'swarm' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : '' // 深链选中的蜂群
  const projectSub = tab === 'projects' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : '' // 深链选中的项目
  const pluginSub = tab === 'capabilities' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : '' // 深链选中的插件（状态条点进来）
  const inboxSub = tab === 'inbox' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : '' // 从推送通知点进来要开的会话
  const settingsSub = tab === 'settings' && route.includes('/') ? route.slice(route.indexOf('/') + 1) : '' // 设置的哪一类（node/browser）
  const go = (k: string) => {
    const qi = location.hash.indexOf('?')
    const qs = qi >= 0 ? location.hash.slice(qi) : ''
    location.hash = '#/' + k + qs
  }
  const selectAgent = useCallback((cid: string, branch?: string, message?: string) => {
    const params = getHashParams().toString()
    const next = 'home/' + (cid ? encodeURIComponent(cid) + (branch ? '/' + encodeURIComponent(branch) + (message ? '/' + encodeURIComponent(message) : '') : '') : 'new')
    setRoute(next)
    location.hash = '#/' + next + (params ? '?' + params : '')
  }, [])
  useEffect(() => {
    const apply = () => setRoute(normalizeRoute(location.hash.replace(/^#\/?/, '') || 'home'))
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])

  const soloName = tab === 'term' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : ''
  return { route, setRoute, tab, go, selectAgent, agentPage, agentParts, agentCID, agentBranch, agentMessage, swarmSub, projectSub, pluginSub, inboxSub, settingsSub, soloName }
}
export type AppRoute = ReturnType<typeof useAppRoute>
