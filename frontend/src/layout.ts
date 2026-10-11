// 全站唯一的断点入口（13 设计 §3.2）。
//
// 在这之前，"端"的判定散在六个文件里：五处 `!screens.md`(768)、GitPanel 的
// `innerWidth >= 900`、Swarm 直接拿 innerWidth 算抽屉宽、index.css 里一条
// `max-width: 760px`——改一个断点要翻六个地方，且互相不一致。
//
// 现在只有一处：`useLayout()` 返回档位与环境，同时把结果写到 <html> 的
// data-* 上，纯样式适配走 CSS，不必再往组件里塞 JS 分支。
//
// 判定用 matchMedia 而不是 window.innerWidth：旋转和软键盘弹起时 innerWidth
// 会短暂给出中间值，媒体查询不会。软键盘高度单独用 visualViewport 量（§8.2）。
import { useSyncExternalStore } from 'react'

/** 四档窗口尺寸，对齐 Material 3 window size class（13 §3.1）。 */
export type WindowSize = 'compact' | 'medium' | 'expanded' | 'large'

export type LayoutState = {
  size: WindowSize
  /** compact | medium —— 取代今天所有的 `!screens.md` */
  phone: boolean
  /** expanded | large */
  desktop: boolean
  /** 手机横屏：高 < 480 且横向。是姿态不是宽度 */
  landscape: boolean
  /** 粗指针（手指）。命中区看它，不看宽度 */
  coarse: boolean
  /** 软键盘高度 px，0 = 收起 */
  keyboard: number
}

/** 档位下界，与 13 §3.1 的表一一对应。 */
export const BREAKPOINTS = { medium: 600, expanded: 905, large: 1280 } as const

/** 桌面常驻分栏的下界；低于此值终端不并排（14 §4.2 / 13 §13.1）。 */
export const SPLIT_MIN_WIDTH = BREAKPOINTS.large

const QUERIES = {
  medium: `(min-width: ${BREAKPOINTS.medium}px)`,
  expanded: `(min-width: ${BREAKPOINTS.expanded}px)`,
  large: `(min-width: ${BREAKPOINTS.large}px)`,
  landscape: '(max-height: 480px) and (orientation: landscape)',
  coarse: '(pointer: coarse)',
} as const

function matches(query: string): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia(query).matches
}

function currentSize(): WindowSize {
  if (matches(QUERIES.large)) return 'large'
  if (matches(QUERIES.expanded)) return 'expanded'
  if (matches(QUERIES.medium)) return 'medium'
  return 'compact'
}

/**
 * 软键盘高度。Android App 用系统 IME Insets；浏览器用 VirtualKeyboard API
 * 或 visualViewport。取最大值，避免输入区被键盘盖住。
 */
function currentKeyboard(): number {
  if (typeof window === 'undefined') return 0
  const byNative = (window as Window & { __roamiNativeKeyboardHeight?: number }).__roamiNativeKeyboardHeight || 0
  let byApi = 0
  try {
    const rect = (navigator as any).virtualKeyboard?.boundingRect
    if (rect && rect.height > 0) byApi = rect.height
  } catch { /* 不支持就算了 */ }
  const vv = window.visualViewport
  const byVv = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0
  // 30px 以下多半是地址栏收放造成的抖动，不当成键盘
  const kb = Math.max(byNative, byApi, byVv)
  return kb > 30 ? Math.round(kb) : 0
}

function read(): LayoutState {
  const size = currentSize()
  return {
    size,
    phone: size === 'compact' || size === 'medium',
    desktop: size === 'expanded' || size === 'large',
    landscape: matches(QUERIES.landscape),
    coarse: matches(QUERIES.coarse),
    keyboard: currentKeyboard(),
  }
}

let state: LayoutState = read()
const listeners = new Set<() => void>()

function same(a: LayoutState, b: LayoutState): boolean {
  return a.size === b.size && a.landscape === b.landscape
    && a.coarse === b.coarse && a.keyboard === b.keyboard
}

function publish() {
  const next = read()
  if (same(state, next)) return
  state = next
  applyDom(state)
  listeners.forEach((fn) => fn())
}

/**
 * 把档位写到 <html> 上，CSS 侧靠 `html[data-size="compact"] .x {}` 适配，
 * 不必为纯样式差异往组件里加 JS 分支。`--kb` 供所有浮层统一吃：
 * `padding-bottom: max(var(--kb), var(--safe-b))`。
 */
function applyDom(s: LayoutState) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.size = s.size
  root.dataset.orient = s.landscape ? 'landscape' : 'portrait'
  root.dataset.pointer = s.coarse ? 'coarse' : 'fine'
  root.dataset.keyboard = s.keyboard > 0 ? 'open' : 'closed'
  root.style.setProperty('--kb', `${s.keyboard}px`)
}

let started = false
function start() {
  if (started || typeof window === 'undefined') return
  started = true
  applyDom(state)
  for (const q of Object.values(QUERIES)) {
    const mql = window.matchMedia(q)
    // Safari < 14 只有 addListener；两者都没有就跳过（测试桩、老 WebView）
    if (mql.addEventListener) mql.addEventListener('change', publish)
    else if (typeof mql.addListener === 'function') mql.addListener(publish)
  }
  window.addEventListener('resize', publish)
  window.addEventListener('orientationchange', publish)
  window.addEventListener('roami-keyboard', publish)
  // VirtualKeyboard API 自己的事件。少了它，--kb 只能靠 resize/visualViewport 顺带刷新——
  // 真机上抓到过 `env(keyboard-inset-height)` 已经是 314、而 --kb 还停在 0 的状态：
  // 布局按 314 让了位，吃 --kb 的浮层（sheet、会话坞）却以为键盘没弹。
  try {
    (navigator as any).virtualKeyboard?.addEventListener?.('geometrychange', publish)
  } catch { /* 不支持就靠上面两条兜底 */ }
  const vv = window.visualViewport
  vv?.addEventListener('resize', publish)
  vv?.addEventListener('scroll', publish)
}

function subscribe(fn: () => void): () => void {
  start()
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/** 全站唯一断点入口。组件里不要再读 window.innerWidth 或自己 matchMedia。 */
export function useLayout(): LayoutState {
  return useSyncExternalStore(subscribe, () => state, () => state)
}

/** 非组件环境（事件回调、模块初始化）读当前档位。 */
export function getLayout(): LayoutState {
  start()
  return state
}

/**
 * 密度是用户偏好，与档位（环境事实）正交，所以是另一个属性（13 §13.4）。
 * `data-size="compact"`（窗口窄）和 `data-density="compact"`（信息密）同名不同义，
 * 合并会在 CSS 里撞车。
 */
export type Density = 'cozy' | 'compact'

export function applyDensity(density: Density) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.density = density
}
