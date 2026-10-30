// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TabContextMenu } from './TabContextMenu'

afterEach(cleanup)

describe('workspace tab context menu', () => {
  it('keeps the menu usable after leaving the tab and scrolling its ancestors', async () => {
    const pin = vi.fn(), select = vi.fn(), menuClick = vi.fn()
    const { container } = render(<div style={{ overflow: 'auto' }}>
      <TabContextMenu menu={{ items: [{ key: 'pin', label: 'Pin', onClick: pin }], onClick: menuClick }}>
        <button onClick={select}>Tab</button>
      </TabContextMenu>
    </div>)
    const tab = screen.getByRole('button', { name: 'Tab' })
    fireEvent.contextMenu(tab)
    const item = await screen.findByRole('menuitem', { name: 'Pin' })
    fireEvent.mouseLeave(tab, { relatedTarget: item })
    fireEvent.scroll(container.firstChild!)
    fireEvent.mouseEnter(item)
    await waitFor(() => expect(screen.getByRole('menuitem', { name: 'Pin' })).toBeTruthy())
    fireEvent.pointerDown(item)
    fireEvent.click(item)
    expect(pin).toHaveBeenCalledOnce()
    expect(menuClick).toHaveBeenCalledOnce()
    expect(select).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
  })

  it('closes on outside press and Escape, and opens on another tab', async () => {
    render(<>
      {['First', 'Second'].map(label => <TabContextMenu key={label}
        menu={{ items: [{ key: 'close', label: `Close ${label}` }] }}>
        <button>{label}</button>
      </TabContextMenu>)}
      <button>Outside</button>
    </>)
    fireEvent.contextMenu(screen.getByText('First'))
    await screen.findByRole('menuitem', { name: 'Close First' })
    fireEvent.contextMenu(screen.getByText('Second'))
    await screen.findByRole('menuitem', { name: 'Close Second' })
    await waitFor(() => expect(screen.queryByRole('menuitem', { name: 'Close First' })).toBeNull())
    fireEvent.keyDown(document, { key: 'Escape', keyCode: 27 })
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
    fireEvent.contextMenu(screen.getByText('First'))
    await screen.findByRole('menu')
    fireEvent.pointerDown(screen.getByText('Outside'))
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
  })
})
