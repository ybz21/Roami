// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import OkrBuildWorkspace from './OkrBuildWorkspace'
import { emptyConfiguration, type Workspace } from './okr-workspace'
const layout = vi.hoisted(() => ({ phone: false }))
vi.mock('../../../layout', () => ({ useLayout: () => layout }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('./OkrMainChat', () => ({ default: ({ projectId, onUpdated }: { projectId: string; onUpdated: () => void }) => <div data-testid="main" data-project={projectId}><textarea aria-label="draft" defaultValue="saved input" /><button onClick={onUpdated}>Updated</button></div> }))
vi.mock('./OkrGoalMap', () => ({ default: ({ workspace }: { workspace: Workspace }) => <div>{workspace.objective}</div> }))
vi.mock('./OkrDashboard', () => ({ default: () => <div>Dashboard</div> }))
vi.mock('./OkrProjectFiles', () => ({ default: () => <div>Files</div> }))
afterEach(() => { cleanup(); layout.phone = false })
const props = { projectId: 'original-project', projectDir: '/project', draft: emptyConfiguration(), workspace: null, onSession: vi.fn(), onUpdated: vi.fn(), onClose: vi.fn() }
it('opens the original project Main without dispatching tasks, preserves chat when preview closes and updates the saved plan', () => {
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener() {}, removeListener() {} })
  const updated = vi.fn()
  const page = render(<OkrBuildWorkspace {...props} onUpdated={updated} />)
  const main = screen.getByTestId('main')
  expect(main.getAttribute('data-project')).toBe('original-project')
  fireEvent.change(screen.getByLabelText('draft'), { target: { value: 'unfinished' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.builder.hidePreview' }))
  expect(screen.queryByRole('complementary')).toBeNull()
  expect(screen.getByLabelText('draft')).toHaveProperty('value', 'unfinished')
  fireEvent.click(screen.getByRole('button', { name: 'okr.builder.showPreview' }))
  fireEvent.click(screen.getByRole('button', { name: 'Updated' }))
  expect(updated).toHaveBeenCalledOnce()
  page.rerender(<OkrBuildWorkspace {...props} onUpdated={updated} workspace={{ ...emptyConfiguration(), projectId: 'original-project', revision: 2, objective: 'Saved goal', observations: [], reviews: [], updatedAt: '' }} />)
  expect(screen.getByText('Saved goal')).toBeTruthy()
  expect(screen.getByTestId('main')).toBe(main)
})
it('keeps the same Main and input mounted while phone preview is open', () => {
  layout.phone = true
  render(<OkrBuildWorkspace {...props} />)
  const main = screen.getByTestId('main')
  fireEvent.click(screen.getByRole('button', { name: 'okr.builder.preview' }))
  expect(main.closest('[hidden]')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'okr.builder.chat' }))
  expect(screen.getByTestId('main')).toBe(main)
  expect(screen.getByLabelText('draft')).toHaveProperty('value', 'saved input')
})
