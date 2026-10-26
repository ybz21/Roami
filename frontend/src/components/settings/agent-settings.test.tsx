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
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { proxy: { dailyLimit: null, prices: {} }, connection: { baseUrl: role.baseUrl }, main: { model: 'other', images: false, contextWindow: null, reasoningEffort: null }, worker: { model: 'strong', images: false, contextWindow: null, reasoningEffort: null } }))
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

it('identifies an unavailable local runtime and retries the settings request', async () => {
  vi.mocked(api).mockRejectedValueOnce(Object.assign(new Error('AGENT_RUNTIME_UNAVAILABLE'), { apiError: { code: 'AGENT_RUNTIME_UNAVAILABLE' } })).mockResolvedValue({ data: settings })
  setup()
  expect((await screen.findByRole('alert')).textContent).toContain('agent.unavailable')
  expect(screen.queryByText('agent.models.failed')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByLabelText('agent.models.baseUrl')
})

const usage = { day: '2026-10-26', timezone: 'Asia/Shanghai', requests: 2, knownCost: 1.25, unknown: 1, pending: 0, inputTokens: 1000, outputTokens: 50, cacheReadTokens: 400, recent: [{ id: 'call', role: 'main', model: 'fast', started_ms: 1792971000000, state: 'unknown', input_tokens: 1000, output_tokens: 50, cost: null }] }
it('saves prices and a daily limit atomically, preserving input after a failed save', async () => {
  const configured = { ...settings, proxy: { dailyLimit: null, prices: {} } }
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (path === '/agent/model-usage') return { data: usage }
    if (method === 'PUT') throw new Error('MODEL_CONFIGURATION_BUSY')
    return { data: configured }
  })
  setup()
  await screen.findByRole('tab', { name: 'agent.proxy.tab' })
  fireEvent.click(screen.getByRole('tab', { name: 'agent.proxy.tab' }))
  await screen.findByLabelText('agent.proxy.dailyLimit')
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), { target: { value: '10' } })
  const fields = screen.getAllByRole('spinbutton')
  const rateFields = fields.filter(field => field.getAttribute('id')?.startsWith('agent-price-0-'))
  rateFields.forEach((field, index) => fireEvent.change(field, { target: { value: ['2', '8', '0.2'][index] } }))
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await screen.findByText('agent.models.busy')
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('10')
  expect(vi.mocked(api).mock.calls.find(call => call[0] === 'PUT')?.[2]).toMatchObject({ proxy: { dailyLimit: 10, prices: { fast: { input: 2, output: 8, cacheRead: 0.2 } } } })
  expect(screen.getByText('agent.proxy.unknown')).toBeTruthy()
  expect(screen.getByText('agent.proxy.costUnknown')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.discard' }))
})
it('keeps partial prices unsaved and allows an explicit zero price', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path === '/agent/model-usage' ? usage : settings }))
  setup(); await screen.findByRole('tab', { name: 'agent.proxy.tab' }); fireEvent.click(screen.getByRole('tab', { name: 'agent.proxy.tab' })); await screen.findByLabelText('agent.proxy.dailyLimit')
  const fields = [...document.querySelectorAll<HTMLInputElement>('input[id^="agent-price-0-"]')]
  fireEvent.change(fields[0], { target: { value: '0' } })
  expect((screen.getByRole('button', { name: 'agent.models.save' }) as HTMLButtonElement).disabled).toBe(true)
  fields.slice(1).forEach(field => fireEvent.change(field, { target: { value: '0' } }))
  expect((screen.getByRole('button', { name: 'agent.models.save' }) as HTMLButtonElement).disabled).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.discard' }))
  expect(fields[0].value).toBe('')
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT')).toBe(false)
})

it('opens model configuration first and preserves both drafts across tabs before one save', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path === '/agent/model-usage' ? usage : settings }))
  setup()
  await screen.findByLabelText('agent.models.baseUrl')
  expect(screen.getByRole('tab', { name: 'agent.models.configurationTab' }).getAttribute('aria-selected')).toBe('true')
  expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/model-usage')).toBe(false)
  fireEvent.change(screen.getByLabelText('agent.models.apiKey'), { target: { value: 'draft-fixture-key' } })
  fireEvent.click(screen.getByRole('tab', { name: 'agent.proxy.tab' }))
  expect(screen.queryByRole('combobox', { name: 'agent.models.role.main agent.composer.model' })).toBeNull()
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), { target: { value: '12' } })
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/model-usage')).toBe(true))
  fireEvent.click(screen.getByRole('tab', { name: 'agent.models.configurationTab' }))
  expect((screen.getByLabelText('agent.models.apiKey') as HTMLInputElement).value).toBe('draft-fixture-key')
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('12')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(vi.mocked(api).mock.calls.find(call => call[0] === 'PUT')?.[2]).toMatchObject({ connection: { apiKey: 'draft-fixture-key' }, proxy: { dailyLimit: 12 } }))
})
