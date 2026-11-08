// 工作区空间状态：Page / Focus / Overlay 三态与右栏（Inspector）宽度。
//
// 这里只有尺寸与状态，不含任何 JSX——分栏契约是纯算术，值得单独测。
//
// 14 稿的「页面 ｜ 终端」并排（split）已按 22 设计 D1 作废：large 档要么整块页面（Page），
// 要么整块任务工作区（Focus，即任务视图）；终端不再和页面抢宽度，Dock 宽度、拖拽分隔条、
// 42vw 默认值那一整套算术随之删掉。expanded 档（905–1279）终端仍是覆盖式面板，手机全屏。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLayout, type WindowSize } from '../../layout'
import { usePreferences, preferencesLoaded, saveWorkspace } from '../../preferences'
import { reportInspectorCap, useInspectorOpen, useInspectorWantWidth, INSPECTOR_REVEAL_EVENT } from './inspector'

/** 页面最窄 560，与 index.css 的 --canvas-min 同源（14 §8.2）：右栏再宽也不能把页面挤破，挤破就整页让位 */
export const CANVAS_MIN = 560
/** 右栏那条 8px 分隔条 */
export const RAIL = 8
export const NAV_WIDTH = 280 // 22 设计 §5：左栏 280，树里的任务卡才摆得下名字 + 状态
// 轨态 48：一列 20px 图标要的就是这个宽度（VS Code 活动栏同宽）。64 是给「图标 + 文字」
// 留的位子，可轨态本来就没有文字，多出来的 16px 只是一条空黑边贴在页面左边。
export const NAV_RAIL = 48
/** expanded 档覆盖式终端面板的宽度（13 §13.1）。 */
export const OVERLAY_DOCK = 480

/** Inspector（右栏：文件 / Git / Worktree）的尺寸契约，见 14-desktop-workspace/panels-desktop.html */
export const INSPECTOR_MIN = 280
export const INSPECTOR_DEFAULT = 350
// 文件抽屉是两层折叠（文件夹层 + 预览层），两层加起来能到一千出头——880 会把预览截短。
// 真正的上界仍由 inspectorBounds 按剩余空间给，这里只是"用户最多能拖多宽"。
export const INSPECTOR_MAX = 1200

export type SpaceMode = 'page' | 'focus' | 'overlay'
export type FocusTarget = 'none' | 'page' | 'dock'

/** 右栏打开之后，页面还保不保得住 560。保不住就整页让位（Workspace 把 Canvas 归零） */
export function canvasFitsWith(o: { workspaceWidth: number; inspectorWidth: number }): boolean {
  return o.workspaceWidth - o.inspectorWidth - RAIL >= CANVAS_MIN
}

/** 右栏的拖拽区间：下界 280，上界不超过 1200、也不撑破工作区（撑破 = 文档横向溢出 = 10px 滚动条） */
export function inspectorBounds(o: { workspaceWidth: number }): { min: number; max: number } {
  const room = o.workspaceWidth - RAIL
  return { min: INSPECTOR_MIN, max: Math.max(INSPECTOR_MIN, Math.min(INSPECTOR_MAX, room)) }
}

/**
 * 三态判定（14 §4.1 + 13 §13.1 + 22 D1）。抽成纯函数是因为「哪一档进哪一态」正是最容易改错的地方。
 *
 * large：任务视图是 focus（中间整块给标签工作区），其余一律 page——终端只在任务视图里出现。
 * expanded（905–1279）走 **overlay**：并排最多只能挤出 561–735 的页面，正是 14 §2.2 要消灭的
 * 「页面被压成预览条」；覆盖式面板换来的是页面布局在终端开合前后完全不变。
 * Focus 在 expanded 上仍优先于覆盖：它是用户显式按 ⌘⇧J 要的。
 */
export function resolveMode(o: {
  hasTerms: boolean; dockOpen: boolean; focus: FocusTarget
  size: WindowSize; workspaceWidth: number
  /** 任务视图（#/w）：中间整块给标签工作区，就是现成的 focus 几何（22 设计 §3.1） */
  taskView?: boolean
}): SpaceMode {
  if (o.taskView) return 'focus'
  if (o.size === 'large') return 'page'
  if (!o.hasTerms || !o.dockOpen) return 'page'
  if (o.focus !== 'none') return 'focus'
  if (o.size === 'expanded') return 'overlay'
  return 'focus'
}

