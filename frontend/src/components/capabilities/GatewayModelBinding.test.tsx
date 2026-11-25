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
const catalog = { revision: 'catalog-r1', sources, models, drafts: [], uses: {}, baseUrl: 'http://127.0.0.1:19000' }
const official = { mode: 'official', profiles: [] as AgentModelView['profiles'], current: {}, activeId: undefined } as const
const view: AgentModelView = { mode: 'custom', profiles: [{ id: 'active', name: 'Roami Gateway', model: 'model-a', baseUrl: 'http://127.0.0.1:19000', protocol: 'anthropic-messages', authMode: 'bearer', hasKey: true, applied: true }], current: { model: 'model-a', provider: 'Roami Gateway' }, activeId: 'active', revision: 'native-r1', changed: false, canRestore: true, configPaths: [] }
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.mocked(api).mockResolvedValue({ data: catalog })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
const mount = (current = view, installed = true) => { const changed = vi.fn(async () => {}); render(<App><GatewayModelBinding kind="claude" view={current} installed={installed} onChanged={changed} /></App>); return changed }
const select = async (option: string) => {
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'modelUsage.model' }))
  fireEvent.click(await screen.findByText(option, { selector: '.ant-select-item-option-content' }))
}
it('allows applying a direct native preset that already matches a saved source and model', async () => {
  mount({ ...view, profiles: [{ ...view.profiles[0], name: 'Native preset', baseUrl: sources[0].baseUrl + '/v1', model: 'upstream-a' }], current: { provider: 'Native preset', model: 'upstream-a' } })
  await screen.findByText('Model a', { selector: '.ant-select-selection-item' })
  expect(screen.getByText('hub.directConnection')).toBeTruthy()
  expect(screen.queryByText('hub.gatewayCurrent')).toBeNull()
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind: 'claude', model: 'model-a', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
})
it('marks a matching gateway profile as applied', async () => {
  mount({ ...view, profiles: [{ ...view.profiles[0], baseUrl: view.profiles[0].baseUrl + '/v1/' }] })
  await screen.findByText('Model a', { selector: '.ant-select-selection-item' })
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByText('hub.directConnection')).toBeNull()
  expect(screen.getByText('hub.gatewayCurrent')).toBeTruthy()
})
it.each(['upstream-a', 'model-a'])('does not match a direct preset to a different protocol or a gateway alias: %s', async model => {
  mount({ ...view, profiles: [{ ...view.profiles[0], baseUrl: sources[0].baseUrl, protocol: 'openai-completions', model }], current: { provider: 'Native preset', model } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('GET', '/agent/model-gateway/catalog', undefined, expect.anything()))
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'modelUsage.model' })).not.toHaveProperty('disabled', true))
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).not.toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/source-models', expect.anything(), expect.anything())
})

it.each(['claude', 'codex', 'opencode', 'pi'] as const)('applies the gateway default to %s without selecting or fetching a source', async kind => {
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models, drafts: [], uses: {}, baseUrl: view.profiles[0].baseUrl, defaultModel: 'model-b' } })
  render(<App><GatewayModelBinding kind={kind} view={{ ...view, ...official }} onChanged={async () => {}} /></App>)
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.custom' }))
  await screen.findByText('hub.gatewayDefaultHint')
  await waitFor(() => expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.getByRole('combobox', { name: 'modelUsage.model' })).toBeTruthy()
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
  expect(await screen.findByText('Model b', { selector: '.ant-select-selection-item' })).toBeTruthy()
})
it('lists models across sources and aggregates while excluding unavailable routes and drafts', async () => {
  const group = { ...models[0], id: 'group', name: 'Routing group', aggregate: true }
  const hidden = { ...models[0], id: 'hidden', name: 'Hidden member', gatewayHidden: true }
  const disabled = { ...models[0], id: 'disabled', name: 'Disabled model', enabled: false }
  const draft = { ...models[0], id: 'draft', name: 'Unpublished model' }
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, models: [...models, group, hidden, disabled], drafts: [draft] } })
  mount()
  await screen.findByText('Model a', { selector: '.ant-select-selection-item' })
  expect(screen.queryByRole('combobox', { name: 'hub.upstreamSource' })).toBeNull()
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'modelUsage.model' }))
  const list = await screen.findByRole('listbox')
  expect(within(list).getAllByRole('option').map(option => option.textContent)).toEqual(['Model a', 'Model b', 'Routing group'])
  expect(api).not.toHaveBeenCalledWith('POST', expect.stringContaining('/source-models'), expect.anything(), expect.anything())
})

