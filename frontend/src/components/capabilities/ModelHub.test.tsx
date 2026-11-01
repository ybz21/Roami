// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

it('shows connections and their models together and accepts old source-page links', async () => {
  mount('sources')
  const connection = await screen.findByRole('region', { name: 'Saved source' })
  expect(connection.textContent).toContain('Coding')
  expect(screen.queryByRole('tab', { name: 'hub.tab.sources' })).toBeNull()
  expect(screen.getAllByRole('tab')).toHaveLength(4)
  expect(screen.getByRole('tab', { name: 'hub.tab.catalog' }).getAttribute('aria-selected')).toBe('true')
  expect(screen.queryByText('hub.consumers')).toBeNull()
})

it('adds a source and a deduplicated manual batch in one save without confirmation', async () => {
  mount('catalog/source/new')
  fireEvent.change(await screen.findByLabelText('agent.models.baseUrl'), { target: { value: 'https://new.example/v1' } })
  fireEvent.change(screen.getByLabelText('agent.models.apiKey'), { target: { value: 'test-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.manual' }))
  fireEvent.change(screen.getByLabelText('hub.directory.manual'), { target: { value: 'first-model\nsecond-model\nfirst-model\n' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.saveModels' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/catalog', expect.objectContaining({
    sources: expect.arrayContaining([expect.objectContaining({ name: 'new.example', baseUrl: 'https://new.example/v1', apiKey: 'test-key' })]),
    models: expect.arrayContaining([expect.objectContaining({ name: 'first-model' }), expect.objectContaining({ name: 'second-model' })]),
  })))
  expect(screen.queryByRole('dialog')).toBeNull()
  const writes = vi.mocked(api).mock.calls.filter(([method]) => method === 'PUT')
  expect(writes).toHaveLength(1)
  expect((writes[0][2] as ModelCatalog).models).toHaveLength(3)
  expect((writes[0][2] as ModelCatalog).models[0]).toEqual(catalog.models[0])
})

it('fetches an unsaved source, selects all matches and keeps selection across searches', async () => {
  const original = vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async (method, path, body, options) => path.endsWith('/discover') ? { data: { models: ['alpha', 'beta', 'gamma'] } } : original(method, path, body, options))
  mount('catalog/source/new')
  fireEvent.change(await screen.findByLabelText('agent.models.baseUrl'), { target: { value: 'https://new.example/v1' } })
  fireEvent.change(screen.getByLabelText('agent.models.apiKey'), { target: { value: 'draft-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.fetch' }))
  await screen.findByRole('checkbox', { name: 'alpha' })
  expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/discover', expect.objectContaining({ revision: catalog.revision, source: expect.objectContaining({ apiKey: 'draft-key' }) }), expect.anything())
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'PUT')).toBe(false)
  fireEvent.click(screen.getByRole('checkbox', { name: 'beta' }))
  fireEvent.change(screen.getByLabelText('hub.directory.search'), { target: { value: 'alpha' } })
  fireEvent.click(screen.getByRole('checkbox', { name: 'hub.directory.selectMatches' }))
  fireEvent.change(screen.getByLabelText('hub.directory.search'), { target: { value: '' } })
  expect((screen.getByRole('checkbox', { name: 'beta' }) as HTMLInputElement).checked).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.saveModels' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/catalog', expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ name: 'alpha' }), expect.objectContaining({ name: 'beta' })]) })))
})

it('keeps existing IDs, credentials and failover candidates while adding discovered models', async () => {
  const backup = { ...catalog.sources[0], id: 'backup', name: 'Backup source' }
  const saved = { ...catalog, sources: [...catalog.sources, backup], models: [{ ...catalog.models[0], strategy: 'failover', candidates: [...catalog.models[0].candidates, { sourceId: 'backup', model: 'backup-model' }] }] }
  vi.mocked(api).mockImplementation(async (method, path, body) => ({ data: path.endsWith('/discover') ? { models: ['priced-model', 'new-model'] } : method === 'PUT' ? { ...body, revision: 'r2' } : saved }))
  mount('catalog/source/upstream')
  fireEvent.click(await screen.findByRole('button', { name: 'hub.directory.fetch' }))
  expect((await screen.findByRole('checkbox', { name: 'priced-model' }) as HTMLInputElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox', { name: 'hub.directory.selectAll' }))
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.saveModels' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/catalog', expect.objectContaining({
    sources: expect.arrayContaining([expect.objectContaining({ id: 'upstream', hasKey: true, apiKey: '' })]),
    models: [saved.models[0], expect.objectContaining({ name: 'new-model' })],
  })))
})

