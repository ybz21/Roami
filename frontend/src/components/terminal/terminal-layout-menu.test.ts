import { describe, expect, it } from 'vitest'
import { buildTerminalContextMenu, buildTerminalLayoutMenu, parseTerminalLayoutMenuKey } from './terminal-layout-menu'

const t = (key: string, params?: Record<string, string | number>) => {
  if (!params) return key
  return `${key}(${Object.entries(params).map(([k, v]) => `${k}=${v}`).join(',')})`
}

describe('terminal-layout-menu', () => {
  it('keeps single-window single-pane menu minimal without redundant navigation entries', () => {
    const groups = buildTerminalLayoutMenu(t, {
      backend: 'native',
      activeWindowId: 'w-1',
      activePaneId: 'p-1',
      panesInWindow: 1,
      windows: [{ id: 'w-1', index: 1, name: 'main', active: true, panes: 1 }],
    })
    expect(groups).toHaveLength(3)
    expect(groups[0].children.map((c: any) => c.key)).toEqual(['split-right', 'split-down'])
    expect(groups[1].children.map((c: any) => c.key)).toEqual(['close-pane'])
    expect(groups[2].children.map((c: any) => c.key)).toEqual(['new-window'])
  })

  it('lists live windows and pane switching when multiple panes or windows exist', () => {
    const groups = buildTerminalLayoutMenu(t, {
      backend: 'native',
      activeWindowId: 'w-2',
      activePaneId: 'p-3',
      panesInWindow: 2,
      windows: [
        { id: 'w-1', index: 1, name: 'main', active: false, panes: 1 },
        { id: 'w-2', index: 2, name: 'logs', active: true, panes: 2 },
      ],
    })
    expect(groups[1].children.map((c: any) => c.key)).toEqual(['next-pane', 'close-pane'])
    expect(groups[2].children.map((c: any) => c.key).filter(Boolean)).toEqual([
      'select-window:w-1',
      'select-window:w-2',
      'new-window',
      'next-window',
      'prev-window',
      'close-window',
    ])
  })

  it('parses structured menu keys into API action payloads', () => {
    expect(parseTerminalLayoutMenuKey('split-right')).toEqual({ action: 'split-right' })
    expect(parseTerminalLayoutMenuKey('split-down')).toEqual({ action: 'split-down' })
    expect(parseTerminalLayoutMenuKey('select-window:w-2')).toEqual({ action: 'select-window', windowId: 'w-2' })
    expect(parseTerminalLayoutMenuKey('focus-left')).toEqual({ action: 'focus-pane', direction: 'left' })
    expect(parseTerminalLayoutMenuKey('unknown')).toBeNull()
  })

  it('builds a concise flat right-click menu without nested submenus or redundant cancel', () => {
    const items = buildTerminalContextMenu(t, {})
    const keys = items.map((item: any) => item.key).filter(Boolean)
    expect(keys).toEqual([
      'paste',
      'select-all',
      'split-right',
      'split-down',
      'new-window',
      'close-pane',
      'redraw',
      'reconnect',
    ])
    expect(items.some((item: any) => 'children' in item)).toBe(false)
    expect(items.find((item: any) => item.key === 'close-pane')).toMatchObject({ danger: true })
  })
})