it('uses a real factory-mode action instead of restoring an old third-party connection', async () => {
  const changed = mount(); await screen.findByText('Model a', { selector: '.ant-select-selection-item' })
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.official' }))
  expect(screen.queryByRole('combobox', { name: 'modelUsage.model' })).toBeNull()
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

it('shows an empty state until the gateway has a selectable model', async () => {
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, models: [] } })
  mount({ ...view, ...official })
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.custom' }))
  await screen.findByText('gatewayWorkspace.noCallable')
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByRole('link', { name: 'hub.manageSources' })).toBeTruthy()
})

it.each(['claude', 'codex', 'opencode', 'pi'])('applies a published Chat Completions model by route ID to %s', async kind => {
  const alias = 'coding-gateway'
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, models: [{ ...models[0], protocol: 'openai-completions', gatewayAlias: alias }] } })
  render(<App><GatewayModelBinding kind={kind} view={{ ...view, ...official }} onChanged={async () => {}} /></App>)
  fireEvent.click(screen.getByRole('radio', { name: 'hub.mode.custom' }))
  const field = screen.getByRole('combobox', { name: 'modelUsage.model' })
  await waitFor(() => expect(field).not.toHaveProperty('disabled', true))
  fireEvent.mouseDown(field)
  fireEvent.change(field, { target: { value: 'unpublished/model' } })
  expect(screen.queryByRole('option')).toBeNull()
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(field, { target: { value: alias } })
  fireEvent.click(await screen.findByRole('option', { name: 'Model a' }))
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.apply' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.models.apply' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/apply', { kind, model: 'model-a', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
})

it.each(['pi', 'opencode'] as const)('allows syncing a changed gateway catalog to %s without losing the current model', async kind => {
  const profile = { ...view.profiles[0], models: models.map(model => ({ id: model.id, name: model.name })) }
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models, baseUrl: profile.baseUrl } })
  const mounted = render(<App><GatewayModelBinding kind={kind} view={{ ...view, profiles: [profile] }} onChanged={async () => {}} /></App>)
  await screen.findByText('Model a', { selector: '.ant-select-selection-item' })
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  mounted.rerender(<App><GatewayModelBinding kind={kind} view={{ ...view, profiles: [{ ...profile, models: [] }] }} onChanged={async () => {}} /></App>)
  expect(screen.getByText('hub.gatewayCatalogChanged')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'capabilities.models.apply' }) as HTMLButtonElement).disabled).toBe(false)
  expect(screen.getByText('Model a', { selector: '.ant-select-selection-item' })).toBeTruthy()
})


it('recognizes a Claude routing group alias and preserves the gateway default entry', async () => {
  const group = { ...models[0], id: 'pool-id', gatewayAlias: 'free-pool', name: 'Free pool', aggregate: true, strategy: 'smart' }
  vi.mocked(api).mockResolvedValue({ data: { revision: 'catalog-r1', sources, models: [...models, group], baseUrl: view.profiles[0].baseUrl, defaultModel: group.id } })
  mount({ ...view, current: { model: 'roami-claude/free-pool[1m]' } })
  expect(await screen.findByText('Free pool', { selector: '.ant-select-selection-item' })).toBeTruthy()
  expect((screen.getByRole('button', { name: 'capabilities.models.applied' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).not.toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/source-models', expect.anything(), expect.anything())
  await select('hub.gatewayDefault')
  await screen.findByText('hub.gatewayDefaultHint')
  expect(screen.getByRole('combobox', { name: 'modelUsage.model' })).toBeTruthy()
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
