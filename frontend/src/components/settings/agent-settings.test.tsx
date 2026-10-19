// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentSettings } from './agent-settings'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../i18n', () => { const t = (key: string) => key; return { useI18n: () => ({ t }) } })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const role = { baseUrl: 'https://models.example/v1', keyConfigured: true, model: 'fast', images: false }
const settings = { connection: { baseUrl: role.baseUrl, keyConfigured: true }, main: role, worker: { ...role, model: 'strong' } }
const mainModel = () => screen.getByRole('combobox', { name: 'agent.models.role.main agent.composer.model' })
const setup = () => render(<App><AgentSettings /></App>)
it('keeps one shared key and stages model selection before saving separate roles', async () => {
  vi.mocked(api).mockImplementation(async method => ({ data: method === 'POST' ? { models: ['fast', 'strong', 'other'] } : settings }))
  setup()
  await screen.findByLabelText('agent.models.baseUrl')
  expect(screen.getAllByLabelText('agent.models.baseUrl')).toHaveLength(1)
  expect(screen.getAllByLabelText('agent.models.apiKey')).toHaveLength(1)
  expect((screen.getByRole('button', { name: 'agent.models.save' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.mouseDown(mainModel())
  fireEvent.click(await screen.findByText('other'))
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { connection: { baseUrl: role.baseUrl }, main: { model: 'other', images: false, contextWindow: null, reasoningEffort: null }, worker: { model: 'strong', images: false, contextWindow: null, reasoningEffort: null } }))
})
it('supports a custom searched model and discards unsaved changes without writing', async () => {
  vi.mocked(api).mockImplementation(async method => ({ data: method === 'POST' ? { models: ['fast', 'strong'] } : settings }))
  setup(); await screen.findByLabelText('agent.models.baseUrl')
  fireEvent.mouseDown(mainModel()); fireEvent.change(mainModel(), { target: { value: 'custom-model' } })
  fireEvent.click(await screen.findByText('agent.models.use'))
  await screen.findByText('agent.models.unsaved')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.discard' }))
  await screen.findByText('agent.models.savedState')
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT')).toBe(false)
})
it('invalidates the old endpoint catalog and ignores its late response', async () => {
  let resolveCatalog!: (value: any) => void
  vi.mocked(api).mockImplementation(async method => method === 'POST' ? new Promise(resolve => { resolveCatalog = resolve }) : { data: settings })
  setup(); await screen.findByLabelText('agent.models.baseUrl')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.test' }))
  await waitFor(() => expect(resolveCatalog).toBeDefined())
  fireEvent.change(screen.getByLabelText('agent.models.baseUrl'), { target: { value: 'https://new.example/v1' } })
  resolveCatalog({ data: { models: ['stale-secret-model'] } })
  await waitFor(() => expect((screen.getByRole('button', { name: 'agent.models.test' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.queryByText('agent.models.catalogReady')).toBeNull()
  expect(screen.queryByText('stale-secret-model')).toBeNull()
})
it('shows catalog errors without disabling manual selection or saving the draft', async () => {
  vi.mocked(api).mockImplementation(async method => { if (method === 'POST') throw new Error('MODEL_HTTP_401'); return { data: settings } })
  setup(); await screen.findByLabelText('agent.models.baseUrl')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.test' }))
  await screen.findByRole('alert')
  expect((mainModel() as HTMLInputElement).disabled).toBe(false)
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT')).toBe(false)
})
