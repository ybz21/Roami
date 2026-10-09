// hash 路由的读写：整站只有这一处碰 location.hash 的格式。
// 终端标签（terms/active）也挂在 hash 的 query 上——刷新后要还原开着的会话。


// 旧链接兼容：/#/env → /#/settings，/#/overview → /#/projects（概览并进项目页，18 设计）
export function normalizeRoute(raw: string): string {
  const route = raw.split('?')[0]
  if (route === 'env' || route.startsWith('env/')) return 'settings' + route.slice(3)
  if (route === 'overview' || route.startsWith('overview/')) return 'projects'
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
  const base = (h.split('?')[0]) || '#/projects'
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) { if (v) sp.set(k, v) }
  const qs = sp.toString()
  const next = qs ? base + '?' + qs : base
  if (h !== next) history.replaceState(history.state, '', next)
}

export const NO_TERMS = 'none'

/** 任务视图的页面名：#/w（22 设计 §7）。当前任务从当前标签推出来，URL 不写 */
export const TASK_ROUTE = 'w'

// URL 上的终端标签参数（terms=打开的标签、active=当前标签）。
// 现在写进去的是会话 id；老链接里存的是会话名，两者都能读——还原时按 id 表判别（见 resolveToken）。
//
// terms 有三态，别把后两个当成一回事：**没写** = 这条链接对标签没意见，回落到本机记的那份；
// **terms=none** = 明说「这页不要标签」（「在新页面打开」开出来的镜像页就带这个）；
// 有值 = 就开这几个。少了 none 这一态，新开的页会把上一次的会话全部拽过来。
export function readTermTokens(): { terms: string[]; active: string; none: boolean } {
  const p = getHashParams()
  const t = p.get('terms')
  const a = p.get('active')
  return {
    terms: t && t !== NO_TERMS ? t.split(',').map(decodeURIComponent).filter(Boolean) : [],
    active: a ? decodeURIComponent(a) : '',
    none: t === NO_TERMS,
  }
}

