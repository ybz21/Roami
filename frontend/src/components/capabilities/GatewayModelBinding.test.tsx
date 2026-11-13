// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayModelBinding from './GatewayModelBinding'
import type { AgentModelView } from '../../agent-registry'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
const sources = ['a', 'b'].map(id => ({ id, name: 'Source ' + id, protocol: 'anthropic-messages', baseUrl: 'https://' + id + '.example', authMode: 'bearer' }))
const models = ['a', 'b'].map(id => ({ id: 'model-' + id, name: 'Model ' + id, protocol: 'anthropic-messages', strategy: 'fixed', candidates: [{ sourceId: id, model: 'upstream-' + id }] }))
const view: AgentModelView = { mode: 'custom', profiles: [{ id: 'active', name: 'Roami Gateway', model: 'model-a', baseUrl: 'http://127.0.0.1:19000', protocol: 'anthropic-messages', authMode: 'bearer', hasKey: true, applied: true }], current: { model: 'model-a', provider: 'Roami Gateway' }, activeId: 'active', revision: 'native-r1', changed: false, canRestore: true, configPaths: [] }
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.mocked(api).mockImplementation(async (_method, path) => path.endsWith('/source-models') ? { data: { models: [] } } : ({ data: { revision: 'catalog-r1', sources, models, drafts: [], uses: {}, baseUrl: 'http://127.0.0.1:19000' } }))
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
const mount = (current = view, installed = true) => { const changed = vi.fn(async () => {}); render(<App><GatewayModelBinding kind="claude" view={current} installed={installed} onChanged={changed} /></App>); return changed }
const select = async (label: string, option: string) => {
  fireEvent.mouseDown(screen.getByRole('combobox', { name: label }))
  fireEvent.click(await screen.findByText(option, { selector: '.ant-select-item-option-content' }))
}
it('allows applying a direct native preset that already matches a saved source and model', async () => {
  mount({ ...view, profiles: [{ ...view.profiles[0], name: 'Native preset', baseUrl: sources[0].baseUrl + '/v1', model: 'upstream-a' }], current: { provider: 'Native preset', model: 'upstream-a' } })
  await screen.findByText('Source a')
  expect(screen.getByText('hub.directConnection')).toBeTruthy()
  expect(screen.queryByText('hub.gatewayCurrent')).toBeNull()
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind: 'claude', sourceId: 'a', model: 'model-a', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
})
it('marks a matching gateway profile as applied', async () => {
  mount({ ...view, profiles: [{ ...view.profiles[0], baseUrl: view.profiles[0].baseUrl + '/v1/' }] })
  await screen.findByText('Source a')
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByText('hub.directConnection')).toBeNull()
  expect(screen.getByText('hub.gatewayCurrent')).toBeTruthy()
})
it.each(['upstream-a', 'model-a'])('does not match a direct preset to a different protocol or a gateway alias: %s', async model => {
  mount({ ...view, profiles: [{ ...view.profiles[0], baseUrl: sources[0].baseUrl, protocol: 'openai-completions', model }], current: { provider: 'Native preset', model } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('GET', '/agent/model-gateway/catalog', undefined, expect.anything()))
  await screen.findByText('hub.gatewayDefault')
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).not.toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/source-models', expect.anything(), expect.anything())
})

it.each(['claude', 'codex', 'opencode', 'pi'] as const)('applies the gateway default to %s without selecting or fetching a source', async kind => {
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models, drafts: [], uses: {}, baseUrl: view.profiles[0].baseUrl, defaultModel: 'model-b' } })
  render(<App><GatewayModelBinding kind={kind} view={{ ...view, mode: 'official', profiles: [], current: {}, activeId: undefined }} onChanged={async () => {}} /></App>)
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.custom' }))
  await screen.findByText('hub.gatewayDefaultHint')
  await waitFor(() => expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.queryByRole('combobox', { name: 'hub.tab.catalog' })).toBeNull()
  expect(api).not.toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/source-models', expect.anything(), expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind, model: 'roami-default', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
})

