// hash 路由的读写：整站只有这一处碰 location.hash 的格式。
// 工作区标签由后台维护；terms/active 只用于首次导入旧链接。


// 旧链接兼容：/#/env → /#/settings，/#/overview → /#/projects（概览并进项目页，18 设计）
export function normalizeRoute(raw: string): string {
  const route = raw.split('?')[0]
  if (route === 'capabilities/models/roles') return 'capabilities/agents/roami'
  if (route === 'settings/agent/runtime') {
    const tab = new URLSearchParams(raw.split('?')[1] || '').get('modelTab')
    return 'capabilities/models/' + (tab === 'proxy' ? 'usage' : tab === 'prices' ? 'prices' : 'catalog')
  }
  if (route === 'settings/common' || route === 'settings/ui/status') return 'settings/ui/look'
  if (route === 'settings/ui/keys/more') return 'settings/ui/keys'
  if (route === 'settings/agent/bin') return 'capabilities/agents'
  if (route.startsWith('settings/agent/bin/')) return 'capabilities/agents/' + route.slice('settings/agent/bin/'.length)
  if (route === 'plugins') return 'capabilities/plugins'
  if (route.startsWith('plugins/')) return 'capabilities/plugins/' + route.slice(8)
  if (/^settings\/agent\/(capabilities|skills|mcp|cli|tools)$/.test(route)) return 'capabilities/' + (route.split('/')[2] === 'capabilities' ? 'skills' : route.split('/')[2])
  if (route === 'env' || route.startsWith('env/')) return normalizeRoute('settings' + raw.slice(3))
  if (route === 'overview' || route.startsWith('overview/')) return 'projects'
  if (route === 'inbox') return 'projects'
  if (route === 'about') return 'settings/about'  // 关于页并进设置（18 设计：设置页收下版本与安装）
  if (route === 'me') return 'tools'
  return route
}

export function getHashParams(): URLSearchParams {
  const h = location.hash
  const qi = h.indexOf('?')
  return new URLSearchParams(qi >= 0 ? h.slice(qi + 1) : '')
}

export function setHashParams(params: Record<string, string>) {
  const h = location.hash
  const base = (h.split('?')[0]) || '#/home'
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) { if (v) sp.set(k, v) }
  const qs = sp.toString()
  const next = qs ? base + '?' + qs : base
  if (h !== next) history.replaceState(history.state, '', next)
}

/** 任务视图的页面名：#/w（22 设计 §7）。当前任务从当前标签推出来，URL 不写 */
export const TASK_ROUTE = 'w'

// 旧链接仅在后台尚未初始化时导入，不覆盖已有工作区。
export function readTermTokens(): { terms: string[]; active: string } {
  const p = getHashParams()
  const t = p.get('terms')
  const a = p.get('active')
  return {
    terms: t && t !== 'none' ? t.split(',').map(decodeURIComponent).filter(Boolean) : [],
    active: a ? decodeURIComponent(a) : '',
  }
}

