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
function Composer({ onSkill }: { onSkill?: (name: string) => void }) {
  const models = useAgentModels(null)
  return <div className="agent-compose-card"><AgentComposerPlus models={models} disabled={false} canCompact modelTrigger={!onSkill} onSkill={onSkill} onFiles={vi.fn()} onCompact={vi.fn()} onCommands={vi.fn()} /></div>
}
function configure() {
  let selected = { ...role, reasoningEffort: 'low' as string | null }
  vi.mocked(api).mockImplementation(async (method, path, data) => {
    if (path === '/agent/models') return { data: { models: [role.model, 'gpt-6.1-sol'], reasoningEfforts: { 'gpt-6.1-sol': ['low', 'medium', 'high'] } } }
    if (method === 'PUT') selected = { ...selected, model: data.main.model, reasoningEffort: data.main.reasoningEffort }
    return { data: { main: selected, worker: role } }
  })
}
it('stages model and effort together and applies once; cancelling never saves', async () => {
  configure(); render(<Composer />)
  await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  await screen.findByRole('menuitemradio', { name: 'gpt-6.1-sol' })
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'gpt-6.1-sol' }))
  expect((screen.getByRole('radio', { name: 'agent.reasoning.default' }) as HTMLInputElement).checked).toBe(true)
  fireEvent.click(screen.getByRole('radio', { name: 'agent.reasoning.medium' }))
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'agent.composer.applyModel' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { main: { model: 'gpt-6.1-sol', reasoningEffort: 'medium' } })
  await screen.findByText('agent.reasoning.medium')
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  fireEvent.click(screen.getByRole('radio', { name: 'agent.reasoning.default' }))
  fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')).toHaveLength(1)
})
it('clears the override to default and preserves the staged choice after a rejected save', async () => {
  configure(); const view = render(<Composer />)
  await screen.findByText('agent.reasoning.low'); fireEvent.click(screen.getByRole('button', { expanded: false }))
  fireEvent.click(screen.getByRole('radio', { name: 'agent.reasoning.default' })); fireEvent.click(screen.getByRole('button', { name: 'agent.composer.applyModel' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { main: { model: role.model, reasoningEffort: null } })
  view.unmount(); configure(); vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'PUT') throw { apiError: { code: 'MODEL_CONFIGURATION_BUSY' } }
    return path === '/agent/models' ? { data: { models: [role.model] } } : { data: { main: role, worker: role } }
  }); render(<Composer />)
  await screen.findByText('agent.reasoning.low'); fireEvent.click(screen.getByRole('button', { expanded: false }))
  fireEvent.click(screen.getByRole('radio', { name: 'agent.reasoning.high' })); fireEvent.click(screen.getByRole('button', { name: 'agent.composer.applyModel' }))
  await screen.findByRole('alert')
  expect((screen.getByRole('radio', { name: 'agent.reasoning.high' }) as HTMLInputElement).checked).toBe(true)
  expect(screen.getByText('agent.reasoning.low', { selector: '.agent-reasoning-label' })).toBeTruthy()
})
it('lists only enabled installed skills and selects into the draft without executing', async () => {
  const pick = vi.fn(); configure()
  const modelApi = vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation((method, path, ...rest) => path === '/agent/capability-settings' ? Promise.resolve({ data: { skills: [{ name: 'installed', enabled: true, description: 'An installed workflow' }, { name: 'disabled', enabled: false }] } }) : modelApi(method, path, ...rest))
  render(<Composer onSkill={pick} />)
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  fireEvent.click(await screen.findByRole('menuitem', { name: /installed/ }))
  expect(screen.queryByRole('menuitem', { name: /disabled/ })).toBeNull()
  expect(pick).toHaveBeenCalledWith('installed')
  expect(vi.mocked(api).mock.calls.every(([method]) => method === 'GET')).toBe(true)
})

it('loads context only inside the plus menu and closes that menu before opening details', async () => {
  vi.mocked(api).mockResolvedValue({ data: { estimatedTokens: 12400, contextWindow: 128000 } })
  const open = vi.fn(), models = { settings: { main: role, worker: role }, efforts: {}, models: [], load: vi.fn() } as any
  render(<div className="agent-compose-card"><AgentComposerPlus models={models} disabled={false} canCompact onFiles={vi.fn()} onCompact={vi.fn()} onCommands={vi.fn()} onContext={open} contextUsage={{ cid: 'main', model: role.model, revision: 'one', active: false }} /></div>)
  expect(vi.mocked(api).mock.calls.some(call => call[1].endsWith('/context'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'agent.composer.more' }))
  fireEvent.click(await screen.findByRole('menuitem', { name: 'agent.contextMeter.known' }))
  expect(open).toHaveBeenCalledOnce()
  expect(screen.queryByRole('dialog')).toBeNull()
})
