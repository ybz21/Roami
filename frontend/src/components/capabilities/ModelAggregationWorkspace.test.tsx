// @vitest-environment jsdom
import { installRadixTestEvents } from '../ui/radix-test-events'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
beforeEach(() => { installRadixTestEvents(); window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })); vi.mocked(api).mockImplementation(async (method, path) => method === 'POST' ? { data: { sourceId: 'a', model: 'native-a', quality: 'pass' } } : path.includes('/monitor?') ? { data: { now: Date.now(), hours: 24, totals, sources: [{ sourceId: 'a', totals }], models: { a: { 'native-a': true } }, points: [], events: [], storage: { records: 2, maxRecords: 10000, bytes: 40960000, maxBytes: 67108864, expired: 0, evicted: 0, dropped: 0, retentionHours: 24 } } } : { data: { available: 0, channels: [] } }) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const pick = async (label: string, option: string) => { fireEvent.keyDown(screen.getByRole('combobox', { name: label }), { key: 'ArrowDown' }); fireEvent.keyDown(await screen.findByRole('option', { name: option }), { key: 'Enter' }) }
it('requires source before model and saves a smart pool with cross-source candidates', async () => {
  const save = vi.fn(async () => true), props = { active: true, catalog, busy: false, error: '', save, retry: vi.fn(), onSource: vi.fn() }
  const mounted = render(<App><ModelAggregationWorkspace {...props} /></App>)
  fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
  expect(screen.queryByRole('region', { name: 'pool.preview' })).toBeNull()
  expect(screen.queryByRole('checkbox', { name: 'native-a' })).toBeNull()
  fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Free pool' } })
  fireEvent.click(document.querySelector('.tt-aggregate-more summary')!)
  fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'free-main' } })
  await pick('pool.source', 'Source A'); fireEvent.click(screen.getByRole('checkbox', { name: 'native-a' }))
  await pick('pool.source', 'Source B'); expect(screen.queryByRole('checkbox', { name: 'native-a' })).toBeNull()
  fireEvent.click(screen.getByRole('checkbox', { name: 'native-b' }))
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
  fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
  expect((screen.getByLabelText('pool.modelId') as HTMLInputElement).disabled).toBe(false)
  fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'renamed' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'renamed', aliases: ['old'] })]) })))
})

it('only selects models saved in the source, never an upstream directory or aggregate references', async () => {
 const approved = { ...catalog.models[0], id: 'approved', name: 'Approved', candidates: [{ sourceId: 'a', model: 'approved' }] }
 const otherPool = { ...approved, id: 'other-pool', aggregate: true, candidates: [{ sourceId: 'a', model: 'aggregate-only' }] }
 const backup = { ...catalog.models[1], id: 'backup-route', candidates: [{ sourceId: 'b', model: 'native-b' }, { sourceId: 'a', model: 'backup-only' }] }
 vi.mocked(api).mockResolvedValue({ data: { models: ['upstream-only'] } })
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, approved, otherPool, backup] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
 expect(document.querySelector('.tt-aggregate-more')?.hasAttribute('open')).toBe(false)
 fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Free pool' } })
 await pick('pool.source', 'Source A')
 expect(screen.queryByRole('checkbox', { name: /upstream-only|aggregate-only|backup-only/ })).toBeNull()
 expect(api).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('checkbox', { name: 'pool.selectAll' }))
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ name: 'Free pool', id: expect.any(String), strategy: 'smart', freeOnly: true, candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'a', model: 'approved' }] })]) })))
})

it('updates the routing preview and persists manual priority without detaching weights', async () => {
 const candidates = [{ sourceId: 'a', model: 'first' }, { sourceId: 'b', model: 'second' }]
 const pool = { id: 'ordered', name: 'Ordered', aggregate: true, protocol: 'openai-completions', strategy: 'order' as const, candidates, weights: { 'a/first': 3 } }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.routing' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 expect(screen.getByRole('checkbox', { name: 'pool.freeOnly' }).getAttribute('aria-checked')).toBe('false')
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.routing' }))
 fireEvent.keyDown(screen.getAllByRole('button', { name: 'pool.dragMember' })[0], { key: 'ArrowDown' })
 expect(document.querySelector('.tt-member-identity>strong')?.textContent).toBe('second')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'ordered', candidates: [candidates[1], candidates[0]], weights: { 'a/first': 3 } })]) })))
})


