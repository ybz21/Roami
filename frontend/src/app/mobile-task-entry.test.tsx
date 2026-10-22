// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { I18nProvider } from '../i18n'
import { MobileTopBar } from './MobileNavigation'

afterEach(cleanup)
it('opens a task without passing the touch event as a project directory', () => {
 localStorage.setItem('ttmux-locale', 'zh-CN')
 const newTask = vi.fn()
 render(<I18nProvider><MobileTopBar tab="projects" go={() => {}} unread={0} notifications={() => {}} newTask={newTask} search={() => {}} actionsHost={() => {}} /></I18nProvider>)
 fireEvent.click(screen.getByRole('button', { name: '新会话' }))
 expect(newTask).toHaveBeenCalledWith()
})
