import { useCallback, useEffect, useMemo, useState } from 'react'
import { normalizeRoute, TASK_ROUTE } from '../route-hash'

import { DESKTOP_PAGE_KEYS, PAGE_TABS_KEY, loadPageTabs } from './navigation'
export function usePageTabs(route: string, terms: string[], go: (route: string) => void, nodeId: string | null = null) {
  const tab = route.split('/')[0]
  const routeKey = `${PAGE_TABS_KEY}.routes:${JSON.stringify(nodeId)}`
  const routes = useMemo(() => {
    const saved = new Map<string, string>()
    try {
      for (const [key, value] of Object.entries(JSON.parse(localStorage.getItem(routeKey) || '{}'))) {
        if (typeof value !== 'string') continue
        const path = normalizeRoute(value)
        if (DESKTOP_PAGE_KEYS.has(key) && path.split('/')[0] === key) saved.set(key, path)
      }
    } catch { /* 存储不可用时在当前会话内记住页面 */ }
    return saved
  }, [routeKey])
  const saveRoutes = useCallback(() => {
    try { localStorage.setItem(routeKey, JSON.stringify(Object.fromEntries(routes))) } catch { /* 保留内存中的页面 */ }
  }, [routeKey, routes])
  const [pageTabs, setPageTabs] = useState<string[]>(loadPageTabs)
  const [tabBarHost, setTabBarHost] = useState<HTMLDivElement | null>(null)
  useEffect(() => {
    if (DESKTOP_PAGE_KEYS.has(tab)) setPageTabs((list) => list.includes(tab) ? list : [...list, tab])
  }, [tab])
  useEffect(() => {
    if (!DESKTOP_PAGE_KEYS.has(tab)) return
    routes.set(tab, route)
    saveRoutes()
  }, [route, tab, routes, saveRoutes])
  useEffect(() => {
    try { localStorage.setItem(PAGE_TABS_KEY, JSON.stringify(pageTabs)) } catch { /* 可继续使用当前标签 */ }
  }, [pageTabs])
  const selectPage = (key: string) => go(routes.get(key) || key)
  const closePageTabs = (keys: string[]) => {
    const closing = new Set(keys)
    const at = pageTabs.findIndex((item) => closing.has(item))
    const next = pageTabs.filter((item) => !closing.has(item))
    if (!next.length && !terms.length) next.push('projects')
    setPageTabs(next)
    keys.forEach(key => routes.delete(key))
    saveRoutes()
    if (closing.has(tab)) {
      const target = next[at] || next[at - 1]
      selectPage(target || (terms.length ? TASK_ROUTE : 'projects'))
    }
  }
  const closePageTab = (key: string) => closePageTabs([key])
  return { pageTabs, tabBarHost, setTabBarHost, selectPage, closePageTab, closePageTabs }
}
