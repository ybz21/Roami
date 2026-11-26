// Structured terminal layout menu (split / pane / window) backed by REST APIs instead of
// raw Ctrl+b keystroke injection, working identically across native roami-sessiond and tmux sessions.
export interface SessionWindowItem {
  id: string
  index: number
  name: string
  active: boolean
  panes: number
}

export interface SessionWindowsState {
  backend?: string
  activeWindowId?: string
  activePaneId?: string
  panesInWindow?: number
  windows: SessionWindowItem[]
}

export type TerminalLayoutAction =
  | { action: 'split-right' }
  | { action: 'split-down' }
  | { action: 'next-pane' }
  | { action: 'focus-pane'; direction: 'up' | 'down' | 'left' | 'right' }
  | { action: 'close-pane' }
  | { action: 'new-window' }
  | { action: 'next-window' }
  | { action: 'prev-window' }
  | { action: 'select-window'; windowId: string }
  | { action: 'close-window'; windowId?: string }

const SELECT_WINDOW_PREFIX = 'select-window:'

export function parseTerminalLayoutMenuKey(key: string): TerminalLayoutAction | null {
  if (key.startsWith(SELECT_WINDOW_PREFIX)) {
    const windowId = key.slice(SELECT_WINDOW_PREFIX.length)
    return windowId ? { action: 'select-window', windowId } : null
  }
  switch (key) {
    case 'split-right':
      return { action: 'split-right' }
    case 'split-down':
      return { action: 'split-down' }
    case 'next-pane':
      return { action: 'next-pane' }
    case 'focus-up':
      return { action: 'focus-pane', direction: 'up' }
    case 'focus-down':
      return { action: 'focus-pane', direction: 'down' }
    case 'focus-left':
      return { action: 'focus-pane', direction: 'left' }
    case 'focus-right':
      return { action: 'focus-pane', direction: 'right' }
    case 'close-pane':
      return { action: 'close-pane' }
    case 'new-window':
      return { action: 'new-window' }
    case 'next-window':
      return { action: 'next-window' }
    case 'prev-window':
      return { action: 'prev-window' }
    case 'close-window':
      return { action: 'close-window' }
    default:
      return null
  }
}

export function buildTerminalLayoutMenu(
  t: (key: string, params?: Record<string, string | number>) => string,
  state?: SessionWindowsState | null,
) {
  const windows = state?.windows ?? []
  const multiWindow = windows.length > 1
  const multiPane = (state?.panesInWindow ?? 1) > 1

  const windowChildren: any[] = []
  if (multiWindow) {
    for (const w of windows) {
      const label = w.active
        ? t('terminal.menu.windowItemActive', { index: w.index, name: w.name })
        : t('terminal.menu.windowItem', { index: w.index, name: w.name })
      windowChildren.push({ key: SELECT_WINDOW_PREFIX + w.id, label })
    }
    windowChildren.push({ type: 'divider' })
  }
  windowChildren.push({ key: 'new-window', label: t('terminal.menu.newWindow') })
  if (multiWindow) {
    windowChildren.push(
      { key: 'next-window', label: t('terminal.menu.nextWindow') },
      { key: 'prev-window', label: t('terminal.menu.prevWindow') },
      { key: 'close-window', label: t('terminal.menu.closeWindow'), danger: true },
    )
  }

  const paneChildren: any[] = []
  if (multiPane) {
    paneChildren.push({ key: 'next-pane', label: t('terminal.menu.nextPane') })
  }
  paneChildren.push({ key: 'close-pane', label: t('terminal.menu.closePane'), danger: true })

  return [
    {
      type: 'group',
      label: t('terminal.menu.split'),
      children: [
        { key: 'split-right', label: t('terminal.menu.splitRight') },
        { key: 'split-down', label: t('terminal.menu.splitDown') },
      ],
    },
    {
      type: 'group',
      label: t('terminal.menu.pane'),
      children: paneChildren,
    },
    {
      type: 'group',
      label: t('terminal.menu.window'),
      children: windowChildren,
    },
  ]
}
