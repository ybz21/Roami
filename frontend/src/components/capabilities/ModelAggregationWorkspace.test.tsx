// @vitest-environment jsdom
import { installRadixTestEvents } from '../ui/radix-test-events'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from 'antd'
import { useState, type ComponentProps } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import AggregationWorkspace from './ModelAggregationWorkspace'
import ModelMonitoringWorkspace from './ModelMonitoringWorkspace'
import type { ModelCatalog } from './model-hub-api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false, keyboard: 0 }) }))
const catalog: ModelCatalog = { revision: 'r1', sources: [{ id: 'a', name: 'Source A', baseUrl: 'https://a.example', protocol: 'openai-completions', authMode: 'bearer' }, { id: 'b', name: 'Source B', baseUrl: 'https://b.example', protocol: 'openai-completions', authMode: 'bearer' }], models: [{ id: 'model-a', name: 'A', strategy: 'fixed', protocol: 'openai-completions', candidates: [{ sourceId: 'a', model: 'native-a' }] }, { id: 'model-b', name: 'B', strategy: 'fixed', protocol: 'openai-completions', candidates: [{ sourceId: 'b', model: 'native-b' }] }], drafts: [], baseUrl: '', uses: {} }
const requestNav = { onRequest: vi.fn(), onRequestLimits: vi.fn() }
function ModelAggregationWorkspace(props: Omit<ComponentProps<typeof AggregationWorkspace>, 'onOpenRequested' | 'onCloseRequested'>) {
  const [route, setRoute] = useState<{ pool: string; section?: string } | null>(null)
  return <AggregationWorkspace {...props} requestedPool={route?.pool} requestedSection={route?.section}
    onOpenRequested={(pool, section) => setRoute({ pool, section })} onCloseRequested={() => setRoute(null)} />
}
const totals = { requests: 2, failed: 0, success: 1, firstTokenP95: 123, outputP50: 45, quality: null, graded: 0 }
beforeEach(() => { installRadixTestEvents(); window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })); vi.mocked(api).mockImplementation(async (method, path) => method === 'POST' ? { data: { sourceId: 'a', model: 'native-a', quality: 'pass' } } : path.includes('view=request-summary') ? { data: { totals: { requests: 0 }, points: [], outcomes: {}, range: { from: 0, to: 1 }, byModel: [], routes: {}, callers: {} } } : path.includes('/monitor?') ? { data: { now: Date.now(), hours: 24, totals, sources: [{ sourceId: 'a', totals }], models: { a: { 'native-a': true } }, points: [], events: [], storage: { records: 2, maxRecords: 10000, bytes: 40960000, maxBytes: 67108864, expired: 0, evicted: 0, dropped: 0, retentionHours: 24 } } } : { data: { available: 0, channels: [] } }) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const pick = async (_label: string, option: string) => { fireEvent.click(screen.getByRole('button', { name: option })) }
it('requires source before model and saves a smart pool with cross-source candidates', async () => {
  const save = vi.fn(async () => true), props = { active: true, catalog, busy: false, error: '', save, retry: vi.fn(), onSource: vi.fn() }
  const mounted = render(<App><ModelAggregationWorkspace {...requestNav} {...props} /></App>)
  fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
  expect(screen.queryByRole('region', { name: 'pool.preview' })).toBeNull()
  expect(screen.getByRole('checkbox', { name: 'native-a' }).getAttribute('aria-checked')).toBe('false')
  expect(screen.queryByRole('textbox', { name: 'hub.directory.search' })).toBeNull()
  expect(screen.queryByRole('checkbox', { name: 'pool.selectAll' })).toBeNull()
  fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Free pool' } })
  fireEvent.change(screen.getByLabelText('hub.gatewayAlias'), { target: { value: 'team-free' } })
  fireEvent.click(screen.getByRole('checkbox', { name: 'pool.hideMembers' }))
  expect(screen.getByText('pool.hideMembersHint')).toBeTruthy()
  fireEvent.click(document.querySelector('.tt-aggregate-more summary')!)
  fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'free-main' } })
  await pick('pool.source', 'Source A'); fireEvent.click(screen.getByRole('checkbox', { name: 'native-a' }))
  await pick('pool.source', 'Source B'); expect(screen.queryByRole('checkbox', { name: 'native-a' })).toBeNull()
  fireEvent.click(screen.getByRole('checkbox', { name: 'native-b' }))
  mounted.rerender(<App><ModelAggregationWorkspace {...requestNav} {...props} active={false} /></App>); mounted.rerender(<App><ModelAggregationWorkspace {...requestNav} {...props} /></App>)
  expect((screen.getByLabelText('pool.name') as HTMLInputElement).value).toBe('Free pool')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'free-main', gatewayAlias: 'team-free', hideMembers: true, aggregate: true, strategy: 'smart', candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'b', model: 'native-b' }] })]) })))
})
it('does not send probes until requested and keeps unknown quality out of the pass rate', async () => {
  const mounted = render(<App><ModelMonitoringWorkspace active={false} catalog={catalog} /></App>); expect(api).not.toHaveBeenCalled()
  mounted.rerender(<App><ModelMonitoringWorkspace active catalog={catalog} /></App>)
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'monitor.sources' }))
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
  render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
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
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, approved, otherPool, backup] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
 expect(document.querySelector('.tt-aggregate-more')?.hasAttribute('open')).toBe(false)
 fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Free pool' } })
 await pick('pool.source', 'Source A')
 expect(screen.queryByRole('checkbox', { name: /upstream-only|aggregate-only|backup-only/ })).toBeNull()
 expect(api).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('checkbox', { name: 'pool.selectAll' }))
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ name: 'Free pool', id: expect.any(String), strategy: 'smart', candidates: [{ sourceId: 'a', model: 'native-a' }, { sourceId: 'a', model: 'approved' }] })]) })))
})

