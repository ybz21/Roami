export const NAV = [
  { key: 'home', labelKey: 'nav.home' },
  { key: 'activity', labelKey: 'agent.overview' },
  { key: 'projects', labelKey: 'nav.projects' },
  { key: 'files', labelKey: 'nav.files' },
  { key: 'browser', labelKey: 'nav.browser' },
  { key: 'phone', labelKey: 'nav.phone' },
  { key: 'plugins', labelKey: 'nav.plugins' },
  { key: 'settings', labelKey: 'nav.env' },
  { key: 'sessions', labelKey: 'nav.sessions' }, // 兼容旧会话页路由；手机归入项目，桌面不列
  { key: 'tools', labelKey: 'nav.groupTools' },
]

export const NAV_WORKSPACE = ['home', 'projects', 'files']
export const NAV_TOOLS = ['browser', 'phone', 'plugins']
export const DESKTOP_PAGE_KEYS = new Set(['home', 'activity', 'projects', 'files', 'browser', 'phone', 'plugins', 'settings', 'sessions', 'swarm', 'hub'])
export const PAGE_TABS_KEY = 'roam.pageTabs'
export function loadPageTabs(): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(PAGE_TABS_KEY) || '[]')
    if (Array.isArray(saved)) return Array.from(new Set(saved.filter((key): key is string => typeof key === 'string' && DESKTOP_PAGE_KEYS.has(key))))
  } catch { /* 存储不可用时从当前页开始 */ }
  return []
}

export const MOBILE_NAV_KEYS = ['home', 'projects', 'tools', 'settings']

export const CQ_PAGES = new Set(['projects', 'sessions'])

export function mobileNavRoot(tab: string): string {
  if (tab === 'activity') return 'home'
  if (['sessions', 'swarm', 'w'].includes(tab)) return 'projects'
  if (['install', 'about'].includes(tab)) return 'settings'
  if (['files', 'browser', 'phone', 'plugins', 'hub'].includes(tab)) return 'tools'
  return tab
}
