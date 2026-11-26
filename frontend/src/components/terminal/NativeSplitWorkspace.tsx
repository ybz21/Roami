import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { PlusIcon } from '../../icons'
import Term, { type TermHandle, type TermStatus } from './Terminal'
import SplitTree from './SplitTree'
import { collectPaneIds } from './native-protocol'
import type { WindowLayout } from './native-protocol'
import type { SessionWindowsState } from './terminal-layout-menu'
import './NativeSplitWorkspace.css'

const MAX_WEBGL_PANES = 3

export interface NativeSplitWorkspaceHandle extends TermHandle {
  activePaneId: () => string | undefined
  sendToPane: (paneId: string, data: string, keepFocus?: boolean) => boolean
  paneContainerRect: (paneId?: string) => { x: number; y: number; width: number; height: number } | null
}

export interface NativeSplitWorkspaceProps {
  name: string
  fontSize: number
  active: boolean
  layoutState?: SessionWindowsState | null
  onLayoutRefresh?: () => void
  onFocusPane?: (windowId: string, paneId: string) => void
  onResizeSplit?: (windowId: string, nodeId: string, ratio: number, expectedVersion: number) => void
  onSelectWindow?: (windowId: string) => void
  onNewWindow?: () => void
  onStatus?: (s: TermStatus) => void
  onRevived?: (from: string, to: string) => void
  onContextMenu?: (e: { x: number; y: number; selection: string; paneId?: string }) => void
  onSelectionMenu?: (e: { x: number; y: number; selection: string; paneId?: string }) => void
  onPaste?: (paneId?: string) => void
  onImagePaste?: (files: File[], paneId?: string) => void
}

