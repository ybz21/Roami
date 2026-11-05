// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import SessionHierarchy from './SessionHierarchy'
import SessionLocation from './SessionLocation'

vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (_key: string, values: any) => `由 ${values.parent} 派生` }) }))
afterEach(cleanup)

const renderRow = (s: { label?: string; cwd?: string; branch?: string }) => <button>{s.label}<SessionLocation {...s} /></button>

it('keeps the parent visible before limiting a mixed agent family and preserves separate directories', () => {
  const sessions = [
    { name: 'roami:child', parent: 'codex', label: 'Child', cwd: '/repo/check', branch: 'fix/same' },
    { name: 'loose', label: 'No workspace' },
    { name: 'codex', label: 'Parent', cwd: '/repo/main', branch: 'fix/same' },
  ]
  const view = render(<SessionHierarchy sessions={sessions} limit={2} renderRow={renderRow} />)
  expect(screen.getAllByRole('button').map(button => button.textContent)).toEqual(['Parentfix/same/repo/main', 'Childfix/same/repo/check'])
  expect(view.container.querySelector('[data-depth="1"]')?.textContent).toContain('Child')
  view.rerender(<SessionHierarchy sessions={sessions} renderRow={renderRow} />)
  expect(screen.getByRole('button', { name: 'No workspace' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'No workspace' }).querySelector('.tt-session-location')).toBeNull()
})

it('retains readable ancestry when a filter or worktree group excludes the parent', () => {
  const parent = { name: 'p', label: 'Parent' }, child = { name: 'c', parent: 'p', label: 'Child' }
  render(<SessionHierarchy sessions={[child]} allSessions={[parent, child]} renderRow={renderRow} />)
  expect(screen.getByText('由 Parent 派生')).toBeTruthy()
  expect(screen.getAllByRole('button')).toHaveLength(1)
})
