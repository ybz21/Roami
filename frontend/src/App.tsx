// ttmux Web 控制台 — React + Vite + Antd（统一深色主题）
// 布局（见 docs/design/web/01-overview.md）：
//   电脑 ≥1200 → 三栏：导航 Sider | 列表(页面) | 终端面板(常驻, 多标签)
//   平板/手机   → 终端为全屏覆盖层；手机底部 Tab 导航
// 终端：多标签 / 字号调节 / 复制 / 更多快捷键 / 断线自动重连。
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { bootstrapCluster, setCurrentNode, useClusterNodes, useCurrentNodeId } from './components/cluster/node-url'
import { NodeMark, nodeDotColor } from './components/cluster/NodeMark'
import { hubReasonText, useHubHealth } from './components/cluster/hub-health'
import {
  Layout, Button, Card, List, Tag, Form, Input, Select, Segmented, Tabs, Descriptions,
  Statistic, Row, Col, Space, Popconfirm, Empty, Modal, App as AntApp, Typography, Spin, Tooltip, Dropdown, Checkbox, Progress, AutoComplete, Radio, Switch, Collapse, InputNumber,
} from 'antd'
import type { MenuProps } from 'antd'
import { api, setUnauthorizedHandler } from './api'
import Term, { TermHandle, TermStatus } from './components/terminal/Terminal'
import ClaudeChat from './components/chat/ClaudeChat'
import CodexChat from './components/chat/CodexChat'
import FileBrowser from './components/files/FileBrowser'
import FileWorkspace from './components/files/FileWorkspace'
import AdaptivePanel from './components/shell/AdaptivePanel'
import { InspectorColumn } from './components/shell/InspectorColumn'
import MobileSubPage from './components/MobileSubPage'
import SettingsPage from './components/settings/SettingsPage'
// 非首屏的重页面（蜂群/Git 面板/浏览器/手机镜像/插件）按路由懒加载：切到对应 tab 才拉 chunk，
// 缩小首屏 index 块。都渲染在同一个 Suspense 边界内（见 lazyFallback，App 内 page）。
const GitPanel = lazyRetry(() => import('./components/git/GitPanel'))
const WorktreePanel = lazyRetry(() => import('./components/git/WorktreePanel'))
const RaceCreateModal = lazyRetry(() => import('./components/swarm/Race').then((m) => ({ default: m.RaceCreateModal })))
const RaceComparePanel = lazyRetry(() => import('./components/swarm/Race').then((m) => ({ default: m.RaceComparePanel })))
const PluginsPanel = lazyRetry(() => import('./components/plugins/PluginsPanel'))
const BrowserView = lazyRetry(() => import('./components/mirror/BrowserView'))
const PhoneView = lazyRetry(() => import('./components/mirror/PhoneView'))
const Swarm = lazyRetry(() => import('./components/swarm/Swarm'))
const Projects = lazyRetry(() => import('./components/projects/Projects'))
const HubPage = lazyRetry(() => import('./components/cluster/HubPage'))
import UpdateBanner from './components/UpdateBanner'
import { useThemeMode } from './theme'
import { useI18n } from './i18n'
import { usePreferences, loadPreferences, savePreferences } from './preferences'
import { detectPrompt } from './components/prompt'
import type { PromptSignal } from './components/prompt'
import { useLayout } from './layout'
import { useWorkspaceLayout, NAV_WIDTH, NAV_RAIL } from './components/shell/useWorkspaceLayout'
import { Workspace, SessionCapsule } from './components/shell/Workspace'
import { Navigation } from './components/shell/Navigation'
import { reorderTabs } from './components/shell/tabs'
import { nextInspector, pruneTabInspector, recallTabInspector, rememberTabInspector, tabKey } from './components/shell/tab-inspector-memory'
import { requestIntent, OPEN_FILE_INTENT } from './intents'
import { SessionDock } from './components/shell/SessionDock'
import { WorkspaceStatusBar } from './components/shell/WorkspaceStatusBar'
import { systemCells } from './components/shell/status-system'
import type { StatusAction } from './components/shell/status-cells'
import { sessionProject, useSessionProject, useSessionProjects, setSessionProjects, buildSessionProjects } from './components/sessions/session-project'
import { MobileSheet, SheetRow, SheetSection } from './components/shell/MobileSheet'
import { GlobalSearch, openPalette, type PaletteActions, type PaletteItem } from './components/shell/palette'
import { ProjectTree, firstSessionOf, taskPathOf } from './components/shell/ProjectTree'
import { InspectorPanels, type InspectorPanelKind } from './components/shell/InspectorPanels'
import { buildTaskTree, type TreeTask } from './components/shell/task-tree'
import { loadTreeSrc, saveTreeSrc, type TreeSrc } from './components/shell/task-tree-snapshot'
import { useSessionCloser } from './components/sessions/session-closer'
import { isInfraSession } from './components/sessions/infra-session'
import { taskKeyOf, isLooseTask, looseSessionOf, type TaskKey } from './components/sessions/task-key'
import RenameSessionModal from './components/sessions/RenameSessionModal'
import { TaskComposer } from './components/sessions/TaskComposer'
import { NewProjectModal } from './components/projects/Projects'
import { setSessionLabels, sessionLabel, sessionDisplay } from './components/sessions/session-label'
import { useLinkStatus } from './p2p/use-link-status'
import { startControlLink, stopControlLink } from './p2p/transport'
import FilesPage from './components/files/FilesPage'
import Login from './components/auth/Login'
import Sessions from './components/sessions/Sessions'
import Tasks from './components/tasks/Tasks'
import TerminalPane from './components/terminal/TerminalPane'
import SoloTerminal from './components/terminal/SoloTerminal'
import { ICONS } from './components/nav-icons'
import { normalizeRoute, setHashParams, readTermTokens, NO_TERMS, TASK_ROUTE } from './route-hash'
import type { ClaudeInfo } from './components/terminal/claude-info'
import { dropDeadTokens, loadTabs, saveTabs, type FileTab } from './components/terminal/term-tabs-store'
import type { FileTabMode } from './components/files/FilePathBar'
import { CloudIcon, ExitFullscreenIcon, FullscreenIcon, LogoutIcon, MoonIcon, MoreIcon, SearchIcon, SunIcon } from './icons'
import { lazyRetry } from './components/lazy-retry'

const { Sider, Content } = Layout
const { Text } = Typography

// 「蜂群」不进导航：项目页是唯一主入口（任务驱动，08 设计），蜂群从项目编队 tab 进
// （蜂群台深链 #/swarm/<名>）。
// 「会话」在 NAV 里但不进桌面侧栏两组：桌面从项目页进，命令面板能搜到；手机则**必须**
// 有个导航入口——搜索、筛选、Worktree 管理、新建竞赛全在那一页（13 §6）。
//
// 「概览」已并进项目页（18 设计）：两页画的是同一批项目卡、拉的是同一条 /projects，
// 概览独有的问候条/行动队列/活动轨现在挂在项目列表页顶上。旧链接由 normalizeRoute 接住。
const NAV = [
  { key: 'projects', labelKey: 'nav.projects' },
  { key: 'files', labelKey: 'nav.files' },
  { key: 'browser', labelKey: 'nav.browser' },
  { key: 'phone', labelKey: 'nav.phone' },
  { key: 'plugins', labelKey: 'nav.plugins' },
  { key: 'settings', labelKey: 'nav.env' },
]

// 桌面导航的两组（14 §4.4）。NAV 仍是全量注册表——命令面板和手机「更多」都从它取，
// 所以 settings 留在 NAV 里，只是不进这两组：它单独摆在侧栏底部（见 Navigation 的 settings）。
const NAV_WORKSPACE = ['projects', 'files']
const NAV_TOOLS = ['browser', 'phone', 'plugins']

// 手机底栏。13 §4.1 当初把「浏览器/手机镜像」折进「更多」，理由是低频且窄屏下几乎不可用
// （地址栏固定 150、设备选择器固定 240）——那两处固定宽度后来都改成自适应了，而这两页
// 恰恰是本机最常用的两个工具，藏在二级 sheet 里每次要点两下。现在放回底栏。
// 概览并进项目页后这里空出一格，不再补人：4 格 + 「更多」= 5 个按钮，390 宽下每格 78，
// 比原来 6 格的 65 宽出一截（13 §7.1 的命中区下限是 44，但相邻图标还要留够间隙）。
const MOBILE_NAV_KEYS = ['projects', 'files', 'browser', 'phone']
// 「更多」sheet 里的两段：会话属于工作区主线，不归到工具下面
const MOBILE_MORE_WORKSPACE: string[] = [] // 会话页退役（23 设计 §5）：不再有入口，路由留给老链接
const MOBILE_MORE_TOOLS = ['plugins', 'settings']
const MOBILE_MORE_KEYS = [...MOBILE_MORE_WORKSPACE, ...MOBILE_MORE_TOOLS]

// 用 Canvas 容器查询排版的页面（见 index.css 的 .tt-canvas[data-cq]）。逐页开，
// 不是全局开：container-type 会改变 fixed 后代的包含块。
const CQ_PAGES = new Set(['projects', 'sessions'])






// 探测结果（running/file/dir 这几个标量）没变就保留旧对象：5s 一轮的空翻新会让依赖它的 effect 和 memo 全部重跑
function sameProbe(a: any, b: any): boolean {
  if (a === b) return true
  if (!a || !b) return false
  const ks = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const k of ks) if (a[k] !== b[k]) return false
  return true
}