it('uses only the saved ID for live member status and runtime while editing', async () => {
 const a = { id: 'pool-a', name: 'Pool Alpha', aggregate: true, protocol: 'openai-completions', strategy: 'smart' as const, candidates: [{ sourceId: 'a', model: 'native-a' }] }
 const b = { ...a, id: 'pool-b', name: 'Pool Beta', candidates: [{ sourceId: 'b', model: 'native-b' }] }
 vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.includes('/routing?') ? { now: Date.now(), available: 1, channels: [{ sourceId: 'a', model: 'live-native-a', account: '', kind: 'key', ready: true, remaining: 100, resetAt: null, expiresAt: null, restUntil: null, measuredAt: null, recentTokens: 0 }] } : { models: [] } }))
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, a, b] }} busy={false} error="" save={vi.fn(async () => true)} retry={vi.fn()} onSource={vi.fn()} /></App>)
 expect(api).not.toHaveBeenCalled()
 fireEvent.click(within(screen.getByRole('region', { name: 'Pool Alpha' })).getByRole('button', { name: 'pool.open' }))
 expect(vi.mocked(api).mock.calls.filter(([, path]) => path.includes('/routing?'))).toHaveLength(1)
 fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'unsaved-name' } })
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.runtime' }))
 expect(await screen.findByText('live-native-a')).toBeTruthy()
 expect(vi.mocked(api).mock.calls.filter(([, path]) => path.includes('/routing?')).map(([, path]) => path)).toEqual(expect.arrayContaining(['/agent/model-gateway/catalog/routing?model=pool-a']))
 expect(vi.mocked(api).mock.calls.some(([, path]) => path.includes('model=unsaved-name'))).toBe(false)
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.routing' }))
 expect(screen.queryByText('live-native-a')).toBeNull()
 fireEvent.click(document.querySelector('.tt-aggregate-detail .tt-back')!)
 expect(screen.queryByRole('region', { name: 'pool.preview' })).toBeNull()
})

it('uses a full detail editor and keeps the draft when returning to the list or switching tabs', async () => {
 const pool = { id: 'owned', name: 'Owned pool', aggregate: true, protocol: 'openai-completions', strategy: 'rotate' as const, candidates: [{ sourceId: 'a', model: 'native-a' }] }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 expect(screen.queryByRole('region', { name: 'Owned pool' })).toBeNull()
 expect(document.querySelector('.tt-model-hub-detail')).toBeNull()
 fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'renamed-id' } })
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.routing' }))
 expect(screen.getByRole('region', { name: 'pool.preview' })).toBeTruthy()
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 expect((screen.getByLabelText('pool.modelId') as HTMLInputElement).value).toBe('renamed-id')
 fireEvent.click(document.querySelector('.tt-aggregate-detail .tt-back')!)
 expect(screen.getByText('pool.unsaved')).toBeTruthy()
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 expect((screen.getByLabelText('pool.modelId') as HTMLInputElement).value).toBe('renamed-id')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'renamed-id', aliases: ['owned'] })]) })))
})

it('selects search matches directly, preserves other sources and removes unchecked members', async () => {
 vi.mocked(api).mockResolvedValue({ data: { available: 0, channels: [], models: ['native-a', 'match-a', 'match-b', 'other'] } })
 const pool = { id: 'pool', name: 'Pool', aggregate: true, protocol: 'openai-completions', strategy: 'smart' as const, candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'b', model: 'native-b' }] }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, ...['match-a', 'match-b', 'other'].map(id => ({ ...catalog.models[0], id, candidates: [{ sourceId: 'a', model: id }] })), pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 await screen.findByRole('checkbox', { name: 'match-a' })
 fireEvent.change(screen.getByRole('textbox', { name: 'hub.directory.search' }), { target: { value: 'match' } })
 fireEvent.click(screen.getByRole('checkbox', { name: 'hub.directory.selectMatches' }))
 fireEvent.click(screen.getByRole('checkbox', { name: 'match-a' }))
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'b', model: 'native-b' }, { sourceId: 'a', model: 'match-b' }] })]) })))
})

it('blocks oversized bulk selection without truncating it and permits a narrower search', async () => {
 vi.mocked(api).mockResolvedValue({ data: { available: 0, channels: [], models: Array.from({ length: 65 }, (_, i) => 'entry-' + i) } })
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, ...Array.from({ length: 65 }, (_, i) => ({ ...catalog.models[0], id: 'entry-' + i, candidates: [{ sourceId: 'a', model: 'entry-' + i }] }))] }} busy={false} error="" save={vi.fn(async () => true)} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
 await pick('pool.source', 'Source A')
 await screen.findByRole('checkbox', { name: 'entry-0' })
 expect((screen.getByRole('checkbox', { name: 'pool.selectAll' }) as HTMLInputElement).disabled).toBe(true)
 expect(screen.getByRole('checkbox', { name: 'entry-0' }).getAttribute('aria-checked')).toBe('false')
 fireEvent.change(screen.getByRole('textbox', { name: 'hub.directory.search' }), { target: { value: 'entry-1' } })
 fireEvent.click(screen.getByRole('checkbox', { name: 'hub.directory.selectMatches' }))
 expect(screen.getByRole('checkbox', { name: 'entry-1' }).getAttribute('aria-checked')).toBe('true')
})

