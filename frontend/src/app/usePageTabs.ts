import { useEffect, useState } from 'react'
import { TASK_ROUTE } from '../route-hash'

import { DESKTOP_PAGE_KEYS, PAGE_TABS_KEY, loadPageTabs } from './navigation'
export function usePageTabs(tab: string, terms: string[], go: (route: string) => void) {
  const [pageTabs, setPageTabs] = useState<string[]>(loadPageTabs)
  const [tabBarHost, setTabBarHost] = useState<HTMLDivElement | null>(null)
  useEffect(() => {
    if (DESKTOP_PAGE_KEYS.has(tab)) setPageTabs((list) => list.includes(tab) ? list : [...list, tab])
  }, [tab])
  useEffect(() => {
    try { localStorage.setItem(PAGE_TABS_KEY, JSON.stringify(pageTabs)) } catch { /* 可继续使用当前标签 */ }
  }, [pageTabs])
  const closePageTabs = (keys: string[]) => {
    const closing = new Set(keys)
    const at = pageTabs.findIndex((item) => closing.has(item))
    const next = pageTabs.filter((item) => !closing.has(item))
    if (!next.length && !terms.length) next.push('projects')
    setPageTabs(next)
    if (closing.has(tab)) {
      const target = next[at] || next[at - 1]
      go(target || (terms.length ? TASK_ROUTE : 'projects'))
    }
  }
  const closePageTab = (key: string) => closePageTabs([key])
  return { pageTabs, tabBarHost, setTabBarHost, closePageTab, closePageTabs }
}
