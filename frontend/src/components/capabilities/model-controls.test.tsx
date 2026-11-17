// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Button, Dropdown, Popconfirm } from './model-controls'
import { installRadixTestEvents } from '../ui/radix-test-events'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
beforeEach(() => {
 installRadixTestEvents()
 class Pointer extends MouseEvent { pointerType: string; constructor(type: string, init: PointerEventInit) { super(type, init); this.pointerType = init.pointerType || 'mouse' } }
 vi.stubGlobal('PointerEvent', Pointer)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('defers touch menus until click and leaves scrolling unblocked after a cancelled gesture', async () => {
 const onClick = vi.fn()
 render(<Dropdown menu={{ items: [{ key: 'source', label: 'Source' }], onClick }}><Button>Organize</Button></Dropdown>)
 const trigger = screen.getByRole('button', { name: 'Organize' })
 fireEvent.pointerDown(trigger, { pointerType: 'touch', button: 0 })
 expect(screen.queryByRole('menu')).toBeNull()
 fireEvent.pointerCancel(trigger, { pointerType: 'touch' })
 expect(document.body.style.pointerEvents).not.toBe('none')
 fireEvent.pointerDown(trigger, { pointerType: 'touch', button: 0 })
 fireEvent.click(trigger)
 fireEvent.click(await screen.findByRole('menuitem', { name: 'Source' }))
 expect(onClick).toHaveBeenCalledWith({ key: 'source' })
 await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
 expect(document.body.style.pointerEvents).not.toBe('none')
})
it('keeps failed confirmations visible with a usable recovery action', async () => {
 render(<Popconfirm title="Delete model" onConfirm={async () => false}><Button>Delete</Button></Popconfirm>)
 fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
 fireEvent.click(await screen.findByRole('button', { name: 'common.confirm' }))
 expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'orchestration.actionFailed')
 expect(screen.getByRole('alertdialog')).toBeTruthy()
 fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
 await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
})
