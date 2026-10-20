// Inspector 列：Git / Worktree 在桌面档的容身之处（图纸 14-desktop-workspace/panels-desktop.html）。
//
// 它是 Shell 的第三列，不是浮层——浮层只会「盖」，不会「让」：实测 1440 上会话页
// 开 Git，终端从 605 被盖到只剩 185，而左边 603 的页面全程没人看。
//
// 单独成组件是因为有终端和没终端走的是**两棵不同的树**（App 里 `terms.length > 0`
// 才进 Workspace），这一列两边都要有。它自带拖拽与引导线，与 Dock 那条 rail 同款：
// 拖动期间只移动引导线，pointerup 才提交一次宽度（#139：每帧改宽会让终端反复
// fit → SIGWINCH → 整屏重排，肉眼就是闪屏）。
import { useCallback, useRef } from 'react'
import { useI18n } from '../../i18n'
import { PointerResizeShield, usePointerResize } from '../mirror/PointerResize'
import { setInspectorSlot, useInspectorOpen } from './inspector'
import { RailControls, RAIL_STEP, isGripEvent, isStepEvent } from './RailGrip'

export function InspectorColumn({ width, bounds, overlay, onResize, onReset, collapsed, onToggleCollapsed }: {
  width: number
  bounds: { min: number; max: number }
  /** expanded 档：与 Dock 同语义的覆盖式（这一档没有三列的空间） */
  overlay: boolean
  onResize: (width: number) => void
  onReset: () => void
  /** 折起：面板仍挂着（滚动位置、展开态都留着），只是这一列宽度归零 */
  collapsed: boolean
  onToggleCollapsed: () => void
}) {
  const { t } = useI18n()
  const { active, start } = usePointerResize()
  const railRef = useRef<HTMLDivElement>(null)
  const guideRef = useRef<HTMLDivElement>(null)
  const pending = useRef<number | null>(null)
  const open = useInspectorOpen()
  const inline = open && !overlay && !collapsed
  // 折起时把手还在（它是回程的唯一入口），覆盖态没有列可折，也就没有把手
  const rail = open && !overlay

  const clamp = useCallback(
    (w: number) => Math.round(Math.max(bounds.min, Math.min(bounds.max, w))),
    [bounds],
  )

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const rail = railRef.current
    const guide = guideRef.current
    if (!rail || isStepEvent(e)) return
    // 按在握把上没挪动 = 点击（收起/展开）；挪了才是拖宽——握把不挡拖
    const onGrip = isGripEvent(e)
    let moved = false
    const startX = e.clientX
    const startWidth = width
    const railCenter = rail.getBoundingClientRect().left + rail.offsetWidth / 2
    if (guide) { guide.style.display = 'block'; guide.style.left = `${railCenter}px` }
    start(e, {
      onMove: (ev) => {
        if (Math.abs(ev.clientX - startX) > 3) moved = true
        // 这一列贴右缘：往左拖 = 变宽，所以是减
        const next = clamp(startWidth - (ev.clientX - startX))
        pending.current = next
        if (guide) guide.style.left = `${railCenter - (next - startWidth)}px`
      },
      onEnd: () => {
        if (guide) guide.style.display = 'none'
        const next = pending.current
        pending.current = null
        if (onGrip && !moved) { onToggleCollapsed(); return }
        if (next != null) onResize(next)
      },
    })
  }, [width, clamp, onResize, start, onToggleCollapsed])

  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') onResize(clamp(width + 16))
    else if (e.key === 'ArrowRight') onResize(clamp(width - 16))
    else if (e.key === 'Home') onResize(bounds.min)
    else if (e.key === 'End') onResize(bounds.max)
    else return
    e.preventDefault()
  }, [width, bounds, clamp, onResize])

  return (
    <>
      {rail && (
        <div
          ref={railRef}
          role="separator"
          aria-orientation="vertical"
          aria-label={t('workspace.resizeInspector')}
          aria-valuemin={bounds.min}
          aria-valuemax={bounds.max}
          aria-valuenow={inline ? width : 0}
          tabIndex={0}
          onPointerDown={inline ? onPointerDown : undefined}
          onDoubleClick={inline ? onReset : undefined}
          onKeyDown={inline ? onKeyDown : undefined}
          className={`tt-split-rail${inline ? '' : ' collapsed'}`}
        >
          <RailControls collapsed={!inline} side="right" onToggle={onToggleCollapsed}
            label={inline ? t('workspace.collapsePanel') : t('workspace.expandPanel')}
            onStep={(dir) => onResize(clamp(width - dir * RAIL_STEP))}
            stepLabels={{ minus: t('workspace.widenPanel'), plus: t('workspace.narrowPanel') }} />
        </div>
      )}
      {open && overlay && <div className="tt-dock-scrim" aria-hidden="true" />}
      {/* 槽位 DOM 常驻：面板要 portal 进来，挂载点不能随开合出现/消失 */}
      <div
        ref={setInspectorSlot}
        data-inspector-slot
        style={open && overlay ? {
          containerType: 'inline-size', containerName: 'inspector',
          position: 'absolute', top: 0, right: 0, bottom: 0,
          width: `min(${width}px, 100%)`,
          zIndex: 'var(--z-sheet)' as unknown as number,
          boxShadow: '-12px 0 32px rgba(1,4,9,.45)',
          borderLeft: '1px solid var(--border-subtle)',
          display: 'flex', flexDirection: 'column', minWidth: 0,
          background: 'var(--bg-base)',
          animation: 'ttDockIn .2s cubic-bezier(.2,.85,.3,1)',
        } : {
          // 面板内部按**这一列的宽度**分栏（Git 的「列表 ｜ diff」）：容器查询要挂在这里，
          // 挂在面板自己身上不生效——容器查询只作用于后代
          containerType: 'inline-size', containerName: 'inspector',
          flex: inline ? `0 0 ${width}px` : '0 0 0px',
          width: inline ? width : 0,
          minWidth: 0, height: '100%', minHeight: 0, overflow: 'hidden',
          display: 'flex', flexDirection: 'column',
          background: 'var(--bg-base)',
          borderLeft: inline ? '1px solid var(--border-subtle)' : undefined,
          transition: active ? 'none' : 'flex-basis .2s, width .2s',
        }}
      />
      <div ref={guideRef} data-dock-resize-guide aria-hidden="true" style={{
        display: 'none', position: 'fixed', top: 0, bottom: 0, width: 2,
        zIndex: 1000, pointerEvents: 'none',
      }} className="tt-dock-guide" />
      <PointerResizeShield active={active} />
    </>
  )
}