it('updates the routing preview and persists manual priority without detaching weights', async () => {
 const candidates = [{ sourceId: 'a', model: 'first' }, { sourceId: 'b', model: 'second' }]
 const pool = { id: 'ordered', name: 'Ordered', aggregate: true, protocol: 'openai-completions', strategy: 'order' as const, candidates, weights: { 'a/first': 3 } }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.routing' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 expect(screen.getByRole('checkbox', { name: 'pool.filterFree' }).getAttribute('aria-checked')).toBe('false')
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.routing' }))
 fireEvent.keyDown(screen.getAllByRole('button', { name: 'pool.dragMember' })[0], { key: 'ArrowDown' })
 expect(document.querySelector('.tt-member-identity>strong')?.textContent).toBe('second')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'ordered', candidates: [candidates[1], candidates[0]], weights: { 'a/first': 3 } })]) })))
})

it('filters member choices by confirmed free models while keeping selected paid members', async () => {
 const paid = { sourceId: 'a', model: 'native-a' }, free = { sourceId: 'a', model: 'free-model' }
 const approved = { ...catalog.models[0], id: 'confirmed-free', candidates: [free] }
 vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.includes('/models?free=true') ? {
   revision: catalog.revision, models: [{ ...approved, kind: 'single', configured: true, enabled: true }],
 } : { models: [] } }))
 const save = vi.fn(async (_catalog: ModelCatalog) => true)
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, approved] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
 fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'WB DS' } })
 fireEvent.click(screen.getByRole('checkbox', { name: 'native-a' }))
 fireEvent.click(screen.getByRole('checkbox', { name: 'pool.filterFree' }))
 expect(await screen.findByRole('checkbox', { name: 'free-model' })).toBeTruthy()
 expect(screen.queryByRole('checkbox', { name: 'native-a' })).toBeNull()
 expect(within(screen.getByRole('list', { name: 'orchestration.selectedPool' })).getByText('native-a')).toBeTruthy()
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledTimes(1))
 const pool = save.mock.calls[0][0].models.find(row => row.name === 'WB DS')
 expect(pool?.candidates).toEqual([paid])
 expect(pool).not.toHaveProperty('freeOnly')
})


