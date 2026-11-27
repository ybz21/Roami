// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SplitTree from './SplitTree'
import type { WindowLayout } from './native-protocol'

let mockSize: 'compact' | 'medium' | 'expanded' = 'expanded'

vi.mock('../../layout', () => ({
  useLayout: () => ({ size: mockSize, coarse: mockSize === 'compact' }),
}))

vi.mock('../../i18n', () => ({
  useI18n: () => ({
    t: (key: string, args?: { index?: number }) => (args?.index !== undefined ? `${key}:${args.index}` : key),
  }),
}))

afterEach(() => {
  cleanup()
  mockSize = 'expanded'
})

const nestedWindow: WindowLayout = {
  id: 'w1',
  activePaneId: 'p2',
  version: 3,
  layout: {
    id: 's1',
    kind: 'split',
    dir: 'horizontal',
    ratio: 0.5,
    first: { id: 'n1', kind: 'pane', paneId: 'p1' },
    second: {
      id: 's2',
      kind: 'split',
      dir: 'vertical',
      ratio: 0.5,
      first: { id: 'n2', kind: 'pane', paneId: 'p2' },
      second: { id: 'n3', kind: 'pane', paneId: 'p3' },
    },
  },
}

describe('SplitTree', () => {
  it('renders nested horizontal and vertical splits on desktop and supports keyboard resize & pane focus', () => {
    const onFocus = vi.fn()
    const onResize = vi.fn()
    render(
      <SplitTree
        window={nestedWindow}
        onFocusPane={onFocus}
        onResizeSplit={onResize}
        renderPane={(paneId, active) => <div data-testid={`pane-${paneId}`}>{`${paneId}:${active}`}</div>}
      />,
    )

    expect(screen.getByTestId('pane-p1').textContent).toBe('p1:false')
    expect(screen.getByTestId('pane-p2').textContent).toBe('p2:true')
    expect(screen.getByTestId('pane-p3').textContent).toBe('p3:false')

    fireEvent.pointerDown(screen.getByTestId('pane-p1'))
    expect(onFocus).toHaveBeenCalledWith('p1')

    const separators = screen.getAllByRole('separator')
    expect(separators).toHaveLength(2)
    fireEvent.keyDown(separators[0], { key: 'ArrowRight' })
    expect(onResize).toHaveBeenCalledWith('s1', 0.55, 3)
  })

  it('collapses multi-pane splits into active pane + tab switcher on compact screens', () => {
    mockSize = 'compact'
    const onFocus = vi.fn()
    render(
      <SplitTree
        window={nestedWindow}
        onFocusPane={onFocus}
        renderPane={(paneId) => <div data-testid={`pane-${paneId}`}>{paneId}</div>}
      />,
    )

    expect(screen.queryByTestId('pane-p1')).toBeNull()
    expect(screen.getByTestId('pane-p2')).toBeTruthy()
    expect(screen.queryByTestId('pane-p3')).toBeNull()

    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(3)
    fireEvent.click(tabs[2])
    expect(onFocus).toHaveBeenCalledWith('p3')
  })
})
