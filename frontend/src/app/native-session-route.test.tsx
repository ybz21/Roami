// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AppRoutes from './AppRoutes'

const layout = vi.hoisted(() => ({ size: 'large' }))
vi.mock('../layout', () => ({ useLayout: () => layout }))
vi.mock('../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../components/files/FilesPage', () => ({ default: () => null }))
vi.mock('../components/sessions/Sessions', () => ({ default: () => null }))
vi.mock('../components/settings/SettingsPage', () => ({ default: () => null }))
vi.mock('../components/agent/AgentChat', () => ({ default: ({ inactive, nativeSession }: any) => <div data-testid="main-chat" hidden={inactive} data-native-session={nativeSession} /> }))
vi.mock('../components/agent/AgentHomePage', () => ({ default: () => <div data-testid="session-page" /> }))
afterEach(cleanup)

it.each(['large', 'expanded', 'compact'])('keeps a native session visible at %s size', async size => {
  layout.size = size
  const props: any = {
    routing: { route: 'home/session/projects/native-id', tab: 'home', go: vi.fn(), selectAgent: vi.fn(), agentPage: { view: 'session', origin: 'projects', task: 'native-id' }, agentParts: ['projects'], agentCID: '', agentBranch: '', agentMessage: '' },
    isMobile: size === 'compact', active: null, projects: [], actions: { openTerm: vi.fn(), closeTerm: vi.fn(), newTerminalAt: vi.fn(), newTask: vi.fn(), openProject: vi.fn(), logout: vi.fn() },
    mobileProject: null, mobileSearchNonce: 0, mobileActionsHost: null,
    agent: { node: null, inbox: { conversations: [{ id: 'main' }], refresh: vi.fn() }, notifications: vi.fn() },
  }
  render(<AppRoutes {...props} />)
  if (size === 'large') {
    const main = await screen.findByTestId('main-chat')
    expect(main.hidden).toBe(false)
    expect(main.getAttribute('data-native-session')).toBe('native-id')
    expect(screen.queryByTestId('session-page')).toBeNull()
  } else expect(await screen.findByTestId('session-page')).toBeTruthy()
})