it('shows saved routing order alongside the existing editor with one status request', async () => {
 const a = { sourceId: 'a', model: 'native-a' }, b = { sourceId: 'b', model: 'native-b' }, blocked = { sourceId: 'a', model: 'no-tools' }
 const pool = { id: 'pool-a', name: 'Pool Alpha', aggregate: true, protocol: 'openai-completions', strategy: 'smart' as const, candidates: [a, b, blocked] }
 const channel = { kind: 'key', ready: true, remaining: 100, resetAt: null, expiresAt: null, restUntil: null, measuredAt: null, recentTokens: 0 }
 vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.includes('/routing?') ? {
   now: Date.now(), available: 3, members: [a, b, { ...blocked, block: 'tools' }],
   channels: [{ ...channel, ...b, account: 'first' }, { ...channel, ...b, account: 'second' }, { ...channel, ...a, account: '' }],
 } : { models: [] } }))
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={vi.fn(async () => true)} retry={vi.fn()} onSource={vi.fn()} /></App>)
 expect(api).not.toHaveBeenCalled()
 fireEvent.click(within(screen.getByRole('region', { name: 'Pool Alpha' })).getByRole('button', { name: 'pool.open' }))
 expect(vi.mocked(api).mock.calls.filter(([, path]) => path.includes('/routing?'))).toHaveLength(1)
 fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'unsaved-name' } })
 expect(screen.queryByRole('tab', { name: 'pool.runtime' })).toBeNull()
 const status = (await screen.findByText('pool.runtimeOrder')).closest('section')!
 expect([...status.querySelectorAll('.tt-pool-route strong')].map(row => row.textContent)).toEqual(['native-b', 'native-a'])
 status.querySelector('details')!.open = true
 expect([...status.querySelectorAll('.tt-routing-channel strong')].map(row => row.textContent)).toEqual(['native-b', 'native-a', 'no-tools'])
 expect(within(status).getAllByText('pool.runtimeRank')).toHaveLength(2)
 expect(within(status).getByText('orchestration.routingBlock.tools')).toBeTruthy()
 expect(within(status).getByText('pool.savedRuntime')).toBeTruthy()
 expect(document.querySelector('.tt-member-identity>strong')?.textContent).toBe('native-a')
 expect(vi.mocked(api).mock.calls.filter(([, path]) => path.includes('/routing?')).map(([, path]) => path)).toEqual(['/agent/model-gateway/catalog/routing?model=pool-a'])
 fireEvent.click(document.querySelector('.tt-aggregate-detail .tt-back')!)
 expect(screen.queryByRole('region', { name: 'pool.preview' })).toBeNull()
})

it('uses a full detail editor and keeps the draft when returning to the list or switching tabs', async () => {
 const pool = { id: 'owned', name: 'Owned pool', aggregate: true, protocol: 'openai-completions', strategy: 'rotate' as const, candidates: [{ sourceId: 'a', model: 'native-a' }] }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
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
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, ...['match-a', 'match-b', 'other', 'extra-1', 'extra-2', 'extra-3', 'extra-4', 'extra-5'].map(id => ({ ...catalog.models[0], id, candidates: [{ sourceId: 'a', model: id }] })), pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
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
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, ...Array.from({ length: 65 }, (_, i) => ({ ...catalog.models[0], id: 'entry-' + i, candidates: [{ sourceId: 'a', model: 'entry-' + i }] }))] }} busy={false} error="" save={vi.fn(async () => true)} retry={vi.fn()} onSource={vi.fn()} /></App>)
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
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={catalog} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
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
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, a, b] }} busy={false} error="" save={vi.fn(async () => true)} retry={vi.fn()} onSource={vi.fn()} /></App>)
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
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 const members = screen.getByRole('list', { name: 'orchestration.selectedPool' })
 expect(within(members).getByText('native-a')).toBeTruthy()
 expect(within(members).getByText('native-b')).toBeTruthy()
 await pick('pool.source', 'Source B')
 expect(within(members).getByText('native-a')).toBeTruthy()
 fireEvent.click(within(members).getAllByRole('button', { name: 'orchestration.removeMember' })[1])
 expect(screen.getByRole('checkbox', { name: 'native-b' }).getAttribute('aria-checked')).toBe('false')
 await pick('pool.source', 'Source A')
 expect(screen.getByRole('checkbox', { name: /native-a/ }).getAttribute('aria-checked')).toBe('true')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'all', candidates: [{ sourceId: 'a', model: 'native-a' }] })]) })))
})

