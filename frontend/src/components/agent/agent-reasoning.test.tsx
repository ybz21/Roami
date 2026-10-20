// @vitest-environment jsdom
import { act, fireEvent, render, renderHook, screen, cleanup, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentComposerPlus from './AgentComposerPlus'
import { useAgentModels } from './useAgentModels'
import { api } from '../../api'

const layout = vi.hoisted(() => ({ phone: false }))
vi.mock('../../layout', () => ({ useLayout: () => layout }))
vi.mock('../MobileSubPage', () => ({ default: ({ title, children, onBack, action }: any) => <section aria-label={title}><button onClick={onBack}>common.back</button>{action && <button onClick={action.onClick}>{action.label}</button>}{children}</section> }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', async () => { const { forwardRef } = await import('react'); return { Modal: ({ open, children, title }: any) => open ? <div role="dialog">{title}{children}</div> : null, Input: forwardRef(({ prefix: _prefix, allowClear: _clear, ...props }: any, ref: any) => <input ref={ref} {...props} />), Spin: () => null } })
afterEach(() => { cleanup(); layout.phone = false; vi.resetAllMocks() })
const role = { model: 'glm-5.3-flash', baseUrl: '', keyConfigured: true, images: false, reasoningEffort: 'low', reasoningEfforts: ['low', 'high', 'max'] }
function Composer({ onSkill }: { onSkill?: (name: string) => void }) {
  const models = useAgentModels(null)
  return <div className="agent-compose-card"><AgentComposerPlus models={models} disabled={false} canCompact modelTrigger={!onSkill} onSkill={onSkill} onFiles={vi.fn()} onCompact={vi.fn()} onCommands={vi.fn()} /></div>
}
function configure() {
  let selected = { ...role, reasoningEffort: 'low' as string | null }
  vi.mocked(api).mockImplementation(async (method, path, data) => {
    if (path === '/agent/models') return { data: { models: [role.model, 'gpt-6.1-sol'], reasoningEfforts: { 'gpt-6.1-sol': ['low', 'medium', 'high'] } } }
    if (method === 'PUT') selected = { ...selected, model: data.main.model, reasoningEffort: data.main.reasoningEffort, reasoningEfforts: data.main.model === 'gpt-6.1-sol' ? ['low', 'medium', 'high'] : role.reasoningEfforts }
    return { data: { main: selected, worker: role } }
  })
}
it('switches models in one tap, resets effort atomically, and picks effort separately', async () => {
  configure(); render(<Composer />)
  await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.trigger' }))
  fireEvent.click(await screen.findByRole('option', { name: 'gpt-6.1-sol' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { main: { model: 'gpt-6.1-sol', reasoningEffort: null } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.reasoning.picker' }))
  expect(screen.getByRole('menuitemradio', { name: 'agent.reasoning.default' }).getAttribute('aria-checked')).toBe('true')
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'agent.reasoning.medium' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { main: { model: 'gpt-6.1-sol', reasoningEffort: 'medium' } })
  expect(screen.getByText('agent.reasoning.medium')).toBeTruthy()
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')).toHaveLength(2)
})

it('closing model search or choosing the current model makes no write', async () => {
  configure(); render(<Composer />); await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.trigger' }))
  await screen.findByRole('option', { name: 'gpt-6.1-sol' })
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'custom/model-name' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.close' }))
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.trigger' }))
  fireEvent.click(await screen.findByRole('option', { name: role.model }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')).toHaveLength(0)
})

it('keeps the confirmed effort when saving fails and retries the same choice', async () => {
  configure(); const modelApi = vi.mocked(api).getMockImplementation()!; let reject = true
  vi.mocked(api).mockImplementation((method, path, ...rest) => {
    if (method === 'PUT' && reject) return Promise.reject({ apiError: { code: 'MODEL_CONFIGURATION_BUSY' } })
    return modelApi(method, path, ...rest)
  })
  render(<Composer />); await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { name: 'agent.reasoning.picker' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'agent.reasoning.high' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('menuitemradio', { name: 'agent.reasoning.low' }).getAttribute('aria-checked')).toBe('true')
  expect(screen.getByRole('menuitemradio', { name: 'agent.reasoning.high' }).getAttribute('aria-checked')).toBe('false')
  reject = false; fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByText('agent.reasoning.high')).toBeTruthy()
  const writes = vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')
  expect(writes).toHaveLength(2); expect(writes[0]).toEqual(writes[1])
})

it('writes once on rapid taps and can close while that selection saves', async () => {
  configure(); const modelApi = vi.mocked(api).getMockImplementation()!
  let finish!: () => void
  const pending = new Promise<void>(resolve => { finish = resolve })
  vi.mocked(api).mockImplementation(async (method, path, ...rest) => { if (method === 'PUT') await pending; return modelApi(method, path, ...rest) })
  render(<Composer />); await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.trigger' }))
  const option = await screen.findByRole('option', { name: 'gpt-6.1-sol' })
  fireEvent.click(option); fireEvent.click(option)
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'common.close' }))
  await act(async () => { finish(); await pending })
  await waitFor(() => expect(screen.getByRole('button', { name: 'agent.models.trigger' }).textContent).toContain('gpt-6.1-sol'))
})

it('opens a full mobile model page, pins the current model, and returns without saving', async () => {
  layout.phone = true; configure(); render(<Composer />)
  await screen.findByText('agent.reasoning.low')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.trigger' }))
  await screen.findByRole('option', { name: 'gpt-6.1-sol' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getAllByRole('option')[0].getAttribute('aria-selected')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: 'common.back' }))
  expect(screen.queryByRole('option')).toBeNull()
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')).toHaveLength(0)
})

it('ignores stale saves and lists after switching away from a node and back', async () => {
  let finishSave!: (value: any) => void, finishLoad!: (value: any) => void
  const save = new Promise<any>(resolve => { finishSave = resolve }), load = new Promise<any>(resolve => { finishLoad = resolve })
  vi.mocked(api).mockImplementation(async (method, path) => method === 'PUT' ? save : path === '/agent/models' ? load : { data: { main: role, worker: role } })
  const view = renderHook(({ node }) => useAgentModels(node), { initialProps: { node: 'A' } })
  await waitFor(() => expect(view.result.current.settings?.main.model).toBe(role.model))
  let saved!: Promise<boolean>
  act(() => { saved = view.result.current.apply('stale-model', 'high'); void view.result.current.load() })
  view.rerender({ node: 'B' }); view.rerender({ node: 'A' })
  await act(async () => { finishSave({ data: { main: { ...role, model: 'stale-model' }, worker: role } }); finishLoad({ data: { models: ['stale-model'] } }); await save; await load })
  expect(await saved).toBe(false)
  await waitFor(() => expect(view.result.current.settings?.main.model).toBe(role.model))
  expect(view.result.current.models).not.toContain('stale-model')
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

it('ignores settings reads started before a new selection while that selection saves', async () => {
  let finishRead!: (value: any) => void, finishSave!: () => void, hold = false
  const older = new Promise<any>(resolve => { finishRead = resolve }), saving = new Promise<void>(resolve => { finishSave = resolve })
  let selected = role
  vi.mocked(api).mockImplementation(async (method) => {
    if (method === 'PUT') { await saving; selected = { ...role, model: 'new-model' }; return { data: { main: selected, worker: role } } }
    if (hold) { hold = false; return older }
    return { data: { main: selected, worker: role } }
  })
  const view = renderHook(() => useAgentModels(null))
  await waitFor(() => expect(view.result.current.settings?.main.model).toBe(role.model))
  hold = true
  act(() => { window.dispatchEvent(new Event('roami:agent-model-settings-changed')) })
  let saved!: Promise<boolean>
  act(() => { saved = view.result.current.apply('new-model', 'default') })
  await act(async () => { finishRead({ data: { main: { ...role, model: 'stale-read' }, worker: role } }); await older })
  expect(view.result.current.settings?.main.model).toBe(role.model)
  await act(async () => { finishSave(); await saved })
  expect(view.result.current.settings?.main.model).toBe('new-model')
})

it('retries the settings read when the initial settings request failed', async () => {
  let fail = true
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/models') return { data: { models: [role.model] } }
    if (fail) throw new Error('offline')
    return { data: { main: role, worker: role } }
  })
  const view = renderHook(() => useAgentModels(null))
  await waitFor(() => expect(view.result.current.error).toBeTruthy())
  fail = false
  await act(async () => { await view.result.current.load() })
  await waitFor(() => expect(view.result.current.settings?.main.model).toBe(role.model))
  expect(view.result.current.error).toBeNull()
})
