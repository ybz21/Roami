// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { I18nProvider } from '../i18n'
import { MobileTopBar } from './MobileNavigation'

vi.mock('../components/sessions/SessionLifecyclePanel', () => ({ SessionLifecycleInbox: ({ compact, onOpen }: any) => <button type="button" aria-label="收尾" data-compact={compact} onClick={() => onOpen('pending-session')}>Lifecycle</button> }))
afterEach(cleanup)
it('opens a task without passing the touch event as a project directory', () => {
 localStorage.setItem('ttmux-locale', 'zh-CN')
 const newTask = vi.fn()
 render(<I18nProvider><MobileTopBar tab="projects" go={() => {}} unread={0} notifications={() => {}} newTask={newTask} search={() => {}} actionsHost={() => {}} /></I18nProvider>)
 fireEvent.click(screen.getByRole('button', { name: '新会话' }))
 expect(newTask).toHaveBeenCalledWith()
})

it('keeps background work reachable in the visible phone top bar', () => {
 const openSession = vi.fn()
 render(<I18nProvider><MobileTopBar tab="projects" go={() => {}} unread={0} notifications={() => {}} newTask={() => {}} openSession={openSession} search={() => {}} actionsHost={() => {}} /></I18nProvider>)
 const button = screen.getByRole('button', { name: '收尾' })
 expect(button.closest('.tt-mobile-topbar')).toBeTruthy()
 expect(button.getAttribute('data-compact')).toBe('true')
 fireEvent.click(button)
 expect(openSession).toHaveBeenCalledWith('pending-session')
})
