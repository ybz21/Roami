// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { NewProjectModal } from './Projects'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
beforeEach(() => {
  localStorage.clear()
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })
  vi.mocked(api).mockReset().mockResolvedValue({ data: { key: 'project', dir: '/work/repo', git: true, name: 'repo' } } as any)
})
afterEach(() => { cleanup(); location.hash = '' })

it.each([false, true])('keeps local-directory and clone workflows available with inline=%s', async inline => {
  const created = vi.fn()
  render(<App><NewProjectModal open inline={inline} onClose={() => {}} onCreated={created} /></App>)
  expect(screen.getByText('project.sourceLocal')).toBeTruthy()
  fireEvent.click(screen.getByText('project.sourceClone'))
  fireEvent.change(screen.getByPlaceholderText('project.cloneUrlPlaceholder'), { target: { value: 'https://example.test/team/repo.git' } })
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '/work/repo' } })
  fireEvent.click(screen.getByRole('button', { name: 'file.create' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/projects', { dir: '/work/repo', displayName: 'repo', cloneUrl: 'https://example.test/team/repo.git' }))
  expect(created).toHaveBeenCalledWith(expect.objectContaining({ key: 'project' }))
})
