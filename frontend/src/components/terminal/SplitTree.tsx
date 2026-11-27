import { useCallback, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { clampSplitRatio, collectPaneIds } from './native-protocol'
import type { LayoutNode, SplitDir, WindowLayout } from './native-protocol'
import './SplitTree.css'

export interface SplitTreeProps {
  window: WindowLayout
  renderPane: (paneId: string, active: boolean) => ReactNode
  onFocusPane?: (paneId: string) => void
  onResizeSplit?: (nodeId: string, ratio: number, expectedVersion: number) => void
}

interface BranchProps {
  node: LayoutNode
  activePaneId: string
  paneCount: number
  version: number
  renderPane: (paneId: string, active: boolean) => ReactNode
  onFocusPane?: (paneId: string) => void
  onResizeSplit?: (nodeId: string, ratio: number, expectedVersion: number) => void
}

function SplitBranch({
  node,
  activePaneId,
  paneCount,
  version,
  renderPane,
  onFocusPane,
  onResizeSplit,
}: BranchProps) {
  const { t } = useI18n()
  const branchRef = useRef<HTMLDivElement>(null)
  const [liveRatio, setLiveRatio] = useState<number | null>(null)

  const dir: SplitDir = node.dir === 'vertical' ? 'vertical' : 'horizontal'
  const committedRatio = clampSplitRatio(node.ratio ?? 0.5)
  const ratio = liveRatio ?? committedRatio

  const handlePointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (!onResizeSplit || !branchRef.current) return
      e.preventDefault()
      const rect = branchRef.current.getBoundingClientRect()
      const target = e.currentTarget
      target.setPointerCapture?.(e.pointerId)

      let latest = committedRatio
      const compute = (clientX: number, clientY: number) => {
        const span = dir === 'horizontal' ? rect.width : rect.height
        if (span <= 0) return committedRatio
        const offset = dir === 'horizontal' ? clientX - rect.left : clientY - rect.top
        return clampSplitRatio(offset / span)
      }

      const onMove = (ev: globalThis.PointerEvent) => {
        latest = compute(ev.clientX, ev.clientY)
        setLiveRatio(latest)
      }
      const onUp = () => {
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        window.removeEventListener('pointercancel', onUp)
        setLiveRatio(null)
        if (Math.abs(latest - committedRatio) > 0.005) {
          onResizeSplit(node.id, latest, version)
        }
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      window.addEventListener('pointercancel', onUp)
    },
    [committedRatio, dir, node.id, onResizeSplit, version],
  )

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (!onResizeSplit) return
      const step = 0.05
      const dec = dir === 'horizontal' ? 'ArrowLeft' : 'ArrowUp'
      const inc = dir === 'horizontal' ? 'ArrowRight' : 'ArrowDown'
      if (e.key === dec) {
        e.preventDefault()
        onResizeSplit(node.id, clampSplitRatio(committedRatio - step), version)
      } else if (e.key === inc) {
        e.preventDefault()
        onResizeSplit(node.id, clampSplitRatio(committedRatio + step), version)
      }
    },
    [committedRatio, dir, node.id, onResizeSplit, version],
  )

  if (node.kind === 'pane' || !node.first || !node.second) {
    const paneId = node.paneId || ''
    const isActive = paneId === activePaneId
    return (
      <div
        className={`tt-split-pane${isActive && paneCount > 1 ? ' active' : ''}`}
        data-pane-id={paneId}
        onPointerDown={() => {
          if (paneId && paneId !== activePaneId) onFocusPane?.(paneId)
        }}
      >
        {renderPane(paneId, isActive)}
      </div>
    )
  }

  return (
    <div ref={branchRef} className={`tt-split-branch ${dir}`} data-split-id={node.id}>
      <div className="tt-split-slot" style={{ flexGrow: ratio, flexShrink: 1, flexBasis: 0 }}>
        <SplitBranch
          node={node.first}
          activePaneId={activePaneId}
          paneCount={paneCount}
          version={version}
          renderPane={renderPane}
          onFocusPane={onFocusPane}
          onResizeSplit={onResizeSplit}
        />
      </div>
      <div
        role="separator"
        tabIndex={0}
        aria-orientation={dir === 'horizontal' ? 'vertical' : 'horizontal'}
        aria-valuenow={Math.round(ratio * 100)}
        aria-valuemin={15}
        aria-valuemax={85}
        aria-label={t('terminal.splitResize')}
        className={`tt-split-divider ${dir}${liveRatio !== null ? ' dragging' : ''}`}
        onPointerDown={handlePointerDown}
        onKeyDown={handleKeyDown}
      />
      <div className="tt-split-slot" style={{ flexGrow: 1 - ratio, flexShrink: 1, flexBasis: 0 }}>
        <SplitBranch
          node={node.second}
          activePaneId={activePaneId}
          paneCount={paneCount}
          version={version}
          renderPane={renderPane}
          onFocusPane={onFocusPane}
          onResizeSplit={onResizeSplit}
        />
      </div>
    </div>
  )
}

// Renders a binary split tree on desktop, and collapses multi-pane layouts into a
// full-width active pane + top switcher strip on compact mobile screens.
export default function SplitTree({ window: win, renderPane, onFocusPane, onResizeSplit }: SplitTreeProps) {
  const { size } = useLayout()
  const { t } = useI18n()
  const paneIds = collectPaneIds(win.layout)
  const activePaneId = paneIds.includes(win.activePaneId) ? win.activePaneId : paneIds[0] || ''

  if (size === 'compact' && paneIds.length > 1) {
    return (
      <div className="tt-split-root">
        <div className="tt-split-mobile-bar" role="tablist" aria-label={t('terminal.paneSwitcher')}>
          {paneIds.map((pid, idx) => {
            const active = pid === activePaneId
            return (
              <button
                key={pid}
                type="button"
                role="tab"
                aria-selected={active}
                className={`tt-split-mobile-tab${active ? ' active' : ''}`}
                onClick={() => onFocusPane?.(pid)}
              >
                {t('terminal.paneNumber', { index: idx + 1 })}
              </button>
            )
          })}
        </div>
        <div className="tt-split-pane" data-pane-id={activePaneId}>
          {renderPane(activePaneId, true)}
        </div>
      </div>
    )
  }

  return (
    <div className="tt-split-root">
      <SplitBranch
        node={win.layout}
        activePaneId={activePaneId}
        paneCount={paneIds.length}
        version={win.version}
        renderPane={renderPane}
        onFocusPane={onFocusPane}
        onResizeSplit={onResizeSplit}
      />
    </div>
  )
}