it('marks default as applied and recognizes a model selected inside Claude Code', async () => {
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models, baseUrl: view.profiles[0].baseUrl, defaultModel: 'model-b' } })
  mount({ ...view, current: { model: 'roami-default' } })
  await screen.findByText('hub.gatewayDefaultHint')
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  cleanup()
  mount({ ...view, activeId: undefined, changed: true, profiles: [{ ...view.profiles[0], applied: false }], current: { model: 'roami-claude/model-b[1m]', baseUrl: view.profiles[0].baseUrl } })
  await screen.findByText('Source b')
  expect(screen.getByText('Model b', { selector: '.ant-select-selection-item' })).toBeTruthy()
})
it('chooses a saved source first and exposes only that source’s models', async () => {
  mount(); await screen.findByText('Source a')
  await select('hub.upstreamSource', 'Source b')
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'hub.tab.catalog' }))
  expect(await screen.findByText('Model b', { selector: '.ant-select-item-option-content' })).toBeTruthy()
  expect(screen.queryByText('Model a', { selector: '.ant-select-item-option-content' })).toBeNull()
  fireEvent.click(screen.getByText('Model b', { selector: '.ant-select-item-option-content' }))
  expect(api).not.toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind: 'claude', sourceId: 'b', model: 'model-b', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
})
it('uses a real factory-mode action instead of restoring an old third-party connection', async () => {
  const changed = mount(); await screen.findByText('Source a')
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.official' }))
  expect(screen.queryByRole('combobox', { name: 'hub.upstreamSource' })).toBeNull()
  expect(api).not.toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/professional/claude/models/default', { revision: 'native-r1' }))
  expect(api).not.toHaveBeenCalledWith('POST', expect.stringContaining('/restore'), expect.anything())
  expect(changed).toHaveBeenCalled()
})
it('keeps factory mode available if the shared model directory cannot load', async () => {
  vi.mocked(api).mockImplementation(async method => { if (method === 'GET') throw new Error('offline'); return {} })
  mount(); fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.official' }))
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/professional/claude/models/default', { revision: 'native-r1' }))
})
it('requires installation before applying and keeps the factory default on a new agent', async () => {
  mount({ ...view, mode: 'official', profiles: [], current: {}, activeId: undefined, canRestore: false }, false)
  expect(screen.getByRole('radio', { name: 'hub.mode.official' }).getAttribute('checked')).not.toBeNull()
  expect(screen.getByText('hub.installFirst')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
})

it('reads models from a saved source without requiring prior model registration', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => path.endsWith('/source-models') ? { data: { models: ['vendor/new-model'] } } : { data: { revision: 'catalog-r1', sources, models: [], drafts: [], uses: {} } })
  mount({ ...view, mode: 'official', profiles: [], current: {}, activeId: undefined })
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.custom' }))
  await select('hub.upstreamSource', 'Source a')
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/source-models', { kind: 'claude', sourceId: 'a', revision: 'catalog-r1' }, expect.objectContaining({ signal: expect.any(AbortSignal) })))
  await select('hub.tab.catalog', 'vendor/new-model')
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind: 'claude', sourceId: 'a', upstreamModel: 'vendor/new-model', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
  expect(api).not.toHaveBeenCalledWith('PUT', '/agent/model-gateway/catalog', expect.anything())
})

it('allows a known model ID when a source has no model-list endpoint', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.endsWith('/source-models')) throw Object.assign(new Error('unsupported'), { apiError: { code: 'MODEL_LIST_UNSUPPORTED' } })
    return { data: { revision: 'catalog-r1', sources, models, drafts: [], uses: {}, baseUrl: view.profiles[0].baseUrl } }
  })
  mount(); await screen.findByText('hub.sourceListUnsupported')
  const field = screen.getByRole('combobox', { name: 'hub.tab.catalog' })
  fireEvent.mouseDown(field)
  fireEvent.change(field, { target: { value: 'typed/model-id' } })
  fireEvent.click(await screen.findByText('typed/model-id', { selector: '.ant-select-item-option-content' }))
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', expect.objectContaining({ sourceId: 'a', upstreamModel: 'typed/model-id' })))
})

