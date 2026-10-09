// 工作区容器：Canvas ｜ Dock ｜ Inspector 的三种几何（14 设计 §4.1 / 13 §13.1 / 22 D1）。
//
// **一个组件管三态，是为了让终端永远不换挂载点。**把不同态分成不同的 JSX 树，每换一次态
// React 都在同一位置看到不同的组件类型 → 卸载重建 → 终端连接跟着断一次。现在 {canvas} 和
// {dock} 在三态里都是同一个位置，变的只有它们的样式。
//
//   page     Canvas 铺满，Dock 宽度 0（仍挂载）
//   overlay  Canvas 铺满不动，Dock 从右侧覆盖 480 + 遮罩（expanded 档，905–1279）
//   focus    Canvas 归零，Dock 铺满（任务视图；expanded 档上是用户显式 ⌘⇧J）
//
// 14 稿的 split（页面 ｜ 拖拽分隔条 ｜ 终端）已作废（22 D1）：终端不再和页面抢宽度，
// 分隔条、引导线、拖过头落 Focus 那套都不在了。overlay 的关键是 Dock **脱离文档流**：
// 终端开合前后 Canvas 宽度一模一样，概览的容器查询不会因为开个终端就跳列。
import { type CSSProperties, type ReactNode } from 'react'
import { useI18n } from '../../i18n'
import { OVERLAY_DOCK, type SpaceMode } from './useWorkspaceLayout'
import { useInspectorOpen } from './inspector'
import { InspectorColumn } from './InspectorColumn'

export function Workspace({
  mode, canvas, dock, onDismiss, capsule,
  inspectorWidth, inspectorBounds, inspectorOverlay, canvasFitsInspector, onInspectorResize, onInspectorReset,
  inspectorCollapsed, onToggleInspector,
}: {
  mode: SpaceMode
  canvas: ReactNode
  dock: ReactNode
  /** 覆盖态点遮罩收起 */
  onDismiss: () => void
  /** 覆盖态收起时右下角的会话胶囊（13 §13.1）；其余档传 null */
  capsule?: ReactNode
  /** Inspector（文件 / Git / Worktree）列宽与区间 */
  inspectorWidth: number
  inspectorBounds: { min: number; max: number }
  /** expanded 档：Inspector 也走覆盖式（与 Dock 同语义） */
  inspectorOverlay: boolean
  /** Inspector 打开后 Canvas 还够不够 560：不够就让位 */
  canvasFitsInspector: boolean
  onInspectorResize: (width: number) => void
  onInspectorReset: () => void
  inspectorCollapsed: boolean
  onToggleInspector: () => void
}) {
  const { t } = useI18n()
  const focus = mode === 'focus'
  const overlay = mode === 'overlay'

  // Inspector 占用与否由槽位登记决定（面板自己 portal 进来），Shell 只管留不留这一列
  const insInline = useInspectorOpen() && !inspectorOverlay
  // 三列摆不下时让 Canvas（图纸 §三：让页面，不让终端）
  const canvasHidden = focus || (insInline && !canvasFitsInspector)

  const dockStyle: CSSProperties = overlay
    ? {
        // 脱离文档流：Canvas 宽度不受影响，这是覆盖式的全部意义
        position: 'absolute', top: 0, right: 0, bottom: 0,
        width: `min(${OVERLAY_DOCK}px, 100%)`,
        zIndex: 'var(--z-sheet)' as unknown as number,
        boxShadow: '-12px 0 32px rgba(1,4,9,.45)',
        borderLeft: '1px solid var(--border-subtle)',
        display: 'flex', flexDirection: 'column', minWidth: 0,
        background: 'var(--bg-term)',
        animation: 'ttDockIn .2s cubic-bezier(.2,.85,.3,1)',
      }
    : {
        // clip：page 态下这一列宽 0 但终端仍挂着，hidden 会让里面的 autoFocus 把祖先滚出屏幕
        flex: focus ? '1 1 auto' : '0 0 0px', width: focus ? undefined : 0,
        minWidth: 0, height: '100%', minHeight: 0, overflow: 'clip',
        display: 'flex', flexDirection: 'column',
        background: 'var(--bg-term)',
      }

  return (
    // 这里**不能**写 height:100dvh：100dvh 会让整列比可视区高出一个顶栏，最底下那条快捷键条只露得出几像素。
    // 跟着 Layout 的列走 flex:1 即可。
    <div style={{ position: 'relative', display: 'flex', minHeight: 0, minWidth: 0, flex: 1 }}>
      <div style={{
        flex: canvasHidden ? '0 0 0px' : '1 1 auto', width: canvasHidden ? 0 : undefined,
        minWidth: 0, height: '100%', minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column',
      }}>
        {canvas}
      </div>

      {/* 遮罩只盖 Canvas，不盖导航轨——「上下文不消失」也适用于覆盖态 */}
      {overlay && <div className="tt-dock-scrim" onClick={onDismiss} aria-hidden="true" />}

      <div style={dockStyle}
        role={overlay ? 'dialog' : undefined}
        aria-label={overlay ? t('workspace.terminalPanel') : undefined}>
        {dock}
      </div>

      {/* Inspector：文件 / Git / Worktree 这一列（图纸 panels-desktop.html）。它自带 rail 与拖拽。 */}
      <InspectorColumn width={inspectorWidth} bounds={inspectorBounds}
        overlay={inspectorOverlay} onResize={onInspectorResize} onReset={onInspectorReset}
        collapsed={inspectorCollapsed} onToggleCollapsed={onToggleInspector} />

      {capsule}
    </div>
  )
}

/**
 * 会话胶囊（13 §13.1）：覆盖式面板收起后，右下角留一枚 50 高的入口，
 * 等价于手机上的会话坞——否则这一档收起面板，终端就"消失"了。
 */
export function SessionCapsule({ label, count, onOpen, title }: {
  label: string; count: number; onOpen: () => void; title: string
}) {
  return (
    <button type="button" className="tt-session-capsule" onClick={onOpen} title={title} aria-label={title}>
      <span className="d" />
      <span className="nm">{label}</span>
      {count > 1 && <span className="n">{count}</span>}
    </button>
  )
}
