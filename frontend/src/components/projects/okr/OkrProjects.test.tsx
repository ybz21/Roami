// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OkrProjects from './OkrProjects'
import { NAV_WORKSPACE, loadPageTabs, mobileNavRoot } from '../../../app/navigation'
const api = vi.hoisted(() => vi.fn())
vi.mock('../../../api', () => ({ api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string) => key }) }))
const objective = { projectId: 'first project', projectName: 'Promotion', objective: 'Grow adoption', startDate: '2026-11-01', endDate: '2026-11-30', updatedAt: '', revision: 1, keyResults: [] }
const projects = [{ key: 'first project', name: 'Promotion', dir: '/promotion' }, { key: 'second', name: 'Repository without OKR', dir: '/repo' }]
beforeEach(() => { api.mockReset(); api.mockResolvedValue({ data: [objective] }); window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
afterEach(() => { cleanup(); localStorage.clear() })

it('lists only explicitly saved objectives and never populates OKRs for every project', async () => {
  history.replaceState(null, '', '#/okr?node=remote')
  render(<OkrProjects projects={projects} loaded error={false} retry={vi.fn()} />)
  expect((await screen.findByRole('link', { name: /Grow adoption/ })).getAttribute('href')).toBe('#/okr/first%20project?node=remote')
  expect(screen.queryByText('Repository without OKR')).toBeNull()
  expect(api.mock.calls.every(call => call[0] === 'GET' && call[1] === '/okr')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: /okr.create/ }))
  expect(await screen.findByRole('combobox', { name: 'okr.selectProject' })).toBeTruthy()
  expect(api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})
it('shows an empty OKR state instead of listing projects with no goal', async () => {
  api.mockResolvedValue({ data: [] })
  render(<OkrProjects projects={projects} loaded error={false} retry={vi.fn()} />)
  expect(await screen.findByText('okr.noObjectives')).toBeTruthy()
  expect(screen.queryAllByRole('link')).toHaveLength(0)
})
it('keeps the last successful objective list when a visible refresh fails', async () => {
  render(<OkrProjects projects={projects} loaded error={false} retry={vi.fn()} />)
  await screen.findByRole('link', { name: /Grow adoption/ })
  api.mockRejectedValue(new Error('offline'))
  fireEvent(document, new Event('visibilitychange'))
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  expect(screen.getByRole('link', { name: /Grow adoption/ })).toBeTruthy()
})
it('retains the OKR workspace tab and places phone OKR routes under Projects', () => {
  expect(NAV_WORKSPACE).toContain('okr')
  localStorage.setItem('roam.pageTabs', JSON.stringify(['home', 'okr']))
  expect(loadPageTabs()).toEqual(['home', 'okr'])
  expect(mobileNavRoot('okr', 'okr/project')).toBe('projects')
})
