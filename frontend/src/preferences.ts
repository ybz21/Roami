import { useSyncExternalStore } from 'react'
import { api } from './api'

export interface Preferences {
  theme: 'dark' | 'light'
  claudeThemeSync: boolean // 切 Roami 主题时把 Claude Code 的主题（~/.claude/settings.json）一起切，服务端做
  locale: string
  browserQuality: string
  browserDevice: string
  browserRotate: string
  promptPopupOff: boolean
  recentDirs: string[]
  claudeCommand: string
  codexCommand: string
  quickCommands: string[]
  showVoiceButton: boolean
  keybindings: Partial<Record<string, string>> // 快捷键覆盖：动作 → 'Mod+Shift+KeyS' 这种串，默认表在 shell/keybindings.ts
  overviewTab: 'projects' | 'sessions' // 概览页 项目/会话 切换 tab，记住上次选择
  p2pEnabled: boolean // P2P 直连总开关（实验性，默认关）；关闭后 下载/镜像等一律走 frp 中转
  p2pStunServers: string // 逗号分隔的 STUN 服务器；留空用服务端默认（/api/p2p/config）。仅影响本浏览器
  p2pConnectTimeoutSec: number // 打洞建链超时（秒），超时回退 frp。默认 30
  p2pGatherTimeoutSec: number // ICE 候选收集上限（秒）：等 srflx 等这么久，慢网(手机蜂窝)可调大。默认 30
  p2pMinSpeedKBps: number // P2P 直连测速回退阈值(KB/s)：平均落盘速率长期低于此值就回退 frp；0=禁用，永远坚持 P2P。默认 200
  workspace: WorkspacePreference // 工作区外壳偏好（13/14 设计共用一份，见下）
  statusBar: StatusBarPreference // 底部状态条（20 设计）
  taskNames: Record<string, string> // 任务（worktree 路径）→ 人起的显示名；没起就用第一个会话的名字
  _migrated: boolean
}

/**
 * 底部状态条偏好（20 设计 §05/§13）。
 *
 * `hidden` 收全局格 id 或 provider id；`optIn` 是**第三方插件**的白名单——
 * 装了插件不等于同意它上你的状态条，所以第三方默认关，要在设置里打开。
 * 系统格与随二进制分发的 builtin 插件（如主机监控）默认就在，不需要进 optIn。
 */
export interface StatusBarPreference {
  enabled: boolean
  hidden: string[]
  optIn: string[]
}

/**
 * 工作区外壳偏好（14 §9.3 + 13 §9）。**四档共用一份，不按端各存一套**——
 * 但恢复时按当前档钳制：手机记的方向簇左手位不该影响桌面，桌面记的 Dock 宽度
 * 也不该被手机读出来当布局用。
 */
export interface WorkspacePreference {
  navCollapsed: boolean // 桌面侧栏收成 64px 轨
  dockOpen: boolean // 终端区是否展开
  inspectorWidth: number // Git/Worktree 列宽 px；同样按当前几何钳制
  inspectorCollapsed: boolean // 右栏收起（只剩把手）。第一次进来是收着的，见 WORKSPACE_DEFAULTS
  workspaceFocus: 'none' | 'page' | 'dock' // 单区聚焦
  density: 'cozy' | 'compact' // 信息密度，与窗口档正交
  dpadOn: boolean // 手机方向簇
  dpadSide: 'left' | 'right' // 方向簇落在哪只手
  dpadHintSeen: boolean // 方向簇的一次性说明看过没
}

const WORKSPACE_DEFAULTS: WorkspacePreference = {
  // 默认成轨（VSCode 的活动栏本来就不带文字标签，名字在 tooltip 里）。
  // 两个实在理由：① 展开态只在 large(≥1280) 存在，1280 以下强制成轨——默认展开的结果是
  // 拖窗口跨过 1280 导航自己换一副样子；默认成轨，桌面各档同一个形状。
  // ② 那 160px 在 1280 上是决定性的：展开时终端最宽 488，比它的下限 480 只多 8，等于顶死；
  // 收成轨是 648。已经存过偏好的浏览器不受影响，这只是没拖过时给什么。
  navCollapsed: true,
  dockOpen: true,
  inspectorWidth: 0, // 0 = 还没拖过，用 INSPECTOR_DEFAULT
  // 第一次进来右栏是收着的：新用户开门看见的应该是「会话在哪、终端在哪」，
  // 而不是一列 Git/文件面板占掉三分之一屏——那一列是查东西时才叫出来的。
  // 自己拉开过就记住，下次照旧开着。
  inspectorCollapsed: true,
  workspaceFocus: 'none',
  density: 'cozy',
  dpadOn: true,
  dpadSide: 'right',
  dpadHintSeen: false,
}

const STATUSBAR_DEFAULTS: StatusBarPreference = { enabled: true, hidden: [], optIn: [] }

const DEFAULTS: Preferences = {
  theme: 'dark',
  claudeThemeSync: true,
  locale: 'zh-CN',
  browserQuality: 'auto',
  browserDevice: '',
  browserRotate: '0',
  promptPopupOff: false,
  recentDirs: [],
  claudeCommand: 'claude',
  codexCommand: 'codex',
  quickCommands: [],
  showVoiceButton: true,
  keybindings: {},
  overviewTab: 'projects',
  p2pEnabled: false, // 实验性：待真实跨网/Android/iOS 验收后再默认开
  p2pStunServers: '',
  p2pConnectTimeoutSec: 30,
  p2pGatherTimeoutSec: 30,
  p2pMinSpeedKBps: 200,
  workspace: WORKSPACE_DEFAULTS,
  statusBar: STATUSBAR_DEFAULTS,
  taskNames: {},
  _migrated: false,
}

