// @vitest-environment jsdom
import { cleanup, fireEvent, render as renderView, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import AgentModels from './AgentModels'
import { agentModels, agentModelOptions, applyAgentModel, deleteAgentModel, restoreAgentModel, saveAgentModel, type AgentModelProfile, type AgentModelView } from '../../agent-registry'

vi.mock('./GatewayModelBinding', () => ({ default: () => null }))
vi.mock('../../agent-registry', () => ({ agentModels: vi.fn(), agentModelOptions: vi.fn(), applyAgentModel: vi.fn(), deleteAgentModel: vi.fn(), restoreAgentModel: vi.fn(), saveAgentModel: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
const preset: AgentModelProfile = { id: 'profile-1', name: 'Work gateway', baseUrl: 'https://gateway.example/v1', model: 'custom-model', protocol: 'openai-responses', authMode: 'api_key', hasKey: true, applied: false }
const view: AgentModelView = { profiles: [preset], current: { model: 'original-model' }, revision: 'revision-1', changed: false, canRestore: false, configPaths: ['/config/config.toml'] }
beforeAll(() => {
  const style = window.getComputedStyle; window.getComputedStyle = element => style(element)
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
beforeEach(() => vi.mocked(agentModels).mockResolvedValue(view))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const render = (element: Parameters<typeof renderView>[0]) => {
  const result = renderView(element)
  fireEvent.click(screen.getByText('hub.advancedPresets'))
  return result
}

it('applies a preset only after confirmation using the current revision', async () => {
  vi.mocked(applyAgentModel).mockResolvedValue({ ...view, profiles: [{ ...preset, applied: true }], current: { model: preset.model }, activeId: preset.id, canRestore: true })
  render(<AgentModels kind="codex" />)
  const row = await screen.findByRole('article', { name: preset.name })
  expect(screen.getByText('original-model')).toBeTruthy()
  fireEvent.click(within(row).getByRole('button', { name: 'capabilities.models.apply' }))
  expect(applyAgentModel).not.toHaveBeenCalled()
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(applyAgentModel).toHaveBeenCalledWith('codex', preset.id, 'revision-1'))
  await screen.findByText('capabilities.models.applied')
  expect(screen.queryByText('original-model')).toBeNull()
})

it('keeps a stored key private and does not overwrite it with an empty editor value', async () => {
  vi.mocked(saveAgentModel).mockResolvedValue({ ...preset, model: 'next-model' })
  render(<AgentModels kind="codex" />)
  const row = await screen.findByRole('article', { name: preset.name })
  fireEvent.click(within(row).getByRole('button', { name: 'capabilities.models.editAction' }))
  const secret = screen.getByLabelText('capabilities.models.apiKey') as HTMLInputElement
  expect(secret.value).toBe(''); expect(secret.type).toBe('password')
  fireEvent.change(screen.getByLabelText('capabilities.models.model'), { target: { value: 'next-model' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.save' }))
  await waitFor(() => expect(saveAgentModel).toHaveBeenCalledWith('codex', preset.id, expect.objectContaining({ apiKey: '', model: 'next-model' })))
  expect(applyAgentModel).not.toHaveBeenCalled()
})

it('preserves the full draft after a duplicate-name failure and lets the user retry', async () => {
  vi.mocked(agentModels).mockResolvedValue({ ...view, profiles: [] })
  vi.mocked(saveAgentModel).mockRejectedValueOnce(new Error('MODEL_PROFILE_NAME_EXISTS')).mockResolvedValueOnce(preset)
  render(<AgentModels kind="codex" />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.models.add' }))
  for (const [name, value] of [['name', 'Work gateway'], ['baseUrl', preset.baseUrl], ['model', preset.model], ['apiKey', 'typed-key']]) {
    fireEvent.change(screen.getByLabelText('capabilities.models.' + name), { target: { value } })
  }
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.save' }))
  await screen.findByText('capabilities.models.error.duplicate')
  expect((screen.getByLabelText('capabilities.models.apiKey') as HTMLInputElement).value).toBe('typed-key')
  expect((screen.getByLabelText('capabilities.models.name') as HTMLInputElement).value).toBe(preset.name)
  fireEvent.change(screen.getByLabelText('capabilities.models.name'), { target: { value: 'Other gateway' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.save' }))
  await waitFor(() => expect(saveAgentModel).toHaveBeenLastCalledWith('codex', undefined, expect.objectContaining({ name: 'Other gateway', apiKey: 'typed-key' })))
})

it('rereads after a configuration conflict without claiming an apply succeeded', async () => {
  vi.mocked(applyAgentModel).mockRejectedValue(new Error('AGENT_CONFIG_CHANGED'))
  render(<AgentModels kind="codex" />)
  const row = await screen.findByRole('article', { name: preset.name })
  fireEvent.click(within(row).getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await screen.findByText('capabilities.models.error.changed')
  expect(screen.queryByText('capabilities.models.applied')).toBeNull()
  vi.mocked(agentModels).mockResolvedValue({ ...view, revision: 'revision-2', current: { model: 'external-model' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.reread' }))
  await screen.findByText('external-model')
})

it('restores the original configuration explicitly and prevents deleting the active preset', async () => {
  vi.mocked(agentModels).mockResolvedValue({ ...view, profiles: [{ ...preset, applied: true }], activeId: preset.id, canRestore: true })
  vi.mocked(restoreAgentModel).mockResolvedValue(view)
  render(<AgentModels kind="codex" />)
  const row = await screen.findByRole('article', { name: preset.name })
  expect((within(row).getByRole('button', { name: 'capabilities.models.deleteAction' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.restore' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.restore' }))
  await waitFor(() => expect(restoreAgentModel).toHaveBeenCalledWith('codex', 'revision-1'))
  expect(deleteAgentModel).not.toHaveBeenCalled()
})

for (const kind of ['claude', 'codex', 'opencode', 'pi'] as const) {
  it(`offers searchable model choices and loads models with the stored credential for ${kind}`, async () => {
    vi.mocked(agentModelOptions).mockResolvedValue(['remote-model-a', 'remote-model-b'])
    render(<AgentModels kind={kind} />)
    fireEvent.click(within(await screen.findByRole('article', { name: preset.name })).getByRole('button', { name: 'capabilities.models.editAction' }))
    const model = screen.getByRole('combobox', { name: 'capabilities.models.model' })
    fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.fetchModels' }))
    await waitFor(() => expect(agentModelOptions).toHaveBeenCalledWith(kind, expect.objectContaining({ profileId: preset.id, apiKey: '', baseUrl: preset.baseUrl }), expect.any(AbortSignal)))
    fireEvent.focus(model); fireEvent.change(model, { target: { value: 'remote-model-b' } })
    await screen.findByRole('option', { name: 'remote-model-b' })
    fireEvent.keyDown(model, { key: 'ArrowDown', code: 'ArrowDown' }); fireEvent.keyDown(model, { key: 'Enter', code: 'Enter' })
    expect((model as HTMLInputElement).value).toBe('remote-model-b')
    expect(applyAgentModel).not.toHaveBeenCalled()
  })
}

it('keeps manual model input and credentials after model discovery fails', async () => {
  vi.mocked(agentModelOptions).mockRejectedValue(new Error('MODEL_LIST_UNSUPPORTED'))
  render(<AgentModels kind="codex" />)
  fireEvent.click(within(await screen.findByRole('article', { name: preset.name })).getByRole('button', { name: 'capabilities.models.editAction' }))
  const model = screen.getByLabelText('capabilities.models.model')
  fireEvent.change(model, { target: { value: 'my-private-model' } })
  fireEvent.change(screen.getByLabelText('capabilities.models.apiKey'), { target: { value: 'typed-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.fetchModels' }))
  await screen.findByText('capabilities.models.error.modelUnsupported')
  expect((model as HTMLInputElement).value).toBe('my-private-model')
  expect((screen.getByLabelText('capabilities.models.apiKey') as HTMLInputElement).value).toBe('typed-key')
})

it('ignores models from a connection that was changed while loading', async () => {
  let resolve!: (models: string[]) => void
  vi.mocked(agentModelOptions).mockImplementation(() => new Promise(done => { resolve = done }))
  render(<AgentModels kind="codex" />)
  fireEvent.click(within(await screen.findByRole('article', { name: preset.name })).getByRole('button', { name: 'capabilities.models.editAction' }))
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.fetchModels' }))
  const signal = vi.mocked(agentModelOptions).mock.calls[0][2]!
  fireEvent.change(screen.getByLabelText('capabilities.models.baseUrl'), { target: { value: 'https://other.example/v1' } })
  expect(signal.aborted).toBe(true)
  resolve(['obsolete-model'])
  const model = screen.getByLabelText('capabilities.models.model')
  fireEvent.focus(model); fireEvent.change(model, { target: { value: 'obsolete' } })
  await waitFor(() => expect(screen.queryByRole('option', { name: 'obsolete-model' })).toBeNull())
})
