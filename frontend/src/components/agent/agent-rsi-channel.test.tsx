// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentHomePage from './AgentHomePage'

const state = vi.hoisted(() => ({ value: undefined as { developmentRsi: boolean } | undefined, loading: true, back: vi.fn() }))
vi.mock('./useAgentData', () => ({ useAgentData: () => ({ value: state.value, loading: state.loading }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('./agent-page-route', () => ({ backAgentPage: state.back, openAgentPage: vi.fn() }))
vi.mock('../MobileSubPage', () => ({ default: ({ children }: any) => children }))
vi.mock('./AgentImprovement', () => ({ default: () => <div data-testid="rsi" /> }))
vi.mock('./AgentMemory', () => ({ default: () => null }))
vi.mock('./AgentTasks', () => ({ default: () => null }))
vi.mock('./AgentInbox', () => ({ default: () => null }))
vi.mock('./AgentDebug', () => ({ default: () => null }))

const props = { page: { view: 'improvement', task: '', origin: 'home/main' } as const, node: null, inbox: {} as any, projects: [], select: vi.fn(), onSession: vi.fn(), onChanged: vi.fn() }
afterEach(() => { cleanup(); state.value = undefined; state.loading = true; vi.clearAllMocks() })
it('keeps the evaluator unmounted while channel availability is unknown', () => {
  render(<AgentHomePage {...props} />)
  expect(screen.queryByTestId('rsi')).toBeNull()
  expect(state.back).not.toHaveBeenCalled()
})
it.each([false, true])('guards direct RSI links using the selected node status (%s)', developmentRsi => {
  state.loading = false; state.value = { developmentRsi }
  render(<AgentHomePage {...props} />)
  expect(!!screen.queryByTestId('rsi')).toBe(developmentRsi)
  expect(state.back).toHaveBeenCalledTimes(developmentRsi ? 0 : 1)
})
it('returns to the originating page when status retrieval fails', () => {
  state.loading = false
  render(<AgentHomePage {...props} />)
  expect(screen.queryByTestId('rsi')).toBeNull()
  expect(state.back).toHaveBeenCalledWith(props.page)
})
