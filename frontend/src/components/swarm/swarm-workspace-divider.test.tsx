// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import SwarmWorkspaceDivider from './SwarmWorkspaceDivider'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)
function pointer(element: Element | Window, type: string, x: number) {
  const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x })
  Object.defineProperty(event, 'pointerId', { value: 7 })
  fireEvent(element, event)
}
it('commits a bounded drag once after release and removes the input shield', () => {
  const resize = vi.fn()
  render(<SwarmWorkspaceDivider width={500} min={300} max={700} onResize={resize} />)
  const divider = screen.getByRole('separator')
  pointer(divider, 'pointerdown', 1000)
  pointer(window, 'pointermove', 100)
  expect(resize).not.toHaveBeenCalled()
  expect(document.querySelector('[data-pointer-resize-shield]')).toBeTruthy()
  pointer(window, 'pointerup', 100)
  expect(resize).toHaveBeenCalledTimes(1)
  expect(resize).toHaveBeenCalledWith(700)
  expect(document.querySelector('[data-pointer-resize-shield]')).toBeNull()
})
it('provides keyboard width adjustment within the same bounds', () => {
  const resize = vi.fn()
  render(<SwarmWorkspaceDivider width={500} min={300} max={700} onResize={resize} />)
  const divider = screen.getByRole('separator')
  for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) fireEvent.keyDown(divider, { key })
  expect(resize.mock.calls.map(call => call[0])).toEqual([516, 484, 300, 700])
})