export type WorkspaceLayout = {
  /** 当前空间状态 */
  mode: SpaceMode
  /** 终端区是否可见（任务视图、覆盖面板或手机全屏） */
  dockVisible: boolean
  focus: FocusTarget
  navCollapsed: boolean
  /** large 档：有展开的侧栏和右栏这一列；expanded 及以下右栏走覆盖式（见 13 §13.1） */
  large: boolean
  /** 这一档的终端是覆盖式面板：收起时右下角留会话胶囊（13 §13.1） */
  overlayCapable: boolean
  toggleDock: () => void
  setDockOpen: (open: boolean) => void
  setFocus: (target: FocusTarget) => void
  toggleFocus: () => void
  setNavCollapsed: (collapsed: boolean) => void
  /** Inspector 列宽（文件 / Git / Worktree），已按当前几何钳过 */
  inspectorWidth: number
  inspectorBounds: { min: number; max: number }
  setInspectorWidth: (width: number) => void
  resetInspectorWidth: () => void
  /** Inspector 打开时页面还够不够 560——不够就让位 */
  canvasFitsInspector: boolean
  /** Inspector 折起（面板仍挂着，只是这一列宽度归零）；把手上那枚握把切它 */
  inspectorCollapsed: boolean
  /** 展开右栏。只有人的动作该调它（开关钮 / ⌘⇧E·G·F / 对话工具行的 Git） */
  setInspectorCollapsed: (collapsed: boolean) => void
  toggleInspectorCollapsed: () => void
}

/**
 * @param hasTerms 是否有已打开的终端；没有就永远是 Page 态
 * @param taskView 任务视图：不看 hasTerms / dockOpen，直接 focus
 */