// Product-level split terminal workspace: each native pane is mounted as an independent
// <Term paneId={...} /> instance inside SplitTree so selection, multi-line copy, select-all,
// and scrollback remain cleanly isolated per pane. Legacy tmux sessions render a single <Term>.
const NativeSplitWorkspace = forwardRef<NativeSplitWorkspaceHandle, NativeSplitWorkspaceProps>(
  function NativeSplitWorkspace(
    {
      name,
      fontSize,
      active,
      layoutState,
      onLayoutRefresh,
      onFocusPane,
      onResizeSplit,
      onSelectWindow,
      onNewWindow,
      onStatus,
      onRevived,
      onContextMenu,
      onSelectionMenu,
      onPaste,
      onImagePaste,
    },
    ref,
  ) {
    const { t } = useI18n()
    const paneRefs = useRef<Record<string, TermHandle | null>>({})
    const singleRef = useRef<TermHandle | null>(null)
    const layoutDebounceRef = useRef<ReturnType<typeof setTimeout>>()

    const nativeWindow = useMemo<WindowLayout | null>(() => {
      if (layoutState?.backend !== 'native' || !layoutState.windows?.length) return null
      const activeWin =
        layoutState.windows.find((w) => w.id === layoutState.activeWindowId) ||
        layoutState.windows.find((w) => w.active) ||
        layoutState.windows[0]
      if (!activeWin?.layout) return null
      const paneIds = collectPaneIds(activeWin.layout)
      const activePaneId =
        (activeWin.activePaneId && paneIds.includes(activeWin.activePaneId) && activeWin.activePaneId) ||
        (layoutState.activePaneId && paneIds.includes(layoutState.activePaneId) && layoutState.activePaneId) ||
        paneIds[0] ||
        ''
      return {
        id: activeWin.id,
        name: activeWin.name,
        activePaneId,
        version: activeWin.version ?? 1,
        layout: activeWin.layout,
      }
    }, [layoutState])

    const [focusedPaneId, setFocusedPaneId] = useState('')
    const [recentPanes, setRecentPanes] = useState<string[]>([])

    useEffect(() => {
      if (!nativeWindow) return
      const next = nativeWindow.activePaneId
      if (!next) return
      setFocusedPaneId(next)
      setRecentPanes((prev) => [next, ...prev.filter((id) => id !== next)].slice(0, MAX_WEBGL_PANES))
    }, [nativeWindow?.id, nativeWindow?.activePaneId])

    useEffect(() => () => clearTimeout(layoutDebounceRef.current), [])

    const scheduleLayoutRefresh = useCallback(() => {
      if (!onLayoutRefresh) return
      clearTimeout(layoutDebounceRef.current)
      layoutDebounceRef.current = setTimeout(() => {
        onLayoutRefresh()
      }, 60)
    }, [onLayoutRefresh])

    const currentPaneId = nativeWindow
      ? (focusedPaneId && collectPaneIds(nativeWindow.layout).includes(focusedPaneId)
          ? focusedPaneId
          : nativeWindow.activePaneId)
      : undefined

    const targetHandle = () => {
      if (nativeWindow && currentPaneId) {
        return paneRefs.current[currentPaneId] || paneRefs.current[nativeWindow.activePaneId] || null
      }
      return singleRef.current
    }

    const handleFocusPane = useCallback(
      (paneId: string) => {
        if (!nativeWindow || !paneId) return
        setFocusedPaneId(paneId)
        setRecentPanes((prev) => [paneId, ...prev.filter((id) => id !== paneId)].slice(0, MAX_WEBGL_PANES))
        if (paneId !== nativeWindow.activePaneId) {
          onFocusPane?.(nativeWindow.id, paneId)
        }
      },
      [nativeWindow, onFocusPane],
    )

    useImperativeHandle(ref, () => ({
      activePaneId: () => currentPaneId,
      sendToPane: (paneId, data, keepFocus) => {
        const h = paneRefs.current[paneId]
        if (!h) return false
        h.send(data, keepFocus)
        return true
      },
      paneContainerRect: (paneId) => {
        const pid = paneId || currentPaneId
        if (nativeWindow && pid) {
          return paneRefs.current[pid]?.containerRect() ?? null
        }
        return singleRef.current?.containerRect() ?? null
      },
      send: (s, keepFocus) => targetHandle()?.send(s, keepFocus),
      fit: () => {
        if (nativeWindow) {
          for (const pid of collectPaneIds(nativeWindow.layout)) {
            paneRefs.current[pid]?.fit()
          }
          return
        }
        singleRef.current?.fit()
      },
      copy: () => targetHandle()?.copy() ?? false,
      selection: () => targetHandle()?.selection() ?? '',
      selectAll: () => targetHandle()?.selectAll(),
      clearSelection: () => targetHandle()?.clearSelection(),
      focus: () => targetHandle()?.focus(),
      reconnect: () => targetHandle()?.reconnect(),
      scroll: (lines) => targetHandle()?.scroll(lines),
      toBottom: () => targetHandle()?.toBottom(),
      selectPaneAt: (clientX, clientY) => targetHandle()?.selectPaneAt(clientX, clientY),
      paneScreenRect: (pane) => targetHandle()?.paneScreenRect(pane) ?? null,
      containerRect: () => targetHandle()?.containerRect() ?? null,
      gridSize: () => targetHandle()?.gridSize() ?? null,
      redraw: () => targetHandle()?.redraw(),
      beginVisualHandoff: () => {
        if (nativeWindow) {
          for (const pid of collectPaneIds(nativeWindow.layout)) {
            paneRefs.current[pid]?.beginVisualHandoff()
          }
          return
        }
        singleRef.current?.beginVisualHandoff()
      },
    }))

    if (!nativeWindow) {
      return (
        <div className="tt-native-pane-slot">
          <Term
            ref={singleRef}
            name={name}
            fontSize={fontSize}
            active={active}
            onStatus={onStatus}
            onLayoutChange={scheduleLayoutRefresh}
            onRevived={onRevived}
            onContextMenu={(e) => onContextMenu?.(e)}
            onSelectionMenu={(e) => onSelectionMenu?.(e)}
            onPaste={() => onPaste?.()}
            onImagePaste={(files) => onImagePaste?.(files)}
          />
        </div>
      )
    }

    const windows = layoutState?.windows ?? []
    const paneCount = collectPaneIds(nativeWindow.layout).length
    const effectiveWindow: WindowLayout = {
      ...nativeWindow,
      activePaneId: currentPaneId || nativeWindow.activePaneId,
    }

    return (
      <div className="tt-native-split-workspace">
        {windows.length > 1 && (
          <div className="tt-win-strip" role="tablist" aria-label={t('terminal.windowListLabel')}>
            {windows.map((w) => {
              const isCurrent = w.id === nativeWindow.id
              return (
                <button
                  key={w.id}
                  type="button"
                  role="tab"
                  aria-selected={isCurrent}
                  className={`tt-win-tab${isCurrent ? ' active' : ''}`}
                  onClick={() => onSelectWindow?.(w.id)}
                >
                  {t('terminal.menu.windowItem', { index: w.index, name: w.name })}
                </button>
              )
            })}
            <button
              type="button"
              className="tt-win-add"
              aria-label={t('terminal.menu.newWindow')}
              title={t('terminal.menu.newWindow')}
              onClick={() => onNewWindow?.()}
            >
              <PlusIcon size={13} />
            </button>
          </div>
        )}
        <div className="tt-native-split-body">
          <SplitTree
            window={effectiveWindow}
            onFocusPane={handleFocusPane}
            onResizeSplit={(nodeId, ratio, expectedVersion) =>
              onResizeSplit?.(nativeWindow.id, nodeId, ratio, expectedVersion)
            }
            renderPane={(paneId, isFocused) => {
              const preferWebgl = paneCount <= MAX_WEBGL_PANES || isFocused || recentPanes.includes(paneId)
              return (
                <div className="tt-native-pane-slot">
                  <Term
                    key={paneId}
                    ref={(h) => {
                      if (h) paneRefs.current[paneId] = h
                      else delete paneRefs.current[paneId]
                    }}
                    name={name}
                    paneId={paneId}
                    fontSize={fontSize}
                    active={active}
                    focused={active && isFocused}
                    preferWebgl={preferWebgl}
                    onStatus={isFocused ? onStatus : undefined}
                    onLayoutChange={scheduleLayoutRefresh}
                    onRevived={onRevived}
                    onContextMenu={(e) => {
                      handleFocusPane(paneId)
                      onContextMenu?.({ ...e, paneId })
                    }}
                    onSelectionMenu={(e) => {
                      handleFocusPane(paneId)
                      onSelectionMenu?.({ ...e, paneId })
                    }}
                    onPaste={() => {
                      handleFocusPane(paneId)
                      onPaste?.(paneId)
                    }}
                    onImagePaste={(files) => {
                      handleFocusPane(paneId)
                      onImagePaste?.(files, paneId)
                    }}
                  />
                </div>
              )
            }}
          />
        </div>
      </div>
    )
  },
)

export default NativeSplitWorkspace
