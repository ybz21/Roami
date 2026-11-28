// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import AppRoutes from './AppRoutes'
import { useAppRoute } from './useAppRoute'
import { useProjectDirectory } from './useProjectDirectory'

const { layout, api, sessionList } = vi.hoisted(() => ({ layout: { size: 'large' }, api: vi.fn(), sessionList: { value: [] } }))
vi.mock('../api', () => ({ api }))
vi.mock('../layout', () => ({ useLayout: () => layout }))
vi.mock('../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../components/sessions/native-session-list', () => ({ useNativeSessionList: () => sessionList }))
vi.mock('../components/projects/Projects', () => ({ default: () => <div data-testid="project-home" /> }))
vi.mock('../components/mobile/MobileSessions', () => ({ default: () => <div data-testid="mobile-projects" /> }))
vi.mock('../components/projects/okr/OkrProjects', () => ({ default: () => <div data-testid="okr-projects" /> }))
vi.mock('../components/projects/okr/ProjectOkr', () => ({ default: ({ projectId, openSwarm }: { projectId: string; openSwarm?: boolean }) => { const [initial] = useState(projectId); return <div data-testid="okr" data-project={projectId} data-initial-project={initial} data-open-swarm={openSwarm} /> } }))
vi.mock('../components/swarm/Swarm', () => ({ default: ({ initialSwarm }: { initialSwarm: string }) => <div data-testid="standalone-swarm" data-swarm={initialSwarm} /> }))
afterEach(() => { cleanup(); api.mockReset() })

function RoutedPage({ projectDirectory }: { projectDirectory?: React.ComponentProps<typeof AppRoutes>['projectDirectory'] }) {
  const routing = useAppRoute()
  return <AppRoutes routing={routing} isMobile={layout.size === 'compact'} active={null} projects={[]} projectDirectory={projectDirectory} actions={{ openTerm: vi.fn(), closeTerm: vi.fn(), newTerminalAt: vi.fn(), newTask: vi.fn(), openProject: vi.fn(), logout: vi.fn() }} mobileProject={null} mobileSearchNonce={0} mobileActionsHost={null} agent={{ node: null, inbox: { conversations: [], refresh: vi.fn() } as any, open: false, notifications: vi.fn() }} />
}

function ProjectDirectoryPage() {
  const directory = useProjectDirectory(false, '')
  return <RoutedPage projectDirectory={{ loaded: directory.projectsLoaded, error: directory.projectsError,
    retry: directory.refresh, projectSwarms: directory.projectSwarms, projectSwarmsError: directory.projectSwarmsError }} />
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
  fireEvent(window, new HashChangeEvent('hashchange'))
  await waitFor(() => expect(screen.getByTestId('okr').getAttribute('data-initial-project')).toBe('second'))
})

it.each(['large', 'compact'])('opens the sidebar OKR destination and its project links on %s', async size => {
  layout.size = size
  history.replaceState(null, '', '#/okr?node=remote')
  render(<RoutedPage />)
  expect(await screen.findByTestId('okr-projects')).toBeTruthy()
  history.replaceState(null, '', '#/okr/stable%20project?node=remote')
  fireEvent(window, new HashChangeEvent('hashchange'))
  await waitFor(() => expect(screen.getByTestId('okr').getAttribute('data-project')).toBe('stable project'))
  expect(screen.queryByTestId('okr-projects')).toBeNull()
})

it.each(['/okr', '/agent/swarms'])('keeps a project swarm out of the standalone view when %s fails on first load', async failingPath => {
  const swarmId = 'sw-' + 'a'.repeat(32), projectId = 'promotion'
  let fail = true
  api.mockImplementation(async (_method, path) => {
    if (path === failingPath && fail) {
      if (path === '/okr') throw new Error('HTTP 503')
      return { data: null }
    }
    if (path === '/okr') return { data: [{ projectId, swarm: swarmId }] }
    if (path === '/agent/swarms') return { data: [{ id: swarmId, target: { projectId }, sessionIds: [], name: 'Promotion' }] }
    return { data: {} }
  })
  layout.size = failingPath === '/okr' ? 'large' : 'compact'
  history.replaceState(null, '', '#/swarm/' + swarmId + '?node=remote')
  render(<ProjectDirectoryPage />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByTestId('standalone-swarm')).toBeNull()
  expect(location.hash).toBe('#/swarm/' + swarmId + '?node=remote')

  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  const project = await screen.findByTestId('okr')
  expect(project.getAttribute('data-open-swarm')).toBe('true')
  expect(project.getAttribute('data-project')).toBe(projectId)
  expect(location.hash).toBe('#/projects/promotion/okr/swarm?node=remote')
})

it('opens a standalone swarm when both successful directories show no project binding', async () => {
  const swarmId = 'sw-' + 'b'.repeat(32)
  api.mockImplementation(async (_method, path) => ({
    data: path === '/okr' ? [] : path === '/agent/swarms' ? [{ id: swarmId, target: {} }] : {},
  }))
  history.replaceState(null, '', '#/swarm/' + swarmId)
  render(<ProjectDirectoryPage />)
  expect((await screen.findByTestId('standalone-swarm')).getAttribute('data-swarm')).toBe(swarmId)
  expect(screen.queryByRole('alert')).toBeNull()
})