export default function App() {
  // 多机：底座那枚按钮 + 账户菜单顶部的机器列表。单机时两者都为空，界面与今天一致。
  // **必须在任何提前 return 之前**——这个组件下面有 `if (!authed) return <Login/>` 这类分支，
  // 放到后面就是条件调用 hook，登录成功那一帧 hook 数量变化，React 直接抛 #310（踩过）。
  const clusterNodes = useClusterNodes()
  const curNodeId = useCurrentNodeId()
  const curNode = clusterNodes.find((n) => n.id === curNodeId) || null
  // 中心不健康时，切换器那枚常驻按钮亮红点——见 cluster/hub-health.ts 里为什么不用绝对阈值
  const hubHealth = useHubHealth()

  const [authed, setAuthed] = useState<boolean | null>(null)
  const [route, setRoute] = useState(() => normalizeRoute(location.hash.replace(/^#\/?/, '') || 'projects'))
  const tab = route.split('/')[0]                                  // 基础页（swarm/leave → swarm）
  const swarmSub = tab === 'swarm' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : '' // 深链选中的蜂群
  const projectSub = tab === 'projects' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : '' // 深链选中的项目
  const pluginSub = tab === 'plugins' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : '' // 深链选中的插件（状态条点进来）
  const settingsSub = tab === 'settings' && route.includes('/') ? route.slice(route.indexOf('/') + 1) : '' // 设置的哪一类（node/browser）
  const go = (k: string) => {
    const qi = location.hash.indexOf('?')
    const qs = qi >= 0 ? location.hash.slice(qi) : ''
    location.hash = '#/' + k + qs
  }
  const { mode, toggle: toggleTheme } = useThemeMode()
  const { t } = useI18n()
  const [prefs] = usePreferences()
  const themeIcon = mode === 'dark' ? <SunIcon size={18} /> : <MoonIcon size={18} />
  const { phone: isMobile, desktop: hasSider } = useLayout()
  // 全屏（平板更易用：隐藏浏览器栏，等价 F11）。监听变化以同步按钮图标
  const [isFs, setIsFs] = useState(false)
  useEffect(() => {
    const on = () => setIsFs(!!(document.fullscreenElement || (document as any).webkitFullscreenElement))
    document.addEventListener('fullscreenchange', on)
    document.addEventListener('webkitfullscreenchange', on)
    return () => {
      document.removeEventListener('fullscreenchange', on)
      document.removeEventListener('webkitfullscreenchange', on)
    }
  }, [])

  // 多终端状态（从 URL 恢复）。URL 里放的是**会话 id**（见下方 sessIds 注释），
  // 组件内部一律用会话名——后端 API / WebSocket 收发的都是名字。
  const [terms, setTerms] = useState<string[]>([])
  const [active, setActive] = useState<string | null>(null)
  // ── 会话身份映射（id ↔ 名字）──（拉取在下面那条 /sessions 轮询里）
  // 会话名可以随时改，用它当 URL 里的 handle 会让分享/收藏的链接一改名就指空。id 由后端按
  // tmux session_id 派生、改名不变，所以 URL 只写 id。名字仍是 API/WS 的 handle，只在这里换算。
  const [sessIds, setSessIds] = useState<{ byId: Record<string, string>; byName: Record<string, string> } | null>(null)
  // 标签条**不按任务隔离**（用户拍板，推翻 22 设计 §3.3 的分片）：所有会话标签都在条上。
  // 「当前任务」不是独立状态，而是从当前标签推出来的：会话标签看它的 worktree（taskKeyOf），
  // 文件标签看它是从哪个任务开的。左树高亮、右栏的根、新建会话落进哪个目录，都跟着它走。
  const projTable = useSessionProjects()
  // 树里点会话时树已经知道它在哪个任务（worktree 轮询的名单），归属表可能还没到：记一笔兜底
  const taskHint = useRef<Record<string, TaskKey>>({})
  const keyOf = (n: string) => {
    const k = taskKeyOf(n, projTable[n]?.worktree)
    return isLooseTask(k) && taskHint.current[n] ? taskHint.current[n] : k
  }
  // 右栏三面板（22 设计 §3.4）：看哪个面板记本机；对话里点了路径要文件面板打开哪个
  const [panel, setPanelLocal] = useState<InspectorPanelKind>(() => {
    try { const v = localStorage.getItem('roam.inspectorPanel'); return v === 'git' || v === 'worktree' ? v : 'files' } catch { return 'files' }
  })
  const setPanel = (p: InspectorPanelKind) => { setPanelLocal(p); try { localStorage.setItem('roam.inspectorPanel', p) } catch { /* 记不住而已 */ } }
  // 文件标签：一条平铺列表，每条记着从哪个任务开的；activeFile 非空 = 当前标签是文件，空 = 当前标签是会话
  const [fileTabs, setFileTabs] = useState<FileTab[]>([])
  const [activeFile, setActiveFile] = useState('')
  const [reveal, setReveal] = useState<{ path: string; line: number; nonce: number } | undefined>()
  const [searchNonce, setSearchNonce] = useState(0)
  const curFile = activeFile
  const curFileTab = curFile ? fileTabs.find((f) => f.path === curFile) : undefined
  // 当前任务：文件标签 → 它记的任务；会话标签 → 它的 worktree；什么都没开 → 没有
  const activeTask: TaskKey | null = curFileTab ? (curFileTab.task || null) : active ? keyOf(active) : null
  const activeTaskRef = useRef<TaskKey | null>(null)
  activeTaskRef.current = activeTask
  const isMd = (p: string) => /\.(md|markdown|mdx|html?)$/i.test(p)
  // 单击开预览标签（斜体）；再单击别的文件替换它；已开着的直接激活
  const openFileTab = (path: string, line?: number) => {
    const key = activeTaskRef.current || ''
    setFileTabs((list) => {
      if (list.some((f) => f.path === path)) return list
      const tab: FileTab = { path, preview: true, mode: isMd(path) ? 'preview' : 'source', task: key }
      const i = list.findIndex((f) => f.preview)
      return i < 0 ? [...list, tab] : list.map((f, k) => (k === i ? tab : f))
    })
    setActiveFile(path)
    if (line && line > 0) setReveal((prev) => ({ path, line, nonce: (prev?.nonce || 0) + 1 }))
  }
  const pinFileTab = (path: string) => setFileTabs((list) => list.map((f) => (f.path === path ? { ...f, preview: false } : f)))
  const setFileMode = (path: string, mode: FileTabMode) => setFileTabs((list) => list.map((f) => (f.path === path ? { ...f, mode, preview: false } : f)))
  const closeFileTab = (path: string) => {
    setFileTabs((list) => {
      const i = list.findIndex((f) => f.path === path)
      const next = list.filter((f) => f.path !== path)
      // 关掉当前文件标签：回到邻居文件，没有邻居就回会话
      setActiveFile((cur) => (cur === path ? (next[i - 1] || next[i])?.path || '' : cur))
      return next
    })
  }
  // 点会话标签 = 文件标签让位
  const activateSession = (n: string) => { setActive(n); setActiveFile('') }
  // 左栏树的三份原料（22 设计 §3.2）：/projects 与每项目的 worktree 挂在下面那条 15s 轮询上，/sessions 挂 5s 那条。
  // 初值取上一轮的本地快照：worktree 那一趟要 1~2s，等它就等于每次刷新都从空树长一遍（见 task-tree-snapshot）
  const [treeSrc, setTreeSrc] = useState<TreeSrc>(() => loadTreeSrc())
  // 建了新会话就立刻把会话表 / 归属表 / worktree 都刷一遍，不等下一轮（分别 5s / 15s / 60s）
  const sessReload = useRef<(() => void) | null>(null)
  const treeReload = useRef<(() => void) | null>(null)
  // 真关会话（树的右键菜单）：和会话页同一套分流，关完刷树。
  // **必须在下面两个提前 return 之前调**——hook 数量在登录前后不一致，React 会报 Rendered more hooks。
  // closeTerm 在后面才定义，通过 ref 调
  const closeTermRef = useRef<(n: string) => void>(() => {})
  const closer = useSessionCloser((n) => closeTermRef.current(n), () => { sessReload.current?.(); treeReload.current?.() })
  // 树里双击会话行改会话名；双击任务行给任务起名（偏好 taskNames，不动会话和分支）
  const [renameInTree, setRenameInTree] = useState<string | null>(null)
  const [renameTask, setRenameTask] = useState<{ key: TaskKey; name: string } | null>(null)
  const [renameTaskVal, setRenameTaskVal] = useState('')
  // 项目行「+」/ ⌘N：在这个项目下开新任务——弹的是项目主页那个 composer（TaskComposer），不是老表单
  const [newTaskDir, setNewTaskDir] = useState<string | null>(null)
  // 树头「+」：就地弹新建项目框，不再先跳去项目列表页（建完自己跳到新项目主页）
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [sessList, setSessList] = useState<{ name: string; label?: string; lastActivity?: number; agent?: 'claude' | 'codex' }[]>([])
  // /sessions **成功**回来过一轮才算数（树按它判会话还在不在）。不能拿 sessIds 当这个信号：
  // 它在请求失败时也会被置成空表（那是为了放行标签还原），首轮就失败的话等于宣布「一个会话
  // 都没有」，树上的任务和会话会被一起抹掉。
  const [sessListLoaded, setSessListLoaded] = useState(false)
  // URL 上待还原的 id/名字（还没拿到 id 映射前先原样存着）
  const urlTerms = useRef<string[]>(readTermTokens().terms)
  const urlActive = useRef<string>(readTermTokens().active)
  // 「在新页面打开」开出来的页（terms=none）：这一页不继承任何会话，也不许拿空集回写——
  // 回写就把主页面记着的那串标签抹了。用户在这页真开了会话之后，它就是普通页面。
  const noTabs = useRef(readTermTokens().none)
  const restored = useRef(false) // 还原完成前不许回写 URL，否则会把待还原的参数抹掉
  const [overlay, setOverlay] = useState(false) // 手机/平板全屏终端
  const [moreOpen, setMoreOpen] = useState(false) // 手机「更多」sheet
  // 任务视图 = 桌面 + 路由 #/w + 有当前任务：中间整块给标签工作区，就是现成的 focus 几何
  const taskView = hasSider && tab === TASK_ROUTE
  // 空间状态（Page / Split / Focus）与 Dock 宽度：唯一的尺寸契约来源
  const space = useWorkspaceLayout(terms.length > 0 || taskView, taskView)

  // 右栏状态跟着标签走：切回一个标签，它上次开着就还开着、停在哪个面板也照旧。
  // 只在 large 档做——窄档右栏是覆盖式面板，切个标签就弹一层盖住正文，那不是记忆是打扰。
  // 会话那一半用**写进 URL 的那个 token**（会话 id），不是显示名：还原时 id→名字的映射
  // 晚一步才到，中间那一帧 active 还是 id。拿 active 直接当键，刷新前后就是两个键——
  // 记的那笔查不到，还会被下面的 prune 当成关掉的标签清掉（第一版就是这么丢的）。
  const insTab = tabKey({ active: (active && sessIds?.byName[active]) || active || '', activeFile })
  const rememberIns = (rec: { collapsed: boolean; panel: InspectorPanelKind }) => {
    // 只在任务视图里记：项目页/会话页也开得出右栏，但那里开的不属于任何一个标签，
    // 记到当前标签名下就成了「在别处开的，回到这个标签也跟着开」。
    if (taskView && space.large) rememberTabInspector(insTab, rec)
  }
  const toggleInspector = () => {
    const collapsed = !space.inspectorCollapsed
    space.setInspectorCollapsed(collapsed)
    rememberIns({ collapsed, panel })
  }
  /** 展开右栏（可顺带切面板）：⌘⇧E/G/F、对话工具行的 Git 都走这里 */
  const showInspector = (p?: InspectorPanelKind) => {
    if (p) setPanel(p)
    space.setInspectorCollapsed(false)
    rememberIns({ collapsed: false, panel: p || panel })
  }
  const pickPanel = (p: InspectorPanelKind) => {
    setPanel(p)
    rememberIns({ collapsed: space.inspectorCollapsed, panel: p })
  }
  // 换标签时：先把离开那个标签此刻的样子记下，再按新标签记着的摆好。
  // 依赖里只有标签键——collapsed/panel 是**读**的，写进依赖会让「用户刚收起右栏」也触发一次
  // 换标签逻辑，把他刚收起的状态当成新标签的状态存错地方。
  const insTabRef = useRef('')
  useEffect(() => {
    if (!taskView || !space.large) return
    const prev = insTabRef.current
    if (prev === insTab) return
    insTabRef.current = insTab
    if (prev) rememberTabInspector(prev, { collapsed: space.inspectorCollapsed, panel })
    const next = nextInspector(recallTabInspector(insTab), { collapsed: space.inspectorCollapsed, panel })
    if (next.collapsed !== space.inspectorCollapsed) space.setInspectorCollapsed(next.collapsed)
    if (next.panel !== panel) setPanel(next.panel)
  }, [insTab, taskView, space.large])
  const { message: antMessage, modal: antModal } = AntApp.useApp()
  const modKeyLabel = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '') ? '⌘' : 'Ctrl+'
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)
  useEffect(() => {
    const on = () => setOnline(navigator.onLine)
    window.addEventListener('online', on); window.addEventListener('offline', on)
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', on) }
  }, [])
  const [fontSize, setFontSize] = useState(13)
  const [statusMap, setStatusMap] = useState<Record<string, TermStatus>>({})
  const termRefs = useRef<Record<string, TermHandle | null>>({})
  // Claude Code / Codex 检测（针对已打开的终端）+ 每个标签的「对话/终端」视图切换
  const [claudeMap, setClaudeMap] = useState<Record<string, ClaudeInfo>>({})
  const [claudeView, setClaudeView] = useState<Record<string, boolean>>({})
  const [codexMap, setCodexMap] = useState<Record<string, ClaudeInfo>>({})
  const [codexView, setCodexView] = useState<Record<string, boolean>>({})

  // 一条轮询喂两件事（15s）：
  //   ① 导航 badge 的跨项目待收尾数（14 §4.4）
  //   ② 会话 → 项目 归属表，给终端标签写 `项目 · 会话`（14 §6.3）
  // 概览页轮的是同两条接口，所以两处显示的数字同源，不会互相打架。
  // 会话坞要显示「几个在等你」，而这个信号是 TerminalPane 抓屏算出来的（detectPrompt）。
  // 它已经在为每个已开会话轮询，别再开第二份——让它把结果递上来即可。
  const [mobileWaiting, setMobileWaiting] = useState<Record<string, boolean>>({})
  // 版本给状态条最右那一格用：**一次性**取，不是轮询（免登录接口，见 server.go）
  const [roamVersion, setRoamVersion] = useState('')
  useEffect(() => {
    let stop = false
    api('GET', '/version').then((r) => { if (!stop) setRoamVersion(r?.data?.version || '') }).catch(() => {})
    return () => { stop = true }
  }, [])
  const [unfinished, setUnfinished] = useState(0)
  const [swarmCount, setSwarmCount] = useState(0)
  // 当前会话所属仓库的 Git 状态，给状态条的分支/同步/改动三格用。
  // **不另起一条定时器**：挂在下面那条已经在跑的 15s 轮询上，换目录时立刻补一次。
  const [git, setGit] = useState<{ branch: string; ahead: number; behind: number; files: number; state: string; conflicts: number } | null>(null)
  // 用**响应式**的那个：sessionProject() 是普通函数，归属表更新时不会触发重渲，
  // 于是切了会话之后分支那几格要等到下一次别的 state 变化才跟上。
  // 树和当前项目在下面才算出来，快捷键里通过 ref 读（effect 挂得早）
  const treeRef = useRef<ReturnType<typeof buildTaskTree> | null>(null)
  const activeProjectRef = useRef<{ dir?: string } | null>(null)
  const activeProject = useSessionProject(active)
  activeProjectRef.current = activeProject
  // 分支那格看当前任务的 worktree，不是项目主仓库（22 设计 §3.2）
  const gitDir = activeProject?.worktree || activeProject?.dir || ''
  const gitDirRef = useRef(gitDir)
  gitDirRef.current = gitDir
  const loadGit = async () => {
    const dir = gitDirRef.current
    if (!dir) { setGit(null); return }
    try {
      const d = (await api('GET', `/git/status?dir=${encodeURIComponent(dir)}`))?.data
      // files / conflicts 是**数组**不是计数（踩过：`String(d.files)` 会画出
      // 一串 [object Object]，而空数组还是 truthy，那一格永远显示 0）
      const len = (v: unknown) => (Array.isArray(v) ? v.length : Number(v) || 0)
      setGit(d?.repo ? {
        branch: d.branch || '', ahead: d.ahead || 0, behind: d.behind || 0,
        files: len(d.files), state: d.state || '', conflicts: len(d.conflicts),
      } : null)
    } catch { /* 轮询失败保持上一轮，不清空 */ }
  }
  // 换会话就换了仓库：立刻补一次，不等下一个 15s
  useEffect(() => { if (authed) void loadGit() }, [authed, gitDir])
  // 不能按 hasSider 收窄：手机没有侧栏，但会话坞同样要写「项目 · 会话」
  useEffect(() => {
    // **必须等 authed**：hooks 跑在下面 `return <Login/>` 那些提前 return 之前，
    // 不等就会在「登录确认 + 多机引导」之前把业务请求发出去——单机上那是一发 401
    // （被 401 处理器吞掉，看不见），在中心上是**没带 /n/<id> 前缀的 404**，
    // 而且没人会告诉你为什么。踩过。
    if (!authed) return
    let stop = false
    const load = async () => {
      try {
        const [pr, an, sw] = await Promise.all([
          api('GET', '/projects'),
          api('GET', '/sessions/annotations').catch(() => null),
          api('GET', '/swarms').catch(() => null),
        ])
        if (stop) return
        const projects = pr?.data?.projects || []
        setUnfinished(projects.reduce((n: number, p: any) => n + (p.unfinished || 0), 0))
        setSessionProjects(buildSessionProjects(projects, an?.data || {}))
        const swarms = Array.isArray(sw) ? sw : sw?.data || []
        setSwarmCount(swarms.filter((x: any) => x?.status && x.status !== 'archived').length)
        void loadGit()
        // 项目行先画出来（/projects 是台账，几毫秒就回来）；worktree 慢，别让它压着项目一起等
        if (hasSider) setTreeSrc((cur) => ({ ...cur, projects }))
        // 左栏树要每个 git 项目的 worktree。后端每个 worktree 要跑十来条 git 命令，
        // 八个项目并发着 15s 一轮会把机器打满（实测 CPU 60%、温度报警），所以：
        // 串行、60s 一轮、项目列表照旧 15s 刷；手机没有树，不拉
        if (hasSider && Date.now() - wtAt > 60000) {
          wtAt = Date.now()
          const worktrees: Record<string, any[]> = {}
          for (const p of projects.filter((x: any) => x.git)) {
            if (stop) return
            try { worktrees[p.key] = (await api('GET', `/git/worktrees?dir=${encodeURIComponent(p.dir)}`))?.data || [] }
            catch { worktrees[p.key] = [] }
            if (stop) return
            // 到一个画一个：串行扫完要 1~2s，攒到最后一起 set 等于整棵树在那儿干等
            setTreeSrc((cur) => ({ projects, worktrees: { ...cur.worktrees, [p.key]: worktrees[p.key] } }))
          }
          if (stop) return
          // 扫完整份替换：这一轮没见到的项目（删了/不再是 git）连同快照里的残留一起清掉
          setTreeSrc({ projects, worktrees })
          saveTreeSrc({ projects, worktrees })
        }
      } catch { /* 轮询失败就保持上一轮的值，不清空 */ }
    }
    let wtAt = 0
    treeReload.current = () => { wtAt = 0; void load() }
    load()
    const i = setInterval(load, 15000)
    return () => { stop = true; clearInterval(i); treeReload.current = null }
  }, [authed, hasSider])

  // Canvas 滚动位置（14 §6.3.5）：终端一开，Canvas 变窄、卡片重排，scrollHeight
  // 从 1108 掉到 781，浏览器顺手把 scrollTop 归零——"你看到哪儿了"就这么没了。
  //
  // 两个坑：
  // ① **不能等状态变了再存**。effect 在 DOM 改完之后才跑，那时 scrollTop 已经是 0。
  //    所以持续记录，而不是在切换时抓一把。
  // ② **不能存像素**。两种形态的 scrollHeight 不一样，像素值换算过去是错的位置。
  //    存比例，还原时再乘回去——重排前后落在同一批卡片上。
  const canvasRatio = useRef(0)
  useEffect(() => {
    if (!hasSider) return
    const el = document.querySelector<HTMLElement>('.tt-canvas')
    if (!el) return
    const on = () => {
      const room = el.scrollHeight - el.clientHeight
      if (room > 0) canvasRatio.current = el.scrollTop / room
    }
    el.addEventListener('scroll', on, { passive: true })
    return () => el.removeEventListener('scroll', on)
  }, [hasSider])
  useEffect(() => {
    const el = document.querySelector<HTMLElement>('.tt-canvas')
    if (!el || !canvasRatio.current) return
    // 等这一帧的布局落定再还原，否则写进去的值会被重排冲掉
    const id = requestAnimationFrame(() => {
      const room = el.scrollHeight - el.clientHeight
      if (room > 0) el.scrollTop = Math.round(canvasRatio.current * room)
    })
    return () => cancelAnimationFrame(id)
  }, [space.mode])

  // ── 工作区快捷键（14 §9.1）：⌘J 开合终端、⌘⇧J 终端聚焦、Esc 退出聚焦 ──
  // 只挂带修饰键的这几个；字母单键快捷键要等命令面板一起做，且必须在输入框/终端
  // 聚焦时禁用，否则会把用户正在打的字吃掉。
  useEffect(() => {
    if (!hasSider) return
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'j') {
        e.preventDefault()
        // 任务视图：⌘J 开合右栏（Dock 没了，这个键让给它）；⌘⇧J 仍是 Focus
        if (taskView && !e.shiftKey) { space.toggleInspectorCollapsed(); return }
        if (e.shiftKey) { if (taskView) space.setNavCollapsed(!space.navCollapsed); else space.toggleFocus() }
        else { space.setFocus('none'); space.toggleDock() }
        return
      }
      // ⌘N 开任务（当前项目下，弹 composer）；⌘T 在当前 worktree 里派生终端；⌘W 收起当前标签（23 设计 §6）
      if (mod && !e.shiftKey && e.key.toLowerCase() === 'n') {
        e.preventDefault()
        const key = activeTaskRef.current
        const tr = treeRef.current
        const proj = key && tr ? tr.projects.find((p) => p.tasks.some((x) => x.key === key)) : undefined
        const dir = proj?.dir || activeProjectRef.current?.dir || tr?.projects[0]?.dir
        if (dir) setNewTaskDir(dir)
        return
      }
      if (mod && !e.shiftKey && taskView && e.key.toLowerCase() === 't') { e.preventDefault(); void newTerminalInTask('shell'); return }
      if (mod && !e.shiftKey && taskView && e.key.toLowerCase() === 'w') {
        e.preventDefault()
        if (curFile) closeFileTab(curFile); else if (active) closeTerm(active)
        return
      }
      // ⌘⇧F：右栏切到「内容」搜索并聚焦（22 设计 §9）
      if (mod && e.shiftKey && taskView && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        showInspector('files')
        setSearchNonce((n) => n + 1)
        return
      }
      // 右栏切面板：⌘⇧E 文件、⌘⇧G Git（22 设计 §9）
      if (mod && e.shiftKey && taskView && (e.key.toLowerCase() === 'e' || e.key.toLowerCase() === 'g')) {
        e.preventDefault()
        showInspector(e.key.toLowerCase() === 'e' ? 'files' : 'git')
        return
      }
      // Esc 收一层：覆盖态先收面板，聚焦态退回分栏。两者都不关终端、不离开页面。
      //
      // 注意这里**不需要**判断焦点在不在终端里：xterm 在捕获阶段就 stopPropagation
      // 了 Escape，事件根本冒泡不到 window。于是天然是对的——在 vim/Claude 里按 Esc
      // 进 TUI，焦点在页面上按 Esc 才收面板。改这段前先确认这条前提还成立。
      if (e.key === 'Escape') {
        if (taskView) return // 任务视图里 focus 是常态，Esc 没有可退的层
        if (space.mode === 'overlay') space.setDockOpen(false)
        else if (space.focus !== 'none') space.setFocus('none')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [hasSider, space, taskView, curFile, active])

  // 启动：先确认登录态，**再**做多机引导，最后才放行渲染。
  //
  // 三步的顺序是踩出来的。引导要带登录态才问得出结果，所以不能跑在 /me 之前（只会拿 401）；
  // 而它又必须跑在任何业务请求之前，否则第一轮请求发的是 /api/*——在中心上那是 404，
  // 而且没人会告诉你为什么。中间那个「先当单机跑一轮再纠正」的窗口就是这么来的。
  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false))
    let alive = true
    void (async () => {
      try {
        await api('GET', '/me')
      } catch {
        if (alive) setAuthed(false)
        return
      }
      await bootstrapCluster()
      if (!alive) return
      setAuthed(true)
      loadPreferences()
      navigator.clipboard?.readText?.().catch(() => {})
    })()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!authed) return
    let stop = false
    const load = () => api('GET', '/sessions').then((list) => {
      if (stop) return
      const byId: Record<string, string> = {}
      const byName: Record<string, string> = {}
      const labels: Record<string, string> = {}
      const names: { name: string; label?: string; lastActivity?: number; agent?: 'claude' | 'codex' }[] = []
      for (const s of Array.isArray(list) ? list : []) {
        // 基础设施会话（_ttmux-plugind / _ttmux-im）不进任何人看的列表：树、标签、⌘K、计数
        if (s?.name && isInfraSession(s.name)) continue
        if (s?.id && s?.name) { byId[s.id] = s.name; byName[s.name] = s.id }
        if (s?.name && s?.label) labels[s.name] = s.label
        if (s?.name) names.push({ name: s.name, label: s.label || undefined, lastActivity: s.lastActivity || undefined, agent: s.agent === 'claude' || s.agent === 'codex' ? s.agent : undefined })
      }
      setSessIds({ byId, byName })
      setSessListLoaded(true)
      // 内容没变就不换引用：树是按它 memo 的，5s 一次的空翻新会让整棵树白重算
      setSessList((cur) => (cur.length === names.length && cur.every((x, i) => x.name === names[i].name && x.label === names[i].label && x.lastActivity === names[i].lastActivity && x.agent === names[i].agent) ? cur : names))
      setSessionLabels(labels) // 展示名（@roam_name）：界面显示「名字（id）」，handle 仍是会话名
    }).catch(() => { if (!stop) setSessIds((m) => m || { byId: {}, byName: {} }) }) // 拉不到也要放行还原，别把标签卡在空白
    sessReload.current = load
    load()
    const t = setInterval(load, 5000)
    return () => { stop = true; clearInterval(t); sessReload.current = null }
  }, [authed])

  // 还原标签：拿到 id 表后做一次。老链接里存的是名字，id 表里查不到就按名字用。
  //
  // **URL 没写标签时回落到本机记的那份**（term-tabs-store）。少了这一步，从书签里打开裸域名
  // 就是「没有标签」，紧接着这个空集会被写回 store，把上次开着的一笔勾销——等于这台浏览器
  // 只要从裸域名进过一次，跨机保留就永远失效。URL 是显式的、可分享的句柄，它没说话时
  // 才轮到本机记忆说话。
  useEffect(() => {
    if (!sessIds || restored.current) return
    restored.current = true
    const toName = (tok: string) => sessIds.byId[tok] || tok
    const fromUrl = urlTerms.current
    const saved = fromUrl.length || noTabs.current ? null : loadTabs(curNodeId)
    if (saved && !urlActive.current) urlActive.current = saved.active
    // 查无此会话的 id 直接丢：切机器、会话在别处被关掉，都会在这里长出打不开的空标签
    const names = Array.from(new Set(dropDeadTokens(saved ? saved.terms : fromUrl, sessIds.byId).map(toName)))
    if (!names.length) return
    // 文件标签只记在本机（URL 不写）：不管 URL 有没有说标签，都从本机那份读
    const stored = saved || loadTabs(curNodeId)
    if (stored.files.length) { setFileTabs(stored.files); setActiveFile(stored.activeFile) }
    // 用户在 id 表回来之前就点开了标签 → 以他的操作为准，别被 URL 还原顶掉
    setTerms((cur) => (cur.length ? cur : names))
    setActive((cur) => {
      if (cur) return cur
      const a = urlActive.current ? toName(urlActive.current) : ''
      return a && names.includes(a) ? a : names[names.length - 1]
    })
  }, [sessIds, curNodeId])

  // 终端状态同步到 URL，刷新后可恢复。写 id；还没有 id 的（刚建、列表未刷新）先退回写名字。
  useEffect(() => {
    if (!restored.current) return
    if (noTabs.current) {
      if (!terms.length) return   // 还是那页干净的镜像页：URL 保持 terms=none，本机记忆不动
      noTabs.current = false      // 这页开了会话 → 回到普通页面的存续规则
    }
    const toTok = (n: string) => sessIds?.byName[n] || n
    const toks = terms.map(toTok)
    const activeTok = active ? toTok(active) : ''
    setHashParams({
      terms: toks.map(encodeURIComponent).join(','),
      active: activeTok ? encodeURIComponent(activeTok) : '',
    })
    // 同一份东西再按机器存一份：切走了还能切回来（见 term-tabs-store）
    saveTabs(curNodeId, toks, activeTok, fileTabs, activeFile)
    // 关掉的标签不留记录：文件标签的键是路径，翻过的文件多了这张表比标签本身还大
    pruneTabInspector([...toks.map((t) => `s:${t}`), ...fileTabs.map((f) => `f:${f.path}`)])
  }, [terms, active, fileTabs, activeFile, sessIds, curNodeId])

  // 左栏树：三份原料 memo 一次；已打开会话探测到的 agent 比 /projects 的名单准
  const tree = useMemo(() => buildTaskTree({
    projects: treeSrc.projects, worktrees: treeSrc.worktrees, sessions: sessList, placement: projTable,
    nameOf: (p) => prefs.taskNames?.[p] || undefined,
    agentOf: (n) => (claudeMap[n]?.running ? 'claude' : codexMap[n]?.running ? 'codex' : undefined),
    // 会话表一到就以它为准：快照/60s 的 worktree 名单里那些已经关掉的会话不该还挂在树上
    sessionsLoaded: sessListLoaded,
    // 互审陪跑叫 `<被审会话id>-review`，靠 id 表还原成人看得懂的那个会话
    nameOfId: (id) => sessIds?.byId[id],
  }), [treeSrc, sessList, claudeMap, codexMap, projTable, prefs.taskNames, sessIds, sessListLoaded])
  treeRef.current = tree

  // hash 路由：URL #/xxx 与当前页同步（支持前进/后退、刷新保持、收藏分享）
  useEffect(() => {
    const apply = () => setRoute(normalizeRoute(location.hash.replace(/^#\/?/, '') || 'projects'))
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])

  // 轮询已打开终端是否在跑 claude / codex（决定是否提供对话入口）
  useEffect(() => {
    if (!authed || terms.length === 0) return
    let stop = false
    const check = () => terms.forEach(async (n) => {
      try {
        const r = await api('GET', `/sessions/${encodeURIComponent(n)}/claude`)
        if (stop) return
        setClaudeMap((m) => (sameProbe(m[n], r.data) ? m : { ...m, [n]: r.data }))
        // 第一次探到 Claude 在跑就进对话视图：这是 Claude 会话的常态，终端是切过去看的那一面
        if (r.data?.running) setClaudeView((v) => (n in v ? v : { ...v, [n]: true }))
      } catch {}
      try { const r = await api('GET', `/sessions/${encodeURIComponent(n)}/codex`); if (!stop) setCodexMap((m) => (sameProbe(m[n], r.data) ? m : { ...m, [n]: r.data })) } catch {}
    })
    check()
    const t = setInterval(check, 5000)
    return () => { stop = true; clearInterval(t) }
  }, [authed, terms])

  // 通用传输 Phase 1a：登录后且用户偏好开 P2P → 建会话级常驻 control PC（左边栏全局状态）。
  // 偏好关闭 / 登出即拆链。P2P 是否真正可用由 transport 内部拉 /api/p2p/config 决定。
  const link = useLinkStatus()
  useEffect(() => {
    if (authed && prefs.p2pEnabled) startControlLink()
    else stopControlLink()
  }, [authed, prefs.p2pEnabled])

  if (authed === null) return <div style={{ height: '100dvh', display: 'grid', placeItems: 'center' }}><Spin size="large" /></div>
  // 登录成功后同样是「先引导、再放行」：不引导就渲染的话，第一轮业务请求会漏掉
  // /n/<id> 前缀。await 之后才 setAuthed，那个窗口就不存在了。
  if (!authed) {
    return <Login onOk={async () => {
      await bootstrapCluster()
      setAuthed(true); loadPreferences(); go('projects')
    }} />
  }

  // 独立单终端页（新标签全屏打开）：hash 路由 #/term/<会话名>
  const soloName = tab === 'term' && route.includes('/') ? decodeURIComponent(route.slice(route.indexOf('/') + 1)) : ''
  if (soloName) return <SoloTerminal name={soloName} />

  const openTerm = (rawName: string, task?: TaskKey) => {
    // tmux 自身会把 '.' ':' 替换为 '_'，前端也同步净化，
    // 确保标签名/WebSocket URL 与 tmux 实际 session 名一致。
    const name = rawName.replace(/[.:]/g, '_')
    // 会话表里还没有它 = 刚建的：立刻刷会话表 / 归属表 / worktree，树上马上归位
    if (!sessList.some((s) => s.name === name)) { sessReload.current?.(); treeReload.current?.() }
    setTerms((ts) => (ts.includes(name) ? ts : [...ts, name]))
    if (task) taskHint.current[name] = task
    setActive(name); setActiveFile('')
    if (hasSider) {
      // 桌面：进任务视图（22 设计）；Dock 那两个开关留着给手机与 Page 态
      go(TASK_ROUTE)
      space.setDockOpen(true); space.setFocus('none')
    }
    else setOverlay(true)           // 手机/平板：全屏
  }
  // 树：点任务 → 回到它已开着的会话标签；一个都没开就打开它的第一个会话
  const onTreeTask = (key: TaskKey) => {
    const open = terms.filter((n) => keyOf(n) === key)
    if (open.length) { setActive(active && open.includes(active) ? active : open[open.length - 1]); setActiveFile('') }
    else {
      const first = firstSessionOf(tree, key)
      if (first) { openTerm(first, key); return }
    }
    go(TASK_ROUTE)
    space.setDockOpen(true); space.setFocus('none')
  }
  // 标签条「新建」菜单顶上写着派生自哪个任务
  const activeTaskLabel = activeTask
    ? (isLooseTask(activeTask) ? sessionLabel(looseSessionOf(activeTask)) : tree.projects.flatMap((p) => p.tasks).find((x) => x.key === activeTask)?.name || activeTask.split('/').pop() || '')
    : ''
  const onTreeProject = (key: string) => go('projects/' + encodeURIComponent(key))
  // 标签条「新建」：在当前任务的 worktree 里开 shell / Claude / Codex，名字与项目页「新开命令行」同款后缀
  const newTerminalInTask = async (kind: 'shell' | 'claude' | 'codex' = 'shell', keyArg?: TaskKey) => {
    const key = keyArg ?? activeTaskRef.current
    const dir = key ? (taskPathOf(tree, key) || sessionProject(looseSessionOf(key))?.dir || '') : ''
    // 名字是展示名（@roam_name），后端另发 id：所以前缀用任务的展示名，不是那串 2026-… 的会话 id
    const first = key ? firstSessionOf(tree, key) : null
    const base = (first && sessionLabel(first)) || 'shell'
    const suffix = kind === 'shell' ? 'sh' : kind === 'claude' ? 'cc' : 'cx'
    let name = `${base}-${suffix}`
    const taken = new Set(sessList.map((s) => s.label || s.name))
    for (let i = 2; taken.has(name); i++) name = `${base}-${suffix}${i}`
    try {
      const res = await api('POST', '/sessions', dir ? { name, dir } : { name })
      const actual = res?.name || name
      if (kind !== 'shell') {
        const cmd = kind === 'claude' ? (prefs.claudeCommand || 'claude') : (prefs.codexCommand || 'codex')
        await api('POST', '/tasks/_/send', { sess: actual, msg: cmd })
      }
      openTerm(actual, key || undefined)
    } catch (e: any) { antMessage.error(e.message) }
  }
  const renameOpenTerm = (oldName: string, newName: string) => {
    if (oldName === newName) return
    setTerms((ts) => Array.from(new Set(ts.map((t) => (t === oldName ? newName : t)))))
    setActive((a) => (a === oldName ? newName : a))
    setStatusMap((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setClaudeMap((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setClaudeView((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setCodexMap((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setCodexView((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    if (termRefs.current[oldName]) {
      termRefs.current[newName] = termRefs.current[oldName]
      delete termRefs.current[oldName]
    }
    // id 表 5 秒才轮询一次，这里先就地改名，免得 URL 上的 id 短暂退化成名字再跳回来
    setSessIds((m) => {
      const id = m?.byName[oldName]
      if (!m || !id) return m
      const { [oldName]: _drop, ...rest } = m.byName
      return { byId: { ...m.byId, [id]: newName }, byName: { ...rest, [newName]: id } }
    })
  }
  const closeTerm = (name: string) => {
    setTerms((ts) => {
      const next = ts.filter((t) => t !== name)
      // 「下一个」在当前任务里找，别跳到别的任务的会话上（22 设计 §3.3）
      const cur = activeTaskRef.current
      const pool = cur ? next.filter((n) => keyOf(n) === cur) : next
      setActive((a) => (a === name ? (pool[pool.length - 1] || null) : a))
      if (next.length === 0) { setOverlay(false); space.setFocus('none') }
      return next
    })
    delete termRefs.current[name]
  }
  closeTermRef.current = closeTerm
  // 收尾一个任务：只有一个会话就走它的关闭分流（worktree 有东西会弹三选一）；多个会话先确认，
  // 多余的直接结束，最后一个再走分流——worktree 的去留在那一步定
  const finishTask = (task: TreeTask) => {
    const [first, ...rest] = task.sessions.map((s) => s.name)
    if (!first) return
    if (!rest.length) { void closer.beginClose(first); return }
    antModal.confirm({
      title: t('tree.finishTaskConfirm', { name: task.name, n: task.sessions.length }),
      okText: t('common.confirm'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
      onOk: async () => { for (const n of rest) await closer.kill(n); await closer.beginClose(first) },
    })
  }
  const setStatus = (name: string, s: TermStatus) => setStatusMap((m) => ({ ...m, [name]: s }))
  const sendKey = (seq: string) => active && termRefs.current[active]?.send(seq)

  // 标签拖拽排序（14 §7.1）。顺序本来就写进 URL 的 terms=，所以持久化是白拿的。
  // 标签条只画当前任务的那些，`to` 是可见列表里的位置：先在可见列表里排好，再按原位塞回全集。
  const reorderTerm = (name: string, to: number) => setTerms((ts) => {
    const cur = activeTaskRef.current
    if (!cur) return reorderTabs(ts, name, to)
    const inTask = (n: string) => keyOf(n) === cur
    const vis = reorderTabs(ts.filter(inTask), name, to)
    let i = 0
    return ts.map((n) => (inTask(n) ? vis[i++] : n))
  })


  // 全屏切换（标准 API + webkit 兜底）。不支持的浏览器（如 iOS Safari）隐藏按钮，改走「添加到主屏幕」
  const docEl: any = document.documentElement
  const fsSupported = !!(docEl.requestFullscreen || docEl.webkitRequestFullscreen)
  const toggleFs = () => {
    const doc: any = document
    if (doc.fullscreenElement || doc.webkitFullscreenElement) {
      (doc.exitFullscreen || doc.webkitExitFullscreen)?.call(doc)
    } else {
      (docEl.requestFullscreen || docEl.webkitRequestFullscreen)?.call(docEl)
    }
  }
  const fsIcon = isFs ? <ExitFullscreenIcon /> : <FullscreenIcon />

  const termPane = (
    <TerminalPane
      terms={terms} active={active} setActive={activateSession} closeTerm={closeTerm}
      fontSize={fontSize} setFontSize={setFontSize} statusMap={statusMap} setStatus={setStatus}
      termRefs={termRefs} sendKey={sendKey}
      claudeMap={claudeMap} claudeView={claudeView} setClaudeView={setClaudeView}
      codexMap={codexMap} codexView={codexView} setCodexView={setCodexView}
      onRename={renameOpenTerm}
      // 任务视图里没有「收起」：中间整块就是它，收起等于回项目页——点导航去
      onCollapse={taskView ? undefined : () => { setOverlay(false); space.setDockOpen(false) }}
      onReorder={reorderTerm}
      onNeedsInput={setMobileWaiting}
      onNew={taskView ? { terminal: () => { void newTerminalInTask('shell') }, claude: () => { void newTerminalInTask('claude') }, codex: () => { void newTerminalInTask('codex') }, taskLabel: activeTaskLabel } : undefined}
      // 任务视图里对话点路径 / Git 都落到右栏三面板；手机与 Page 态退回 TerminalPane 自己的二级页
      onOpenFile={taskView ? (path, line) => openFileTab(path, line) : undefined}
      onOpenGit={taskView ? () => showInspector('git') : undefined}
      inspector={taskView ? { open: !space.inspectorCollapsed, toggle: toggleInspector } : undefined}
      fileTabs={taskView ? fileTabs : undefined} activeFile={taskView ? curFile : undefined}
      taskDir={activeTask && !isLooseTask(activeTask) ? activeTask : (activeProject?.dir || '')}
      onFileTab={setActiveFile} onCloseFile={closeFileTab} onPinFile={pinFileTab} onFileMode={setFileMode} reveal={reveal}
      // Focus 只在桌面有意义：手机上终端本来就是全屏覆盖层；任务视图里 focus 是常态，没有开关
      // 任务视图里不放 Focus 钮：它干的就是侧栏脚「收起」那件事（⌘⇧J 仍在）；expanded 档的覆盖面板才需要它
      focus={!hasSider || taskView ? undefined : { on: space.focus !== 'none', toggle: space.toggleFocus, hint: `${modKeyLabel}⇧J` }}
    />
  )

  const pages: any = {
    swarm: <Swarm openTerm={openTerm} initialSwarm={swarmSub || undefined} onNav={(n) => { location.hash = n ? '#/swarm/' + encodeURIComponent(n) : '#/swarm' }} />,
    projects: <Projects openTerm={openTerm} closeTerm={closeTerm} initialKey={projectSub || undefined} activeTerm={active} />,
    sessions: <Sessions openTerm={openTerm} closeTerm={closeTerm} activeTerm={active} />,
    files: <FilesPage openTerm={openTerm} />,
    settings: <SettingsPage sub={settingsSub} onNav={(r) => go(r)} onLogout={logout} />,
    hub: <HubPage />,
    plugins: <PluginsPanel initialId={pluginSub || undefined} />,
    browser: <BrowserView />,
    phone: <PhoneView />,
  }
  // 懒加载页面 chunk 拉取期间的兜底：居中转圈（体量小，通常一闪而过）
  const lazyFallback = <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}><Spin /></div>
  // 任务视图（#/w）时 Canvas 归零，页面不用画；#/w 不在 pages 里，退回项目页
  const page = <Suspense fallback={lazyFallback}>{taskView ? null : (pages[tab] || pages.projects)}</Suspense>
  // browser 全幅(自带工具栏铺满)；phone 与概览/会话一致走 tt-page（同 16px 留白 + 满高，见 tt-page-phone）。
  // 浏览器页不再全幅特例：与 文件/手机 同走 tt-page 满高容器，五页左上角起点统一 (16,16)
  const pageNode = <div className={`tt-page tt-page-${tab}${isMobile ? ' tt-page-mobile' : ''}${isMobile && terms.length ? ' has-dock' : ''}`}>{page}</div>
  // Canvas 与 Dock 各包一层：两者在 Page / Split / Focus 三态间只改宽度，不改挂载
  // ⌘K 面板的**本地**条目：页面导航 + 已打开的会话——这两样数据就在内存里，打字即出。
  // 项目 / 全部会话 / 项目文件走后端 /search（见 shell/palette），不在这里凑。
  // 这一段在 authed / soloName 那几个提前 return 之后，**不能用 hook**——
  // useMemo 放这里就是条件调用，React 直接抛 #310（踩过一次）。所以这两个值每次
  // 渲染重算；面板那边的合并是纯函数，重算一次的代价远小于把整块状态提上来。
  const paletteItems: PaletteItem[] = [
    ...NAV.map((n) => ({
      key: `page:${n.key}`, group: t('workspace.groupPages'), title: t(n.labelKey),
      keywords: n.key, icon: ICONS[n.key], run: () => go(n.key),
    })),
    ...terms.map((name) => ({
      key: `term:${name}`, group: t('workspace.groupSessions'),
      title: sessionDisplay(name), desc: name === active ? t('workspace.current') : undefined,
      run: () => openTerm(name),
    })),
  ]

  // 面板选中结果后要做的事。三类各自一条路径：项目→详情页深链，会话→开终端，
  // 文件→切文件页并留下「打开这个文件」的意图（见 intents.ts，文件工作区接手）。
  const paletteActions: PaletteActions = {
    openRoute: (hash: string) => { location.hash = hash },
    openSession: (name: string) => openTerm(name),
    openFile: (path: string) => { if (taskView) openFileTab(path); else { go('files'); requestIntent(OPEN_FILE_INTENT, { path }) } },
  }

  const canvasNode = (
    <Content className="tt-canvas" data-cq={CQ_PAGES.has(tab) ? 'on' : undefined} style={{
      flex: 1, minWidth: 0, minHeight: 0, height: '100%', padding: 0,
      overflow: tab === 'browser' || tab === 'phone' || tab === 'files' ? 'hidden' : 'auto',
    }}>{pageNode}</Content>
  )
  const dockNode = (
    <div onTransitionEnd={() => window.dispatchEvent(new Event('resize'))}
      style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>{termPane}</div>
  )

  // 导航分两组（14 §4.4）：工作区 = 干活的地方，工具 = 看别的东西的地方。
  // 设置 / 关于 不在任何一组里——它们进底部账户菜单，见下面的 accountMenu。
  // 桌面不再分「工作区 / 工具」两组（22 设计评审：组名和组间空隙占掉树的位置）；手机「更多」sheet 仍分组
  const navGroups = [
    { label: '', items: [...NAV_WORKSPACE, ...NAV_TOOLS] },
  ].map((g) => ({
    label: g.label,
    items: g.items.map((key) => {
      const n = NAV.find((x) => x.key === key)!
      return {
        key: n.key, label: t(n.labelKey), icon: ICONS[n.key],
        // badge 只报「需要行动」的数量，不报普通总数（14 §4.4）。这里取跨项目待收尾
        // 数：它来自 /projects 一条请求，全局常新；「等待输入」要逐会话抓屏才知道，
        // 为一个角标常驻轮询十几个会话不划算，那个数留在概览页。
        badge: n.key === 'projects' ? unfinished : undefined,
        badgeTitle: n.key === 'projects' ? t('overview.unfinishedN', { count: unfinished }) : undefined,
      }
    }),
  }))

  // 切机器 = 换「浏览 / 新开操作落到哪台」。整页重载是这一版的取舍：页面各自缓存着
  // 上一台的数据，逐个清远比重来一次更容易漏。
  //
  // URL 上的 terms/active 是**上一台**的会话 id，原样带过去会在新机器上还原一批根本不存在
  // 的标签（一堆打不开的窗口，同名会话还可能连错机器）。所以换成那台机器**自己上次**开着
  // 的标签——各记各的，切回来还在（term-tabs-store）。
  //
  // 抽成函数是因为**入口有两个**：桌面在侧栏底座的切换器，手机在「更多」里。
  // 手机上原来根本没有入口——切换器只挂在 <Sider> 里，而手机没有 Sider。
  const switchNode = (id: string) => {
    const back = loadTabs(id)
    setCurrentNode(id)
    setHashParams({
      // 干净页（terms=none）换台机器还是干净页——那台的标签不该在这里长出来
      terms: noTabs.current ? NO_TERMS : back.terms.map(encodeURIComponent).join(','),
      active: noTabs.current || !back.active ? '' : encodeURIComponent(back.active),
    })
    location.reload()
  }

  // 多机：机器列表接在账户菜单最上面（切机器是「换浏览范围」，不是页面）。
  // 单机时 nodes 为空，这一段整个不出现，菜单与今天逐项一致。
  // 顶部切换器的下拉：就是机器列表本身，不再套一层分组标题——它已经有自己的按钮当标题了
  const nodeItems: MenuProps['items'] = clusterNodes.length ? [
    ...clusterNodes.map((n) => ({
      key: 'node:' + n.id,
      // 方章不走 antd 的 icon 槽：那个槽的间距归 antd 管，实测方章会贴着名字（「JE|Jetson」）。
      // 整行自己排，间距用令牌，样式在 index.css 的 .tt-nodemenu 段。
      label: (
        <span className={`tt-nodemenu${n.id === curNodeId ? ' on' : ''}`}>
          <NodeMark name={n.name} size="sm" current={n.id === curNodeId} offline={!n.online} />
          <span className="nm">{n.name}</span>
          <span className="lat">{n.online ? t('node.latencyMs', { ms: n.latencyMs }) : t('node.offline')}</span>
          <i className="dot" style={{ background: nodeDotColor(n) }} />
        </span>
      ),
      disabled: !n.online,
      onClick: () => switchNode(n.id),
    })),
    // 中心单独一条，用分隔线跟机器列表隔开：它的语义是「去看中心」，不是「把浏览范围切过去」。
    // 中心不跑会话/项目/文件/终端，真切过去大半个应用是空的——那不是另一台机器，是另一种东西。
    { type: 'divider' as const },
    {
      key: 'hub-page',
      // 不走 antd 的 icon 槽：那个槽的间距归 antd 管，实测图标会贴着字，而且与上面几行
      // 机器的方章不在同一条竖线上。这里给它一个同尺寸的方框，三行文字左边缘才对得齐。
      label: (
        <span className={`tt-nodemenu hub${hubHealth.level === 'ok' ? '' : ' alarm'}`}>
          <span className="mk"><CloudIcon size={12} /></span>
          <span className="nm">{t('hub.title')}</span>
          <span className="lat">
            {hubHealth.level === 'ok'
              ? t('hub.onlineShort', { n: clusterNodes.filter((n) => n.online).length })
              : hubReasonText(hubHealth, t)}
          </span>
        </span>
      ),
      onClick: () => go('hub'),
    },
  ] : []

  // 侧栏脚的「当前设备」账户菜单没了（22 设计 §3.2 拍板）：关于 / 主题本来在设置页，全屏 / 退出并进设置 › 外观。
  // 手机「更多」sheet 里那几行还在（手机没有设置页的常驻入口）。

  // 侧栏是否是 64px 轨：用户手动收起 / Focus 聚焦 / 非 large 档（expanded 一律用轨）
  // 任务视图里 focus 是常态（22 设计），侧栏必须留着——树就在里面；只有用户 ⌘⇧J 的 Focus 才收轨
  const navRail = space.navCollapsed || (space.mode === 'focus' && !taskView)

  // 状态条的系统格：全部由 App 已经有的 state 算出来，**一条新请求都不发**
  // （18 设计刚删掉过一套「每 6s 对 ≤14 个会话各发 3 条请求」的轮询，别再种一棵）。
  const statusCells = systemCells({
    online,
    node: curNode ? { name: curNode.name, online: curNode.online, latencyMs: curNode.latencyMs } : null,
    hubAlarm: hubHealth.level === 'ok' ? undefined : hubReasonText(hubHealth, t),
    clustered: clusterNodes.length > 0,
    sessions: terms.length,
    waiting: Object.values(mobileWaiting).filter(Boolean).length,
    unfinished,
    agents: terms.filter((n) => claudeMap[n]?.running || codexMap[n]?.running).length,
    version: roamVersion,
    git,
    projectKey: activeProject?.key || '',
    swarms: swarmCount,
    link,
    t,
  })
  // 插件只能给白名单里的两种动作，给不了任意跳转（20 设计 §05 约束①）
  const onStatusAction = (a: StatusAction) => {
    // 直接写 hash，不走 go()：go() 只认页面名，会把 `/<id>` 那截深链抹掉，
    // 于是点 CPU 只到插件列表页第一项——而你刚点的就是主机监控。
    if (a.kind === 'route') location.hash = a.id
    else if (a.kind === 'pluginView') location.hash = '#/plugins/' + encodeURIComponent(a.id)
  }

  return (
    // 外壳改成列向：[ 横向行(侧栏 + 工作区) ][ 状态条 ]。状态条必须占位——
    // 用 position:fixed 的话上面那层照旧按 100dvh 算高，页面最后一行会永远
    // 压在条底下，而且横向滚动条一闪就把画布挪 10px（AGENTS「文档永远不滚动」）。
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-base)' }}>
    {/* overflow 用 clip 不用 hidden：hidden 仍是滚动容器，收起的终端坞（宽 0、内容仍挂着）里
        一个 autoFocus 就能让浏览器把整个 Layout 往右「滚」出去，左侧栏只剩右边缘露在屏幕外——
        会话页上就是这么被挤成一条窄轨的。clip 不是滚动容器，谁也滚不动它 */}
    <Layout style={{ flex: 1, minHeight: 0, overflow: 'clip', background: 'var(--bg-base)' }}>
      <UpdateBanner />
      {/* Focus 时导航收成 64px 轨而不是消失——上下文始终可找回（14 §4.1，老 dockMax 的病根）。
          expanded 档也一律用轨：905–1279 展开 224 侧栏会把 Canvas 挤破契约。*/}
      {hasSider && (
        <Sider collapsible trigger={null} collapsedWidth={NAV_RAIL} width={NAV_WIDTH} theme={mode}
          collapsed={navRail}
          style={{ position: 'sticky', top: 0, height: '100%', background: 'var(--bg-base)', borderRight: '1px solid var(--border-subtle)' }}>
          <Navigation
            rail={navRail} active={tab} groups={navGroups} onGo={go}
            settings={{ key: 'settings', label: t('nav.env'), icon: ICONS.settings }}
            nodeMenu={nodeItems}
            onSearch={openPalette}
            searchHint={`${modKeyLabel}K`}
            tree={<ProjectTree tree={tree} activeTask={activeTask} activeSession={active}
              onProject={onTreeProject} onTask={onTreeTask} onSession={(key, name) => openTerm(name, key)}
              onAddProject={() => setNewProjectOpen(true)}
              onRename={setRenameInTree}
              onRenameTask={(key, name) => { setRenameTask({ key, name }); setRenameTaskVal(prefs.taskNames?.[key] || name) }}
              onNewTask={setNewTaskDir} onKill={(n) => { void closer.beginClose(n) }} onFinishTask={finishTask}
              onNewInTask={(key, kind) => { void newTerminalInTask(kind, key) }}
              onRemoveProject={(key) => antModal.confirm({
                title: t('project.removeConfirm'), okText: t('project.remove'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
                onOk: async () => { try { await api('DELETE', `/projects/${encodeURIComponent(key)}`); antMessage.success(t('project.removed')); treeReload.current?.() } catch (e: any) { antMessage.error(e.message) } },
              })} />}
            hubAlarm={hubHealth.level === 'ok' ? undefined : hubReasonText(hubHealth, t)}
            node={curNode ? {
              name: curNode.name,
              // 切换器那枚**不涂蓝**：它永远是当前机器，`current` 那层高亮不传递任何信息，
              // 只会和别处的蓝撞成两块「选中」。蓝留给下拉列表里区分「哪台是当前」，
              // 那里才有对比对象。
              mark: <NodeMark name={curNode.name} size="sm" />,
              dot: nodeDotColor(curNode),
              latency: curNode.online ? t('node.latencyMs', { ms: curNode.latencyMs }) : t('node.offline'),
            } : null}
            onToggleRail={() => space.setNavCollapsed(!space.navCollapsed)}
          />
          <RenameSessionModal session={renameInTree} onClose={() => setRenameInTree(null)} onDone={renameOpenTerm} />
          {closer.node}
          <Modal open={!!renameTask} title={t('tree.renameTask')} okText={t('common.confirm')} cancelText={t('common.cancel')} destroyOnClose
            onCancel={() => setRenameTask(null)}
            onOk={() => {
              if (!renameTask) return
              const v = renameTaskVal.trim()
              const next = { ...(prefs.taskNames || {}) }
              if (v) next[renameTask.key] = v; else delete next[renameTask.key]
              savePreferences({ taskNames: next })
              setRenameTask(null)
            }}>
            <Input autoFocus value={renameTaskVal} onChange={(e) => setRenameTaskVal(e.target.value)} placeholder={renameTask?.name}
              onPressEnter={() => document.querySelector<HTMLButtonElement>('.ant-modal .ant-btn-primary')?.click()} />
            <div style={{ marginTop: 8, color: 'var(--text-dimmer)', fontSize: 'var(--fs-meta)' }}>{t('tree.taskNameHint')}</div>
          </Modal>
          {/* 开任务（照 Orca 的「创建工作树」框）：顶上先选项目，下面就是项目主页那个 composer */}
          <Modal open={!!newTaskDir} footer={null} width={860} destroyOnClose onCancel={() => setNewTaskDir(null)} title={t('tree.newTask')}>
            {newTaskDir && (
              <>
                <div className="tt-lbl">{t('tree.projectField')}</div>
                <Select value={newTaskDir} onChange={(v) => setNewTaskDir(v)} style={{ width: '100%', marginBottom: 12 }}
                  options={treeSrc.projects.map((p: any) => ({ value: p.dir, label: <span>{p.name} <span style={{ color: 'var(--text-dimmer)', fontFamily: 'var(--mono)', fontSize: 'var(--fs-micro)', marginLeft: 8 }}>{p.dir}</span></span> }))} />
                <TaskComposer key={newTaskDir} dir={newTaskDir} isGit={treeSrc.projects.find((p: any) => p.dir === newTaskDir)?.git !== false}
                  openTerm={openTerm} onCreated={() => setNewTaskDir(null)} autoFocus />
              </>
            )}
          </Modal>
          {/* 建完立刻刷树：项目列表 15s 一轮、worktree 60s 一轮，不刷就得等 */}
          <NewProjectModal open={newProjectOpen} onClose={() => setNewProjectOpen(false)} onCreated={() => treeReload.current?.()} />
        </Sider>
      )}

      {/* 主区：Canvas ｜ Dock ｜ Inspector。终端**常驻挂载**（收起时宽度归零、Focus 时页面归零），换形态不断连接。*/}
      <Layout style={{ background: 'var(--bg-base)', minWidth: 0 }}>
        {/* 顶栏 Command Center 撤了（22 设计 §3.5）：搜索去了侧栏、「新建」去了标签条与项目页、终端数状态条本来就有 */}
        {hasSider && (terms.length > 0 || taskView) ? (
          // 三态（page / overlay / focus）都走同一个 Workspace：换的是几何，
          // 不是组件树，终端因此不会在开合时被卸载重建。
          <Workspace
            mode={space.mode} canvas={canvasNode} dock={dockNode}
            onDismiss={() => space.setDockOpen(false)}
            inspectorCollapsed={space.inspectorCollapsed}
            onToggleInspector={toggleInspector}
            inspectorWidth={space.inspectorWidth} inspectorBounds={space.inspectorBounds}
            inspectorOverlay={!space.large} canvasFitsInspector={space.canvasFitsInspector}
            onInspectorResize={space.setInspectorWidth} onInspectorReset={space.resetInspectorWidth}
            capsule={space.overlayCapable && space.mode === 'page' ? (
              // 胶囊只有 320px，显示 sessionLabel 而不是 sessionDisplay——后者带
              // 「（会话 id）」后缀，在这个宽度下正好被截在 id 中间，什么也没说清。
              // 完整名留给 title。（前缀成 `项目 · 会话` 是 14 §7 的统一命名，
              // 要连 Dock 标签和切换 sheet 一起改，不在这里单独做半套。）
              <SessionCapsule
                label={sessionLabel(active) || active} count={terms.length}
                onOpen={() => { space.setFocus('none'); space.setDockOpen(true) }}
                title={`${sessionDisplay(active)} · ${t('terminal.expandTitle')} (${modKeyLabel}J)`}
              />
            ) : null}
          />
        ) : (
          // 没有终端时不走 Workspace（不必为空 Dock 撑一套几何），但 Inspector 这一列
          // 两边都要有——Git 面板在项目页也开得出来。
          <div style={{ position: 'relative', display: 'flex', flex: 1, minHeight: 0 }}>
            {canvasNode}
            {hasSider && (
              <InspectorColumn width={space.inspectorWidth} bounds={space.inspectorBounds}
                overlay={!space.large} onResize={space.setInspectorWidth}
                onReset={space.resetInspectorWidth}
                collapsed={space.inspectorCollapsed} onToggleCollapsed={toggleInspector} />
            )}
          </div>
        )}
      </Layout>

      {/* 右栏三面板：唯一的 AdaptivePanel，portal 进 InspectorColumn 的槽位；Page 态 open=false 自动收起 */}
      {hasSider && (() => {
        const loose = activeTask ? isLooseTask(activeTask) : false
        const owner = activeTask && !loose ? tree.projects.find((p) => p.tasks.some((x) => x.key === activeTask)) : undefined
        const task = owner?.tasks.find((x) => x.key === activeTask)
        const dir = activeTask && !loose ? activeTask : (activeProject?.dir || '')
        const scope = owner && task ? `${owner.name} · ${task.name}` : (active ? sessionLabel(active) || active : '')
        return (
          <InspectorPanels open={taskView} panel={panel} onPanel={pickPanel} dir={dir} scope={scope}
            openTerm={openTerm}
            onOpenFile={(p) => openFileTab(p)} selectedPath={curFile}
            searchNonce={searchNonce} onOpenLine={(p, line) => openFileTab(p, line)}
            onClose={() => { if (!space.inspectorCollapsed) toggleInspector() }} />
        )
      })()}

      {/* 底栏 6 格 + 会话坞（13 §4.1/§4.2）：概览/项目/文件/浏览器/手机 + 更多。
          360px 下每格 60px，标签 11px 单行截断——所以格数到此为止，再加就只剩图标了。
          「更多」sheet 仍分「工具 / 账户」两段：退出登录和功能页并排时误触代价差了几个
          数量级，所以它收在账户行的二级里。*/}
      {isMobile && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          zIndex: 'var(--z-nav)' as unknown as number, paddingBottom: 'var(--safe-b)',
          background: 'var(--bg-container)', borderTop: '1px solid var(--border)',
        }}>
        {/* 会话坞叠在底栏之上，两者共用同一个 fixed 容器与安全区内边距——
            分开两个 fixed 就得手算彼此的高度，底栏一改高度就错位 */}
        <SessionDock
          sessions={terms} active={active} needsInput={mobileWaiting}
          running={(n) => !!(claudeMap[n]?.running || codexMap[n]?.running)}
          onOpen={() => setOverlay(true)}
          onPick={(n) => { setActive(n); setOverlay(true) }}
          onClose={closeTerm}
        />
        <nav style={{ display: 'flex' }}>
          {MOBILE_NAV_KEYS.map((key) => {
            const n = NAV.find((x) => x.key === key)!
            return (
              <button key={n.key} onClick={() => go(n.key)} className="tt-bottomnav-btn"
                style={{ color: tab === n.key ? 'var(--accent)' : 'var(--text-dim)' }}>
                {ICONS[n.key]}<span>{t(n.labelKey)}</span>
              </button>
            )
          })}
          <button onClick={() => setMoreOpen(true)} className="tt-bottomnav-btn"
            style={{ color: MOBILE_MORE_KEYS.includes(tab) ? 'var(--accent)' : 'var(--text-dim)' }}>
            <MoreIcon size={18} /><span>{t('common.more')}</span>
          </button>
        </nav>
        </div>
      )}

      {isMobile && (
        <MobileSheet open={moreOpen} title={t('common.more')} onClose={() => setMoreOpen(false)}>
          {/* 手机没有顶栏，⌘K 也按不出来——全局搜索在这里给一个入口，否则手机上
              根本到不了它（同一个面板，见 shell/palette）。 */}
          <SheetRow icon={<SearchIcon size={16} />} title={t('workspace.search')}
            desc={t('workspace.searchPlaceholder')}
            onClick={() => { setMoreOpen(false); openPalette() }} />

          {/* 机器排在最前：它换的是「下面这些页看哪台机器」，是别的行的前提，不是并列项。
              桌面的切换器挂在 <Sider> 的底座里，而手机根本没有 Sider——这一段之前是缺的，
              手机上连不上第二台机器（能看见别的机器，但切不过去）。
              单机时 clusterNodes 为空，整段不出现，与今天逐项一致。 */}
          {clusterNodes.length > 0 && (<>
            <SheetSection>{t('node.switch')}</SheetSection>
            {clusterNodes.map((n) => (
              <SheetRow key={n.id}
                icon={<NodeMark name={n.name} size="sm" current={n.id === curNodeId} offline={!n.online} />}
                title={n.name}
                desc={n.online ? t('node.sessionsN', { count: n.sessionCount }) : t('node.offline')}
                active={n.id === curNodeId}
                extra={<i style={{ display: 'block', width: 7, height: 7, borderRadius: '50%', background: nodeDotColor(n) }} />}
                onClick={() => { if (!n.online || n.id === curNodeId) { setMoreOpen(false); return } switchNode(n.id) }} />
            ))}
          </>)}

          <SheetSection>{t('nav.groupWorkspace')}</SheetSection>
          {MOBILE_MORE_WORKSPACE.map((key) => {
            const n = NAV.find((x) => x.key === key)!
            return <SheetRow key={n.key} icon={ICONS[n.key]} title={t(n.labelKey)}
              onClick={() => { setMoreOpen(false); go(n.key) }} />
          })}
          <SheetSection>{t('nav.groupTools')}</SheetSection>
          {MOBILE_MORE_TOOLS.map((key) => {
            const n = NAV.find((x) => x.key === key)!
            return <SheetRow key={n.key} icon={ICONS[n.key]} title={t(n.labelKey)}
              onClick={() => { setMoreOpen(false); go(n.key) }} />
          })}
          <SheetSection>{t('mobile.groupAccount')}</SheetSection>
          <SheetRow icon={themeIcon} title={mode === 'dark' ? t('common.lightTheme') : t('common.darkTheme')}
            onClick={() => { toggleTheme() }} />
          {fsSupported && (
            <SheetRow icon={fsIcon} title={isFs ? t('common.exitFullscreen') : t('common.fullscreen')}
              onClick={() => { toggleFs() }} />
          )}
          <SheetRow icon={ICONS.github} title={t('nav.about')} onClick={() => { setMoreOpen(false); go('about') }} />
          <SheetRow
            icon={<LogoutIcon />}
            title={t('common.logout')} desc={t('common.logoutConfirm')} danger
            onClick={() => { setMoreOpen(false); Modal.confirm({ title: t('common.logoutConfirm'), okText: t('common.logout'), cancelText: t('common.cancel'), okButtonProps: { danger: true }, onOk: logout }) }} />
        </MobileSheet>
      )}

      {/* 全局搜索挂在这里而不是顶栏里：手机没有顶栏、终端聚焦时 xterm 会吃掉按键，
          都得靠这一处（见 shell/palette/GlobalSearch）。入口另给：顶栏那枚框、
          手机「更多」里那一行、以及 ⌘K / Ctrl+K。 */}
      <GlobalSearch items={paletteItems} actions={paletteActions} dir={activeProject?.worktree || activeProject?.dir} />

      {/* 手机/平板：全屏会话覆盖层（桌面用右侧停靠栏，不走这里）*/}
      {isMobile && overlay && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 'var(--z-session)' as unknown as number, background: 'var(--bg-term)', display: 'flex', flexDirection: 'column' }}>
          {termPane}
        </div>
      )}
    </Layout>

    {/* 手机不常驻：底部已经叠了会话坞 + 底栏两层，再加一条就是第三层，
        360px 宽的屏上底部会吃掉三分之一（20 设计 §10）。 */}
    {hasSider && <WorkspaceStatusBar system={statusCells} onAction={onStatusAction} />}
    </div>
  )

  function logout() {
    api('POST', '/logout').catch(() => {}).finally(() => setAuthed(false))
  }
}



