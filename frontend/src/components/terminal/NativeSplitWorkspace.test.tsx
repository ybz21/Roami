// @vitest-environment jsdom
import { cleanup, fireEvent, render } from '@testing-library/react'
import { forwardRef, useImperativeHandle } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import NativeSplitWorkspace from './NativeSplitWorkspace'

afterEach(() => cleanup())

vi.mock('../../layout', () => ({
  useLayout: () => ({ size: 'wide', pointer: 'fine', phone: false, coarse: false, keyboard: 0 }),
}))

const termCalls: Array<{ paneId?: string; selectAll?: boolean }> = []

vi.mock('./Terminal', () => ({
  default: forwardRef(function MockTerm(props: any, ref: any) {
    useImperativeHandle(ref, () => ({
      send: vi.fn(),
      fit: vi.fn(),
      copy: () => false,
      selection: () => '',
      selectAll: () => termCalls.push({ paneId: props.paneId, selectAll: true }),
      clearSelection: vi.fn(),
      focus: vi.fn(),
      reconnect: vi.fn(),
      scroll: vi.fn(),
      toBottom: vi.fn(),
      selectPaneAt: vi.fn(),
      paneScreenRect: () => null,
      containerRect: () => ({ x: 10, y: 20, width: 400, height: 300 }),
      gridSize: () => ({ cols: 80, rows: 24 }),
      redraw: vi.fn(),
      beginVisualHandoff: vi.fn(),
    }))
    return <div data-testid={`mock-term-${props.paneId || 'single'}`} data-focused={String(!!props.focused)} />
  }),
}))

describe('NativeSplitWorkspace', () => {
  it('mounts independent Terminal instances per pane and shows window tabs when multiple windows exist', () => {
    const onFocusPane = vi.fn()
    const onSelectWindow = vi.fn()
    const onNewWindow = vi.fn()

    const { getByTestId, getByRole, getAllByRole } = render(
      <I18nProvider>
        <NativeSplitWorkspace
          name="dev"
          fontSize={13}
          active
          onFocusPane={onFocusPane}
          onSelectWindow={onSelectWindow}
          onNewWindow={onNewWindow}
          layoutState={{
            backend: 'native',
            activeWindowId: 'w-1',
            activePaneId: 'p-1',
            panesInWindow: 2,
            windows: [
              {
                id: 'w-1',
                index: 1,
                name: 'main',
                active: true,
                panes: 2,
                activePaneId: 'p-1',
                version: 2,
                layout: {
                  id: 's-1',
                  kind: 'split',
                  dir: 'horizontal',
                  ratio: 0.5,
                  first: { id: 'n-1', kind: 'pane', paneId: 'p-1' },
                  second: { id: 'n-2', kind: 'pane', paneId: 'p-2' },
                },
              },
              {
                id: 'w-2',
                index: 2,
                name: 'logs',
                active: false,
                panes: 1,
                activePaneId: 'p-3',
                version: 1,
                layout: { id: 'n-3', kind: 'pane', paneId: 'p-3' },
              },
            ],
          }}
        />
      </I18nProvider>,
    )

    expect(getByTestId('mock-term-p-1').getAttribute('data-focused')).toBe('true')
    expect(getByTestId('mock-term-p-2').getAttribute('data-focused')).toBe('false')

    const tabs = getAllByRole('tab')
    expect(tabs).toHaveLength(2)
    fireEvent.click(tabs[1])
    expect(onSelectWindow).toHaveBeenCalledWith('w-2')

    fireEvent.pointerDown(getByTestId('mock-term-p-2').parentElement!.parentElement!)
    expect(onFocusPane).toHaveBeenCalledWith('w-1', 'p-2')

    const addBtn = getByRole('button', { name: /New window|新建窗口/ })
    fireEvent.click(addBtn)
    expect(onNewWindow).toHaveBeenCalledTimes(1)
  })

  it('hides window strip when only a single window exists', () => {
    const { queryAllByRole, getByTestId } = render(
      <I18nProvider>
        <NativeSplitWorkspace
          name="dev"
          fontSize={13}
          active
          layoutState={{
            backend: 'native',
            activeWindowId: 'w-1',
            activePaneId: 'p-1',
            panesInWindow: 1,
            windows: [
              {
                id: 'w-1',
                index: 1,
                name: 'main',
                active: true,
                panes: 1,
                activePaneId: 'p-1',
                version: 1,
                layout: { id: 'n-1', kind: 'pane', paneId: 'p-1' },
              },
            ],
          }}
        />
      </I18nProvider>,
    )

    expect(getByTestId('mock-term-p-1')).toBeTruthy()
    expect(queryAllByRole('tab')).toHaveLength(0)
  })
})
