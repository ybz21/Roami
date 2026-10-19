// @vitest-environment jsdom
import { fireEvent, render, screen, cleanup, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentComposerPlus from './AgentComposerPlus'
import { useAgentModels } from './useAgentModels'
import { api } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', () => ({ Modal: ({ open, children }: any) => open ? <div role="dialog">{children}</div> : null, Input: (props: any) => <input {...props} />, Spin: () => null }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const role = { model: 'glm-5.3-flash', baseUrl: '', keyConfigured: true, images: false, reasoningEffort: 'low', reasoningEfforts: ['low', 'high', 'max'] }
function Composer() {
  const models = useAgentModels(null)
  return <div className="agent-compose-card"><AgentComposerPlus models={models} disabled={false} canCompact modelTrigger onFiles={vi.fn()} onCompact={vi.fn()} onCommands={vi.fn()} /></div>
}
it('shows the effective effort, sends a chosen level, persists it after reopening and clears to model default', async () => {
  let effort: string | null = 'low'
  vi.mocked(api).mockImplementation(async (method, path, data) => {
    if (path === '/agent/models') return { data: { models: [role.model] } }
    if (method === 'PUT') effort = data.main.reasoningEffort
    return { data: { main: { ...role, reasoningEffort: effort }, worker: { ...role, reasoningEffort: 'high' } } }
  })
  const view = render(<Composer />)
  await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  fireEvent.click(screen.getByRole('menuitem', { name: /agent.reasoning.title/ }))
  expect(screen.queryByRole('menuitemradio', { name: 'agent.reasoning.medium' })).toBeNull()
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'agent.reasoning.high' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { main: { reasoningEffort: 'high' } }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByText('agent.reasoning.high')).toBeTruthy()
  view.unmount(); render(<Composer />)
  await screen.findByText('agent.reasoning.high')
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  fireEvent.click(screen.getByRole('menuitem', { name: /agent.reasoning.title/ }))
  expect(screen.getByRole('menuitemradio', { name: 'agent.reasoning.high' }).getAttribute('aria-checked')).toBe('true')
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'agent.reasoning.default' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { main: { reasoningEffort: null } }))
})

it('keeps the menu open and the current value when saving is rejected', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'PUT') throw { apiError: { code: 'MODEL_CONFIGURATION_BUSY' } }
    if (path === '/agent/models') return { data: { models: [role.model] } }
    return { data: { main: role, worker: role } }
  })
  render(<Composer />)
  await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  fireEvent.click(screen.getByRole('menuitem', { name: /agent.reasoning.title/ }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'agent.reasoning.high' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('dialog')).toBeTruthy()
  expect(screen.getByRole('menuitemradio', { name: 'agent.reasoning.low' }).getAttribute('aria-checked')).toBe('true')
})