it.each(['claude', 'codex', 'opencode', 'pi'] as const)('offers the same Chat Completions source and model to %s through the gateway', async kind => {
  vi.mocked(api).mockImplementation(async (_method, path) => path.endsWith('/source-models') ? { data: { models: [] } } : { data: { revision: 'catalog-r1', sources: [{ ...sources[0], protocol: 'openai-completions' }], models: [{ ...models[0], protocol: 'openai-completions' }], drafts: [], uses: {} } })
  render(<App><GatewayModelBinding kind={kind} view={{ ...view, mode: 'official', profiles: [], current: {}, activeId: undefined }} onChanged={async () => {}} /></App>)
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.custom' }))
  await select('hub.upstreamSource', 'Source a')
  await select('hub.tab.catalog', 'Model a')
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind, sourceId: 'a', model: 'model-a', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
})


it.each(['pi', 'opencode'] as const)('allows syncing a changed gateway catalog to %s without losing the current model', async kind => {
  const profile = { ...view.profiles[0], models: models.map(model => ({ id: model.id, name: model.name })) }
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models, baseUrl: profile.baseUrl } })
  const mounted = render(<App><GatewayModelBinding kind={kind} view={{ ...view, profiles: [profile] }} onChanged={async () => {}} /></App>)
  await screen.findByText('Source a')
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  mounted.rerender(<App><GatewayModelBinding kind={kind} view={{ ...view, profiles: [{ ...profile, models: [] }] }} onChanged={async () => {}} /></App>)
  expect(screen.getByText('hub.gatewayCatalogChanged')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(false)
  expect(screen.getByText('Model a', { selector: '.ant-select-selection-item' })).toBeTruthy()
})


it('recognizes a Claude routing group alias and preserves the gateway default entry', async () => {
  const group = { ...models[0], id: 'free-pool', name: 'Free pool', aggregate: true, strategy: 'smart' }
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models: [...models, group], baseUrl: view.profiles[0].baseUrl, defaultModel: group.id } })
  mount({ ...view, current: { model: 'roami-claude/free-pool[1m]' } })
  await screen.findByText('pool.groups', { selector: '.ant-select-selection-item' })
  expect(screen.getByText('Free pool', { selector: '.ant-select-selection-item' })).toBeTruthy()
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).not.toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/source-models', expect.anything(), expect.anything())
  await select('hub.upstreamSource', 'hub.gatewayDefault')
  await screen.findByText('hub.gatewayDefaultHint')
  expect(screen.queryByRole('combobox', { name: 'hub.tab.catalog' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind: 'claude', model: 'roami-default', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
})
it.each(['pi', 'opencode'] as const)('excludes disabled groups when checking the synced %s catalog', async kind => {
  const group = { ...models[0], id: 'free-pool', name: 'Free pool', aggregate: true, strategy: 'smart' }
  const active = [...models, group], disabled = { ...group, id: 'disabled-pool', enabled: false }
  const profile = { ...view.profiles[0], models: [{ id: 'roami-default', name: 'Roami Default' }, ...active.map(({ id, name }) => ({ id, name }))] }
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models: [...active, disabled], baseUrl: profile.baseUrl, defaultModel: group.id } })
  render(<App><GatewayModelBinding kind={kind} view={{ ...view, profiles: [profile], current: { model: group.id } }} onChanged={async () => {}} /></App>)
  await screen.findByText('Free pool', { selector: '.ant-select-selection-item' })
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByText('hub.gatewayCatalogChanged')).toBeNull()
})