export function useWorkspaceLayout(hasTerms: boolean, taskView = false): WorkspaceLayout {
  const layout = useLayout()
  const [prefs] = usePreferences()
  const ws = prefs.workspace

  const [viewport, setViewport] = useState(() => (typeof window === 'undefined' ? 1440 : window.innerWidth))
  useEffect(() => {
    const on = () => setViewport(window.innerWidth)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])

  // 本地态先行、偏好后写：拖拽时每帧都写服务端偏好会打爆 PUT
  const [dockOpen, setDockOpenLocal] = useState(ws.dockOpen)
  const [focus, setFocusLocal] = useState<FocusTarget>(ws.workspaceFocus)
  const [navCollapsed, setNavCollapsedLocal] = useState(ws.navCollapsed)
  const [insWidth, setInsWidthLocal] = useState(ws.inspectorWidth || 0)
  const [inspectorCollapsed, setInspectorCollapsedLocal] = useState(ws.inspectorCollapsed)
  const hydrated = useRef(false)

  /**
   * 偏好从服务端到达后同步一次。
   *
   * 判「到达」必须问 `preferencesLoaded()`，不能拿"effect 跑过一次"充数：偏好是
   * 异步 GET 的，mount 那一跑手里还是默认值，旧写法在那时就把 hydrated 置了位，
   * 真正带着用户宽度的那一跑被 early-return 挡掉——**拖过的分隔条存了却从没读回来**。
   *
   * 用户已经动过手（拖/收/聚焦）之后就不再回填：偏好 GET 与他的操作可能撞在一起，
   * 那时候盖回去等于当着面把他刚拖的位置抹掉。
   */
  useEffect(() => {
    if (hydrated.current || !preferencesLoaded()) return
    hydrated.current = true
    setDockOpenLocal(ws.dockOpen)
    setFocusLocal(ws.workspaceFocus)
    setNavCollapsedLocal(ws.navCollapsed)
    setInsWidthLocal(ws.inspectorWidth || 0)
    setInspectorCollapsedLocal(ws.inspectorCollapsed)
  }, [ws])

  const large = layout.size === 'large'
  const navWidth = large ? (navCollapsed ? NAV_RAIL : NAV_WIDTH) : NAV_RAIL
  const workspaceWidth = Math.max(0, viewport - navWidth)

  const mode = resolveMode({ hasTerms, dockOpen, focus, size: layout.size, workspaceWidth, taskView })

  // Inspector 宽度先钳后用：换到窄窗口不能拿旧大屏的宽度撑破工作区
  const inspectorOpen = useInspectorOpen() && large
  const insBounds = useMemo(() => inspectorBounds({ workspaceWidth }), [workspaceWidth])
  const inspectorWidth = useMemo(() => {
    const wish = insWidth || INSPECTOR_DEFAULT
    return Math.max(insBounds.min, Math.min(insBounds.max, wish))
  }, [insWidth, insBounds])

  const setDockOpen = useCallback((open: boolean) => {
    hydrated.current = true
    setDockOpenLocal(open)
    saveWorkspace({ dockOpen: open })
  }, [])

  const setFocus = useCallback((target: FocusTarget) => {
    hydrated.current = true
    setFocusLocal(target)
    saveWorkspace({ workspaceFocus: target })
  }, [])

  const setInspectorWidth = useCallback((next: number) => {
    hydrated.current = true
    const clamped = Math.round(Math.max(insBounds.min, Math.min(insBounds.max, next)))
    setInsWidthLocal(clamped)
    saveWorkspace({ inspectorWidth: clamped })
  }, [insBounds])

  /**
   * 面板自己报的宽度（文件抽屉是两层折叠，宽度＝两层之和，见 FileBrowser 顶部那段）。
   *
   * **只在它变化的那一刻应用一次**：盯着 inspectorWidth 反复施加的话，用户拖外把手拖出来的
   * 宽度会被立刻弹回去——那根把手就等于拖不动了。面板量到自己被拖宽后会把差值收进对应
   * 那一层并报一个新值，两边由此收敛。
   *
   * 只在真有这一列的档位生效——手机走全屏二级页，没有这一列，不该被它改掉这份偏好。
   */
  const wantInspector = useInspectorWantWidth()
  const appliedWant = useRef(0)
  const appliedMax = useRef(0)
  useEffect(() => {
    if (!large) return
    // 上界变了也要重来一次：报进来的值会被当场钳到当时的上界，钳完就没人再提这茬——
    // 窗口后来变宽，抽屉也永远停在被钳出来的那个宽度。
    if (wantInspector === appliedWant.current && insBounds.max === appliedMax.current) return
    appliedWant.current = wantInspector
    appliedMax.current = insBounds.max
    if (wantInspector > 0) setInspectorWidth(wantInspector)
  }, [wantInspector, insBounds.max, setInspectorWidth, large])

  // 给不了就说一声：面板据此把「Shell 钳的」和「用户拖的」分开（见 inspector.ts）。
  useEffect(() => {
    reportInspectorCap(wantInspector > 0 && inspectorWidth < wantInspector ? inspectorWidth : 0)
  }, [wantInspector, inspectorWidth])

  const setNavCollapsed = useCallback((collapsed: boolean) => {
    hydrated.current = true
    setNavCollapsedLocal(collapsed)
    saveWorkspace({ navCollapsed: collapsed })
  }, [])

  const setInspectorCollapsed = useCallback((collapsed: boolean) => {
    hydrated.current = true
    setInspectorCollapsedLocal(collapsed)
    saveWorkspace({ inspectorCollapsed: collapsed })
  }, [])

  useEffect(() => {
    const reveal = () => setInspectorCollapsed(false)
    window.addEventListener(INSPECTOR_REVEAL_EVENT, reveal)
    return () => window.removeEventListener(INSPECTOR_REVEAL_EVENT, reveal)
  }, [setInspectorCollapsed])

  // Inspector 折起进偏好：第一次进来收着（WORKSPACE_DEFAULTS），自己拉开过就一直开着。
  //
  // 这里**不再**根据「有没有面板占着槽位」自动展开。原来那条（open 为真就展开）等于让这格
  // 偏好不存在——任务页上 InspectorPanels 是常驻 claim 的。改成只看「从无到有」也不行：
  // 槽位是在 mount 之后的 effect 里 claim 的，于是每次进任务页都恰好是一次 false→true，
  // 照样把收起态掰开（实测：点会话进来右栏还是开着）。
  // 展开只由**人**触发：标签条右端那枚开关、⌘⇧E/G/F、对话工具行里的「Git」——
  // 那几处各自调 setInspectorCollapsed(false)，见 App.tsx。

  return {
    mode,
    dockVisible: taskView || (hasTerms && dockOpen),
    focus,
    navCollapsed: large ? navCollapsed : true,
    large,
    overlayCapable: layout.size === 'expanded',
    inspectorWidth,
    inspectorBounds: insBounds,
    setInspectorWidth,
    resetInspectorWidth: () => { hydrated.current = true; setInsWidthLocal(0); saveWorkspace({ inspectorWidth: 0 }) },
    canvasFitsInspector: canvasFitsWith({ workspaceWidth, inspectorWidth }),
    inspectorCollapsed,
    setInspectorCollapsed,
    toggleInspectorCollapsed: () => setInspectorCollapsed(!inspectorCollapsed),
    toggleDock: () => setDockOpen(!dockOpen),
    setDockOpen,
    setFocus,
    toggleFocus: () => setFocus(focus === 'dock' ? 'none' : 'dock'),
    setNavCollapsed,
  }
}