it('resumes a new draft from the list and keeps failed saves editable', async () => {
 const save = vi.fn(async () => false)
 render(<App><ModelAggregationWorkspace active catalog={catalog} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
 fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Draft name' } })
 await pick('pool.source', 'Source A')
 fireEvent.click(screen.getByRole('checkbox', { name: 'native-a' }))
 fireEvent.click(document.querySelector('.tt-aggregate-detail .tt-back')!)
 fireEvent.click(screen.getByRole('button', { name: 'pool.resumeCreate' }))
 expect((screen.getByLabelText('pool.name') as HTMLInputElement).value).toBe('Draft name')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalled())
 expect((screen.getByLabelText('pool.name') as HTMLInputElement).value).toBe('Draft name')
 expect(screen.getByRole('checkbox', { name: 'native-a' }).getAttribute('aria-checked')).toBe('true')
})

it('keeps separate drafts for different cards and puts management actions in the detail', () => {
 const a = { id: 'alpha', name: 'Alpha', aggregate: true, protocol: 'openai-completions', strategy: 'smart' as const, candidates: [{ sourceId: 'a', model: 'native-a' }] }
 const b = { ...a, id: 'beta', name: 'Beta' }
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, a, b] }} busy={false} error="" save={vi.fn(async () => true)} retry={vi.fn()} onSource={vi.fn()} /></App>)
 expect(screen.queryByRole('button', { name: 'capabilities.models.deleteAction' })).toBeNull()
 fireEvent.click(within(screen.getByRole('region', { name: 'Alpha' })).getByRole('button', { name: 'pool.open' }))
 fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Alpha draft' } })
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 expect(screen.getByRole('button', { name: 'capabilities.models.deleteAction' })).toBeTruthy()
 fireEvent.click(document.querySelector('.tt-aggregate-detail .tt-back')!)
 fireEvent.click(within(screen.getByRole('region', { name: 'Beta' })).getByRole('button', { name: 'pool.open' }))
 fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Beta draft' } })
 fireEvent.click(document.querySelector('.tt-aggregate-detail .tt-back')!)
 fireEvent.click(within(screen.getByRole('region', { name: 'Alpha' })).getByRole('button', { name: 'pool.open' }))
 expect((screen.getByLabelText('pool.name') as HTMLInputElement).value).toBe('Alpha draft')
})

it('reviews and removes selected models across sources without changing the others', async () => {
 const pool = { id: 'all', name: 'All', aggregate: true, protocol: 'openai-completions', strategy: 'smart' as const, candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'b', model: 'native-b' }] }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 fireEvent.click(screen.getByRole('button', { name: 'orchestration.reviewSelected' }))
 expect(document.querySelector('.tt-aggregate-members .tt-model-directory-heading [role=status]')).toBeNull()
 expect(screen.getByRole('checkbox', { name: 'orchestration.selectAllMembers' })).toBeTruthy()
 fireEvent.click(screen.getByRole('checkbox', { name: /native-b/ }))
 expect(screen.getByRole('checkbox', { name: /native-a/ }).getAttribute('aria-checked')).toBe('true')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'all', candidates: [{ sourceId: 'a', model: 'native-a' }] })]) })))
})

it('shows field-specific errors and focuses the invalid field without sending a save', () => {
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={catalog} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
 fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'not a valid id' } })
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 expect(screen.getByText('orchestration.nameRequired')).toBeTruthy()
 expect(screen.getByText('orchestration.idInvalid')).toBeTruthy()
 expect(screen.getByLabelText('pool.name').getAttribute('aria-invalid')).toBe('true')
 expect(document.activeElement).toBe(screen.getByLabelText('pool.name'))
 expect(save).not.toHaveBeenCalled()
})

it('keeps legacy unconfigured members visible for explicit removal instead of treating them as source choices', async () => {
 const pool = { id: 'legacy', name: 'Legacy', aggregate: true, protocol: 'openai-completions', strategy: 'smart' as const, candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'a', model: 'orphan' }], weights: { 'a/native-a': 3, 'a/orphan': 2 } }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 expect(document.querySelectorAll('.tt-member-status')[1]?.textContent).toBe('orchestration.sourceNotEnabled')
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 expect(screen.getByText('orchestration.unconfiguredMembers')).toBeTruthy()
 expect(screen.queryByRole('checkbox', { name: /orphan/ })).toBeNull()
 fireEvent.click(screen.getByRole('button', { name: 'orchestration.reviewSelected' }))
 expect(screen.getByRole('checkbox', { name: /orphan/ }).getAttribute('aria-checked')).toBe('true')
 expect(save).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('checkbox', { name: /orphan/ }))
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'legacy', candidates: [{ sourceId: 'a', model: 'native-a' }], weights: { 'a/native-a': 3 } })]) })))
})