it('preserves inputs after authentication errors and allows manual recovery', async () => {
  const original = vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async (method, path, body, options) => { if (path.endsWith('/discover')) throw { apiError: { code: 'MODEL_LIST_UNAUTHORIZED' } }; return original(method, path, body, options) })
  mount('catalog/source/new')
  fireEvent.change(await screen.findByLabelText('agent.models.baseUrl'), { target: { value: 'https://new.example/v1' } })
  fireEvent.change(screen.getByLabelText('agent.models.apiKey'), { target: { value: 'draft-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.fetch' }))
  await screen.findByText('hub.directory.unauthorized')
  expect((screen.getByLabelText('agent.models.apiKey') as HTMLInputElement).value).toBe('draft-key')
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.manual' }))
  fireEvent.change(screen.getByLabelText('hub.directory.manual'), { target: { value: 'manual-model' } })
  expect((screen.getByRole('button', { name: 'hub.directory.saveModels' }) as HTMLButtonElement).disabled).toBe(false)
})

it('discards discovery responses after editing the endpoint', async () => {
  let finish: (value: any) => void = () => {}
  const original = vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async (method, path, body, options) => path.endsWith('/discover') ? new Promise(resolve => { finish = resolve }) : original(method, path, body, options))
  mount('catalog/source/new')
  fireEvent.change(await screen.findByLabelText('agent.models.baseUrl'), { target: { value: 'https://old.example/v1' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.fetch' }))
  fireEvent.change(screen.getByLabelText('agent.models.baseUrl'), { target: { value: 'https://new.example/v1' } })
  finish({ data: { models: ['obsolete'] } })
  await waitFor(() => expect((screen.getByRole('button', { name: 'hub.directory.fetch' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.queryByRole('checkbox', { name: 'obsolete' })).toBeNull()
})

it('keeps selected models after save fails and retries without a new discovery request', async () => {
  const original = vi.mocked(api).getMockImplementation()!
  let attempts = 0
  vi.mocked(api).mockImplementation(async (method, path, body, options) => {
    if (path.endsWith('/discover')) return { data: { models: ['recoverable-model'] } }
    if (method === 'PUT' && attempts++ === 0) throw new Error('offline')
    return original(method, path, body, options)
  })
  mount('catalog/source/upstream')
  fireEvent.click(await screen.findByRole('button', { name: 'hub.directory.fetch' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'recoverable-model' }))
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.saveModels' }))
  await waitFor(() => expect(screen.getAllByText('hub.error.failed').length).toBeGreaterThan(0))
  expect((screen.getByRole('checkbox', { name: 'recoverable-model' }) as HTMLInputElement).checked).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.saveModels' }))
  await waitFor(() => expect(attempts).toBe(2))
  expect(vi.mocked(api).mock.calls.filter(([, path]) => path.endsWith('/discover'))).toHaveLength(1)
})

it('retains each source draft when navigating back and reopening', async () => {
  const navigate = vi.fn(), page = mount('catalog/source/new', navigate)
  fireEvent.change(await screen.findByLabelText('agent.models.baseUrl'), { target: { value: 'https://draft.example/v1' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.manual' }))
  fireEvent.change(screen.getByLabelText('hub.directory.manual'), { target: { value: 'draft-model' } })
  page.rerender(<App><ModelHub sub="catalog" onNav={navigate} /></App>)
  page.rerender(<App><ModelHub sub="catalog/source/new" onNav={navigate} /></App>)
  expect((screen.getByLabelText('agent.models.baseUrl') as HTMLInputElement).value).toBe('https://draft.example/v1')
  expect((screen.getByLabelText('hub.directory.manual') as HTMLTextAreaElement).value).toBe('draft-model')
})

it('blocks stale source configuration after rereading a conflicting catalog', async () => {
  let reads = 0
  const updated = { ...catalog, revision: 'revision-2', sources: [{ ...catalog.sources[0], baseUrl: 'https://changed.example/v1' }] }
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (path.endsWith('/discover')) return { data: { models: ['selected-model'] } }
    if (method === 'PUT') throw { apiError: { code: 'MODEL_CATALOG_CHANGED' } }
    return { data: reads++ ? updated : catalog }
  })
  mount('catalog/source/upstream')
  fireEvent.click(await screen.findByRole('button', { name: 'hub.directory.fetch' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'selected-model' }))
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.saveModels' }))
  await waitFor(() => expect(screen.getAllByText('hub.error.changed').length).toBeGreaterThan(0))
  fireEvent.click(screen.getAllByRole('button', { name: 'capabilities.models.reread' }).slice(-1)[0])
  await screen.findByText('hub.directory.sourceChanged')
  expect((screen.getByRole('button', { name: 'hub.directory.saveModels' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'hub.directory.useLatest' }))
  expect((screen.getByLabelText('agent.models.baseUrl') as HTMLInputElement).value).toBe('https://changed.example/v1')
  expect(screen.queryByRole('checkbox', { name: 'selected-model' })).toBeNull()
})