/**
 * 工作区尺寸的**首帧镜像**。
 *
 * 偏好的权威在服务端，而那是一次异步 GET：首帧手里只有 DEFAULTS，分隔条先按
 * 42vw 画一次，偏好回来再跳到用户拖出来的宽度——每刷新一次，分隔条当着面挪一次。
 * 这里在本地留一份同样的值，首帧就拿它开画；服务端回来仍然是权威，值一致时
 * 肉眼什么都看不到（只有换了台设备才会有一次修正）。尺寸本来也是最该按浏览器
 * 记的东西：手机和桌面读的是同一份偏好，但画出来的从来不是同一个布局。
 */
const WORKSPACE_MIRROR = 'ttmux.workspace'

/**
 * 观感项的**本地权威**：主题与语言。
 *
 * 偏好存在服务端，多机之后就成了「主题跟着机器走」：从开发机切到 Jetson，
 * 读的是那台机器上的值，界面当着面换一副样子——而这两项是「我习惯这样」，
 * 跟人不跟机器。尺寸类偏好早就按浏览器镜像了一份（WORKSPACE_MIRROR，见上），
 * 这里沿用同一条路：**本地有值就以本地为准**，服务端那份退化成备份与首次默认。
 *
 * 只覆盖纯观感项。命令、密钥、传输参数仍以服务端为权威——那些是机器的事实，
 * 不是口味。
 */
const LOOK_MIRROR = 'ttmux.look'

type LookMirror = { theme?: Preferences['theme']; locale?: string }

function readLookMirror(): LookMirror {
  try {
    const raw = localStorage.getItem(LOOK_MIRROR)
    const v = raw ? JSON.parse(raw) : null
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  } catch { return {} }
}

function writeLookMirror(p: Preferences) {
  try { localStorage.setItem(LOOK_MIRROR, JSON.stringify({ theme: p.theme, locale: p.locale })) } catch {}
}

function readWorkspaceMirror(): Partial<WorkspacePreference> {
  try {
    const raw = localStorage.getItem(WORKSPACE_MIRROR)
    const v = raw ? JSON.parse(raw) : null
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  } catch { return {} }
}

function writeWorkspaceMirror(ws: WorkspacePreference) {
  try { localStorage.setItem(WORKSPACE_MIRROR, JSON.stringify(ws)) } catch {}
}

let cache: Preferences = { ...DEFAULTS, ...readLookMirror(), workspace: { ...WORKSPACE_DEFAULTS, ...readWorkspaceMirror() } }
let listeners = new Set<() => void>()
let loaded = false

function notify() {
  listeners.forEach((l) => l())
}

function migrateFromLocalStorage() {
  try {
    const theme = localStorage.getItem('ttmux-theme')
    if (theme === 'dark' || theme === 'light') cache.theme = theme

    const locale = localStorage.getItem('ttmux-locale')
    if (locale) {
      const lower = locale.toLowerCase()
      if (lower === 'zh-cn' || lower === 'zh') cache.locale = 'zh-CN'
      else if (lower === 'en-us' || lower.startsWith('en')) cache.locale = 'en-US'
    }

    const quality = localStorage.getItem('ttmux.browser.quality')
    if (quality) cache.browserQuality = quality

    const device = localStorage.getItem('ttmux.browser.device')
    if (device !== null) cache.browserDevice = device

    const rotate = localStorage.getItem('ttmux.browser.rotate')
    if (rotate) cache.browserRotate = rotate

    try {
      const dirs = JSON.parse(localStorage.getItem('ttmux_recent_dirs') || '[]')
      if (Array.isArray(dirs)) cache.recentDirs = dirs.slice(0, 8)
    } catch {}
  } catch {}

  cache._migrated = true
  api('PUT', '/preferences', cache).catch(() => {})
}

export async function loadPreferences() {
  try {
    const r = await api('GET', '/preferences')
    // workspace 是嵌套对象：整体展开会让服务端存的旧结构缺字段变 undefined，单独深合一层
    // 本地存过的观感项压在服务端之上：这一条是「跟着我走」与「这台机器」的分界线
    cache = { ...DEFAULTS, ...r?.data, ...readLookMirror(), workspace: { ...WORKSPACE_DEFAULTS, ...r?.data?.workspace } }
    writeWorkspaceMirror(cache.workspace)
    if (!cache._migrated) {
      migrateFromLocalStorage()
    }
    loaded = true
    notify()
  } catch {
    // server unreachable: keep defaults, localStorage still works as fallback
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null

export function savePreferences(partial: Partial<Preferences>) {
  cache = { ...cache, ...partial }
  if (partial.workspace) writeWorkspaceMirror(cache.workspace)
  if (partial.theme !== undefined || partial.locale !== undefined) writeLookMirror(cache)
  notify()
  // debounce server writes to avoid rapid-fire PUTs
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    api('PUT', '/preferences', cache).catch(() => {})
    saveTimer = null
  }, 300)
}

/** 只改工作区偏好的某几项，其余保留（savePreferences 会整块替换嵌套对象）。 */
export function saveWorkspace(partial: Partial<WorkspacePreference>) {
  savePreferences({ workspace: { ...cache.workspace, ...partial } })
}

export function getPreferences(): Preferences {
  return cache
}

export function preferencesLoaded(): boolean {
  return loaded
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function getSnapshot(): Preferences {
  return cache
}

export function usePreferences(): [Preferences, typeof savePreferences] {
  const prefs = useSyncExternalStore(subscribe, getSnapshot)
  return [prefs, savePreferences]
}
