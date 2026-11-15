// @vitest-environment jsdom
import { createRef } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import SessionResourceMenu from './SessionResourceMenu'
import type { FileTab } from './term-tabs-store'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, args?: { name?: string }) => key + (args?.name || '') }) }))
afterEach(cleanup)
const file: FileTab = { path: '/repo/plan.md', task: '/repo', mode: 'source', preview: false }
function setup(files: FileTab[], onCloseFile = vi.fn()) {
  const sessionButton = createRef<HTMLButtonElement>(), onSession = vi.fn(), onFile = vi.fn()
  const view = (files: FileTab[]) => <><button ref={sessionButton}>Session</button><SessionResourceMenu session="alpha" label="Alpha" icon={null} files={files} active activeFile={file.path} dirtyFiles={new Set()} sessionButton={sessionButton} onSession={onSession} onFile={onFile} onCloseFile={onCloseFile}/></>
  return { ...render(view(files)), view, onSession, onFile, onCloseFile, sessionButton }
}
it('does not render a menu trigger until a file is open, and browsing the menu does not activate the session', async () => {
  const result = setup([])
  expect(screen.queryByRole('button', { name: 'tabs.sessionResourcesAlpha' })).toBeNull()
  result.rerender(result.view([file]))
  fireEvent.click(screen.getByRole('button', { name: 'tabs.sessionResourcesAlpha' }))
  const item = await screen.findByRole('menuitemradio', { name: /plan.md/ })
  expect(item.classList.contains('ant-dropdown-menu-item-selected')).toBe(true)
  expect(item.getAttribute('aria-checked')).toBe('true')
  expect(result.onSession).not.toHaveBeenCalled()
  fireEvent.click(item)
  expect(result.onFile).toHaveBeenCalledWith(file.path)
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
})
it('closes the last file without activating it and restores focus to the session when the arrow disappears', async () => {
  const result = setup([file])
  fireEvent.click(screen.getByRole('button', { name: 'tabs.sessionResourcesAlpha' }))
  fireEvent.click(await screen.findByRole('button', { name: 'tabs.closeFileplan.md' }))
  expect(result.onCloseFile).toHaveBeenCalledWith(file.path)
  expect(result.onFile).not.toHaveBeenCalled()
  result.rerender(result.view([]))
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
  expect(screen.queryByRole('button', { name: 'tabs.sessionResourcesAlpha' })).toBeNull()
  expect(document.activeElement).toBe(result.sessionButton.current)
})
it('distinguishes duplicate basenames and escapes back to the menu trigger', async () => {
  setup([file, { ...file, path: '/repo/other/plan.md' }])
  const trigger = screen.getByRole('button', { name: 'tabs.sessionResourcesAlpha' })
  fireEvent.click(trigger)
  expect(await screen.findByText('/repo/other/plan.md')).toBeTruthy()
  expect(screen.getByText('/repo/plan.md')).toBeTruthy()
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
  expect(document.activeElement).toBe(trigger)
})
