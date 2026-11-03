// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import OkrProjects from './OkrProjects'
import { NAV_WORKSPACE, loadPageTabs, mobileNavRoot } from '../../../app/navigation'

vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(() => { cleanup(); localStorage.clear() })

it('opens the chosen project under OKR while preserving the current node', () => {
  history.replaceState(null, '', '#/okr?node=remote')
  render(<OkrProjects projects={[{ key: 'first project', name: 'Roami promotion', dir: '/promotion' }, { key: 'second', name: 'Repository', dir: '/repo' }]} loaded error={false} retry={vi.fn()} />)
  expect(screen.getByRole('link', { name: /Roami promotion/ }).getAttribute('href')).toBe('#/okr/first%20project?node=remote')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'repository' } })
  expect(screen.queryByRole('link', { name: /Roami promotion/ })).toBeNull()
  expect(screen.getByRole('link', { name: /Repository/ })).toBeTruthy()
})

it('keeps project choices available when a background catalogue refresh fails', () => {
  const retry = vi.fn()
  render(<OkrProjects projects={[{ key: 'first', name: 'Promotion', dir: '/promotion' }]} loaded error retry={retry} />)
  expect(screen.getByRole('link', { name: /Promotion/ })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'inbox.retry' }))
  expect(retry).toHaveBeenCalledOnce()
})

it('retains the OKR workspace tab and places phone OKR routes under Projects', () => {
  expect(NAV_WORKSPACE).toContain('okr')
  localStorage.setItem('roam.pageTabs', JSON.stringify(['home', 'okr']))
  expect(loadPageTabs()).toEqual(['home', 'okr'])
  expect(mobileNavRoot('okr', 'okr/project')).toBe('projects')
})
