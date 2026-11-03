// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import AppRoutes from './AppRoutes'
import { useAppRoute } from './useAppRoute'

const layout = vi.hoisted(() => ({ size: 'large' }))
vi.mock('../layout', () => ({ useLayout: () => layout }))
vi.mock('../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../components/projects/Projects', () => ({ default: () => <div data-testid="project-home" /> }))
vi.mock('../components/mobile/MobileSessions', () => ({ default: () => <div data-testid="mobile-projects" /> }))
vi.mock('../components/projects/okr/ProjectOkr', () => ({ default: ({ projectId }: { projectId: string }) => { const [initial] = useState(projectId); return <div data-testid="okr" data-project={projectId} data-initial-project={initial} /> } }))
afterEach(cleanup)

function RoutedPage() {
  const routing = useAppRoute()
  return <AppRoutes routing={routing} isMobile={layout.size === 'compact'} active={null} projects={[]} actions={{ openTerm: vi.fn(), closeTerm: vi.fn(), newTerminalAt: vi.fn(), newTask: vi.fn(), openProject: vi.fn(), logout: vi.fn() }} mobileProject={null} mobileSearchNonce={0} mobileActionsHost={null} agent={{ node: null, inbox: { conversations: [], refresh: vi.fn() } as any, open: false, notifications: vi.fn() }} />
}
it.each(['large', 'compact'])('routes the OKR URL to the same stable project on %s', async size => {
  layout.size = size
  history.replaceState(null, '', '#/projects/stable%20project/okr?node=remote')
  render(<RoutedPage />)
  expect((await screen.findByTestId('okr')).getAttribute('data-project')).toBe('stable project')
  expect(screen.queryByTestId('project-home')).toBeNull()
  expect(screen.queryByTestId('mobile-projects')).toBeNull()
})

it('remounts project-owned drafts when navigating directly between OKR projects', async () => {
  layout.size = 'large'
  history.replaceState(null, '', '#/projects/first/okr')
  render(<RoutedPage />)
  expect((await screen.findByTestId('okr')).getAttribute('data-initial-project')).toBe('first')
  history.replaceState(null, '', '#/projects/second/okr')
  const { fireEvent, waitFor } = await import('@testing-library/react')
  fireEvent(window, new HashChangeEvent('hashchange'))
  await waitFor(() => expect(screen.getByTestId('okr').getAttribute('data-initial-project')).toBe('second'))
})