it('shows field-specific errors and focuses the invalid field without sending a save', () => {
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={catalog} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
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
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, pool] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.open' }))
 expect(document.querySelectorAll('.tt-member-status')[1]?.textContent).toBe('orchestration.sourceNotEnabled')
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 expect(screen.getByText('orchestration.unconfiguredCount')).toBeTruthy()
 expect(screen.queryByRole('checkbox', { name: /orphan/ })).toBeNull()
 const orphan = within(screen.getByRole('list', { name: 'orchestration.selectedPool' })).getByText('orphan').closest('li')!
 expect(within(orphan).getByText('orchestration.sourceNotEnabled')).toBeTruthy()
 expect(save).not.toHaveBeenCalled()
 fireEvent.click(within(orphan).getByRole('button', { name: 'orchestration.removeMember' }))
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ id: 'legacy', candidates: [{ sourceId: 'a', model: 'native-a' }], weights: { 'a/native-a': 3 } })]) })))
})


it('distinguishes identical model IDs across sources and keeps selected members in insertion order', async () => {
 const duplicate = { ...catalog.models[1], candidates: [{ sourceId: 'b', model: 'native-a' }] }
 const save = vi.fn(async () => true)
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [catalog.models[0], duplicate] }} busy={false} error="" save={save} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('button', { name: 'pool.create' }))
 fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Duplicates' } })
 fireEvent.click(screen.getByRole('checkbox', { name: 'native-a' }))
 await pick('pool.source', 'Source B')
 expect(screen.getByRole('checkbox', { name: 'native-a' }).getAttribute('aria-checked')).toBe('false')
 fireEvent.click(screen.getByRole('checkbox', { name: 'native-a' }))
 const members = screen.getByRole('list', { name: 'orchestration.selectedPool' })
 expect(within(members).getAllByRole('listitem').map(row => row.textContent)).toEqual(['native-aSource A', 'native-aSource B'])
 fireEvent.click(within(members).getAllByRole('button')[0])
 expect(screen.getByRole('checkbox', { name: 'native-a' }).getAttribute('aria-checked')).toBe('true')
 await pick('pool.source', 'Source A')
 expect(screen.getByRole('checkbox', { name: 'native-a' }).getAttribute('aria-checked')).toBe('false')
 fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
 await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ models: expect.arrayContaining([expect.objectContaining({ name: 'Duplicates', candidates: [{ sourceId: 'b', model: 'native-a' }] })]) })))
})

it('keeps nested routing groups selectable without including the edited group itself', async () => {
 const other = { id: 'other', name: 'Other group', aggregate: true, protocol: 'anthropic-messages', strategy: 'smart' as const, candidates: [{ sourceId: 'a', model: 'native-a' }] }
 const pool = { ...other, id: 'self', name: 'Self', candidates: [{ sourceId: '@group', model: 'other' }] }
 render(<App><ModelAggregationWorkspace {...requestNav} active catalog={{ ...catalog, models: [...catalog.models, other, pool] }} busy={false} error="" save={vi.fn(async () => true)} retry={vi.fn()} onSource={vi.fn()} /></App>)
 fireEvent.click(within(screen.getByRole('region', { name: 'Self' })).getByRole('button', { name: 'pool.open' }))
 fireEvent.mouseDown(screen.getByRole('tab', { name: 'pool.section.members' }))
 expect(screen.getByRole('button', { name: 'pool.groups' }).getAttribute('aria-pressed')).toBe('true')
 expect(screen.getByRole('checkbox', { name: 'other' }).getAttribute('aria-checked')).toBe('true')
 expect(screen.queryByRole('checkbox', { name: 'self' })).toBeNull()
 await pick('pool.source', 'Source A')
 expect(screen.getByRole('list', { name: 'orchestration.selectedPool' }).textContent).toContain('other')
})
