// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import ModelHub from './ModelHub'
import GatewayModelBinding from './GatewayModelBinding'
import type { ModelCatalog } from './model-hub-api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false, keyboard: 0 }) }))
vi.mock('../settings/model-usage-chart', () => ({ ModelUsageChart: () => null }))
const catalog = { revision: 'revision-1', sources: [{ id: 'upstream', name: 'Saved source', baseUrl: 'https://models.example/v1', protocol: 'openai-responses', authMode: 'api_key', hasKey: true }], models: [{ id: 'coding', name: 'Coding', protocol: 'openai-responses', strategy: 'fixed', candidates: [{ sourceId: 'upstream', model: 'priced-model' }] }], drafts: [], baseUrl: 'http://127.0.0.1:19000', uses: {} }
const settings = { currency: 'CNY', timezone: 'Asia/Shanghai', dailyLimit: 3, pricing: { default: { input_per_million: 1, output_per_million: 2, cache_read_per_million: 0.5 }, models: { 'priced-model': { input_per_million: 4, output_per_million: 8, cache_read_per_million: 2 } } } }
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  let saved = structuredClone(catalog) as ModelCatalog
  vi.mocked(api).mockImplementation(async (method, path, body) => {
    if (path === '/agent/model-gateway/catalog') {
      if (method === 'PUT') saved = { ...body, revision: 'revision-2', baseUrl: catalog.baseUrl, uses: {} }
      return { data: structuredClone(saved) }
    }
    if (path === '/agent/model-gateway/settings') return { data: structuredClone(settings) }
    if (path.startsWith('/agent/model-gateway/usage')) return { data: { day: '2026-10-31', from: '2026-10-25', to: '2026-10-31', days: 7, timezone: 'Asia/Shanghai', today: [], groups: [], hourly: [], recent: [] } }
    return { data: {} }
  })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
const mount = (sub: string, navigate = vi.fn()) => render(<App><ModelHub sub={sub} onNav={navigate} /></App>)

it('retains old default and per-model prices and saves to the existing Go configuration', async () => {
  mount('prices')
  const input = await screen.findByLabelText('agent.proxy.price.input') as HTMLInputElement
  expect(input.value).toBe('1')
  fireEvent.click(await screen.findByRole('button', { name: /priced-model agent.prices.configured/ }))
  expect((screen.getByLabelText('agent.proxy.priceLabel', { selector: '#agent-price-0-input' }) as HTMLInputElement).value).toBe('4')
  fireEvent.change(input, { target: { value: '1.25' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/settings', { ...settings, pricing: { ...settings.pricing, default: { ...settings.pricing.default, input_per_million: 1.25 } } }))
})
it('keeps pricing usable when the independent model catalog cannot load', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => { if (path === '/agent/model-gateway/catalog') throw new Error('offline'); return { data: structuredClone(settings) } })
  mount('prices')
  expect((await screen.findByLabelText('agent.proxy.price.input') as HTMLInputElement).value).toBe('1')
  await screen.findByText('hub.error.failed')
})
it('saves an added model directly and makes it selectable by agents without publishing', async () => {
  const navigate = vi.fn(), page = mount('catalog/model/new', navigate)
  fireEvent.change(await screen.findByLabelText('hub.displayName'), { target: { value: 'New coding model' } })
  fireEvent.change(screen.getByLabelText('hub.upstreamModel'), { target: { value: 'provider/model-v2' } })
  expect(screen.queryByLabelText('hub.modelId')).toBeNull()
  expect(screen.queryByRole('button', { name: 'hub.saveDraft' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'hub.publish' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/catalog', expect.objectContaining({
    models: [...catalog.models, expect.objectContaining({ id: expect.any(String), name: 'New coding model', protocol: 'openai-responses', candidates: [{ sourceId: 'upstream', model: 'provider/model-v2' }] })], drafts: [],
  })))
  expect(navigate).toHaveBeenCalledWith('capabilities/models/catalog')
  page.unmount()
  render(<App><GatewayModelBinding kind="codex" view={{ current: {}, profiles: [], revision: 'cli-r1', canRestore: false, changed: false, configPaths: [] }} onChanged={async () => {}} /></App>)
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.custom' }))
  fireEvent.mouseDown(await screen.findByRole('combobox', { name: 'hub.source' }))
  fireEvent.click(await screen.findByTitle('Saved source'))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'hub.tab.catalog' }))
  expect(await screen.findByText('New coding model')).toBeTruthy()
})
it('uses the upstream model ID as the name when the optional display name is blank', async () => {
  mount('catalog/model/new')
  fireEvent.change(await screen.findByLabelText('hub.upstreamModel'), { target: { value: 'provider/model-v3' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/catalog', expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ name: 'provider/model-v3' })]) })))
})
it('opens the shared model list by default without exposing internal IDs or publish states', async () => {
  mount('')
  expect(await screen.findByText('Coding')).toBeTruthy()
  expect(screen.queryByText('coding')).toBeNull()
  expect(screen.queryByText('hub.state.published')).toBeNull()
  expect(screen.getByRole('tab', { name: 'hub.tab.catalog' }).getAttribute('aria-selected')).toBe('true')
})
