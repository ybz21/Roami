// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { FullscreenAction, LogoutAction } from './account-actions'

const confirm = vi.hoisted(() => vi.fn())
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', () => ({ App: { useApp: () => ({ modal: { confirm } }) }, Button: ({ children, icon: _icon, danger: _danger, ...props }: any) => <button {...props}>{children}</button> }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('keeps the mobile fullscreen controller and reflects its state', () => {
  const toggle = vi.fn()
  const view = render(<FullscreenAction controller={{ active: true, toggle }} />)
  fireEvent.click(screen.getByRole('button', { name: 'common.exitFullscreen' }))
  expect(toggle).toHaveBeenCalledOnce()
  view.rerender(<FullscreenAction controller={{ active: false, toggle }} />)
  expect(screen.getByRole('button', { name: 'common.fullscreen' })).toBeTruthy()
})

it('does not log out until the existing confirmation is accepted', () => {
  const onLogout = vi.fn()
  render(<LogoutAction onLogout={onLogout} />)
  fireEvent.click(screen.getByRole('button', { name: 'common.logout' }))
  expect(onLogout).not.toHaveBeenCalled()
  expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ title: 'common.logoutConfirm', onOk: onLogout }))
  confirm.mock.calls[0][0].onOk()
  expect(onLogout).toHaveBeenCalledOnce()
})
