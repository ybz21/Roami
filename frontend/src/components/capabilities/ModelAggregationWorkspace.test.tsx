// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import ModelAggregationWorkspace from './ModelAggregationWorkspace'
import ModelMonitoringWorkspace from './ModelMonitoringWorkspace'
import type { ModelCatalog } from './model-hub-api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false, keyboard: 0 }) }))
const catalog: ModelCatalog = { revision: 'r1', sources: [{ id: 'a', name: 'Source A', baseUrl: 'https://a.example', protocol: 'openai-completions', authMode: 'bearer' }, { id: 'b', name: 'Source B', baseUrl: 'https://b.example', protocol: 'openai-completions', authMode: 'bearer' }], models: [{ id: 'model-a', name: 'A', strategy: 'fixed', protocol: 'openai-completions', candidates: [{ sourceId: 'a', model: 'native-a' }] }, { id: 'model-b', name: 'B', strategy: 'fixed', protocol: 'openai-completions', candidates: [{ sourceId: 'b', model: 'native-b' }] }], drafts: [], baseUrl: '', uses: {} }
const totals = { requests: 2, failed: 0, success: 1, firstTokenP95: 123, outputP50: 45, quality: null, graded: 0 }
beforeEach(() => { window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })); vi.mocked(api).mockImplementation(async (method, path) => method === 'POST' ? { data: { sourceId: 'a', model: 'native-a', quality: 'pass' } } : path.includes('/monitor?') ? { data: { now: Date.now(), hours: 24, totals, sources: [{ sourceId: 'a', totals }], models: { a: { 'native-a': true } }, points: [], events: [], storage: { records: 2, maxRecords: 10000, bytes: 40960000, maxBytes: 67108864, expired: 0, evicted: 0, dropped: 0, retentionHours: 24 } } } : { data: { available: 0, channels: [] } }) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const pick = async (label: string, option: string) => { fireEvent.mouseDown(screen.getByRole('combobox', { name: label })); fireEvent.click(await screen.findByTitle(option)) }
it('requires source before model and saves a smart pool with cross-source candidates', async () => {
  const save = vi.fn(async () => true), props = { active: true, catalog, busy: false, error: '', save, retry: vi.fn(), onSource: vi.fn() }
  const mounted = render(<App><ModelAggregationWorkspace {...props} /></App>)
  fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
  expect(screen.getByRole('region', { name: 'pool.preview' })).toBeTruthy()
  expect((screen.getByRole('combobox', { name: 'pool.model' }) as HTMLInputElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Free pool' } })
  fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'free-main' } })
  await pick('pool.source', 'Source A'); await pick('pool.model', 'native-a'); fireEvent.click(screen.getByRole('button', { name: 'pool.addMember' }))
  await pick('pool.source', 'Source B'); expect((screen.getByRole('combobox', { name: 'pool.model' }) as HTMLInputElement).value).toBe('')
  await pick('pool.model', 'native-b'); fireEvent.click(screen.getByRole('button', { name: 'pool.addMember' }))
  mounted.rerender(<App><ModelAggregationWorkspace {...props} active={false} /></App>); mounted.rerender(<App><ModelAggregationWorkspace {...props} /></App>)
  expect((screen.getByLabelText('pool.name') as HTMLInputElement).value).toBe('Free pool')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'free-main', aggregate: true, strategy: 'smart', freeOnly: true, candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'b', model: 'native-b' }] })]) })))
})
it('does not send probes until requested and keeps unknown quality out of the pass rate', async () => {
  const mounted = render(<App><ModelMonitoringWorkspace active={false} catalog={catalog} /></App>); expect(api).not.toHaveBeenCalled()
  mounted.rerender(<App><ModelMonitoringWorkspace active catalog={catalog} /></App>)
  await screen.findByText('monitor.storage')
  expect(screen.getAllByText('monitor.pending').length).toBeGreaterThan(0)
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'POST')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'monitor.detail Source A' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('GET', expect.stringContaining('sourceId=a'), undefined, expect.anything()))
  fireEvent.click(screen.getByRole('button', { name: 'monitor.runCheck' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/monitor/check', { sourceId: 'a', model: 'native-a', rule: 'answer' }, expect.anything()))
  expect(await screen.findByText(/monitor.checkPassed/)).toBeTruthy()
})

it('renames an existing pool while preserving compatibility aliases', async () => {
  const pool = { id: 'old', name: 'Pool', aggregate: true, protocol: 'openai-completions', strategy: 'smart' as const, candidates: [{ sourceId: 'a', model: 'native-a' }] }
  const save = vi.fn(async () => true)
  render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
  fireEvent.click(screen.getByRole('button', { name: 'hub.configure' }))
  expect((screen.getByLabelText('pool.modelId') as HTMLInputElement).disabled).toBe(false)
  fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'renamed' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'renamed', aliases: ['old'] })]) })))
})

it('selects all models in a source, deduplicates and can select only advertised free models', async () => {
  vi.mocked(api).mockResolvedValue({ data: { models: ['native-a', 'free-b', 'paid-c'], details: [{ id: 'native-a', inputPrice: 0, outputPrice: 0 }, { id: 'free-b', inputPrice: 0, outputPrice: 0 }, { id: 'paid-c', inputPrice: 1, outputPrice: 2 }] } })
  const save = vi.fn(async () => true)
  render(<App><ModelAggregationWorkspace active catalog={catalog} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
  fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
  fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Free pool' } })
  await pick('pool.source', 'Source A')
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', expect.stringContaining('/discover'), expect.objectContaining({ source: catalog.sources[0] }), expect.anything()))
  fireEvent.click(screen.getByRole('checkbox', { name: 'directory.free' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'pool.selectAll' }))
  fireEvent.click(screen.getByRole('button', { name: 'pool.addMember' }))
  expect((screen.getByRole('checkbox', { name: 'pool.selectAll' }) as HTMLInputElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'a', model: 'free-b' }] })]) })))
})

it('updates the routing preview and persists manual priority without detaching weights', async () => {
 const candidates = [{ sourceId: 'a', model: 'first' }, { sourceId: 'b', model: 'second' }]
 const pool = { id: 'ordered', name: 'Ordered', aggregate: true, protocol: 'openai-completions', strategy: 'order' as const, candidates, weights: { 'a/first': 3 } }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'hub.configure' }))
 expect((screen.getByRole('checkbox', { name: 'pool.freeOnly' }) as HTMLInputElement).checked).toBe(false)
 fireEvent.keyDown(screen.getAllByRole('button', { name: 'pool.dragMember' })[0], { key: 'ArrowDown' })
 expect(document.querySelector('.tt-member-identity>strong')?.textContent).toBe('second')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'ordered', candidates: [candidates[1], candidates[0]], weights: { 'a/first': 3 } })]) })))
})
