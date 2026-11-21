// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { useLayout } from '../../layout'
import { WorkspaceStateStore } from '../../workspace-state'
import { WorkspaceStateProvider } from '../../view-state'
import { installRadixTestEvents } from '../ui/radix-test-events'
import ModelHub from './ModelHub'
import type { CatalogModel, ModelCatalog } from './model-hub-api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: vi.fn() }))
vi.mock('../settings/model-usage-chart', () => ({ ModelUsageChart: () => null }))

const pool: CatalogModel = {
  id: 'pool-a', name: 'Pool Alpha', aggregate: true, protocol: 'openai-completions', strategy: 'smart',
  candidates: [{ sourceId: 'source', model: 'native' }],
}
const catalog: ModelCatalog = {
  revision: 'r1', sources: [{ id: 'source', name: 'Source', baseUrl: '', protocol: 'openai-completions', authMode: 'bearer' }],
  models: [pool, { ...pool, id: 'pool-b', name: 'Pool Beta' }], drafts: [], baseUrl: '', uses: {},
}
const totals = { requests: 5, failed: 1, recovered: 2, uncertain: 1, sameSource: 1, crossSource: 2, switchedFailed: 1 }
const empty = { requests: 0, failed: 0, recovered: 0, uncertain: 0, sameSource: 0, crossSource: 0 }
const now = Date.UTC(2026, 10, 21, 12)
const trace = { requestId: 'audit-id', at: now, routeId: pool.id, model: pool.name, caller: 'external', outcome: 'recovered', sourceId: 'source', upstreamModel: 'native', status: 200, durationMs: 100, attempts: 2, switch: 'source' }
let store: WorkspaceStateStore
const page = (sub: string, navigate: (path: string) => void) =>
  <WorkspaceStateProvider store={store}><App><ModelHub sub={sub} onNav={navigate} /></App></WorkspaceStateProvider>
const monitorCalls = () => vi.mocked(api).mock.calls.filter(([, path]) => path.includes('view=request-summary'))
const tab = (section: string) => screen.getByRole('tab', { name: 'pool.section.' + section })

beforeEach(() => {
  installRadixTestEvents()
  store = new WorkspaceStateStore()
  vi.mocked(useLayout).mockReturnValue({ phone: false, keyboard: 0 } as ReturnType<typeof useLayout>)
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/model-gateway/catalog') return { data: catalog }
    if (path === '/agent/model-gateway/settings') return { data: { currency: 'CNY', timezone: 'Asia/Shanghai', dailyLimit: 0, pricing: { default: {}, models: {} } } }
    if (path.includes('/monitor/requests/')) return { data: { request: trace, attempts: [
      { attempt: 1, at: now - 100, sourceId: 'source', model: 'original', status: 429, success: false, durationMs: 80 },
      { attempt: 2, at: now, sourceId: 'source', model: 'native', status: 200, success: true, durationMs: 20, firstTokenMs: 10, groupPath: ['pool-b'] },
    ], complete: true } }
    if (path.includes('view=requests')) {
      const query = new URL(path, 'https://example.test').searchParams
      return { data: { recent: query.get('routeId') === pool.id && query.get('switch') !== 'failed' ? [trace] : [] } }
    }
    if (path.includes('view=request-summary')) {
      const query = new URL(path, 'https://example.test').searchParams
      const sample = query.get('routeId') === pool.id ? totals : empty
      return { data: { now, totals: sample, points: [{ from: now - 3600000, to: now, totals: sample }], range: { from: now - 3600000, to: now }, byModel: [] } }
    }
    if (path.includes('/routing?')) return { data: { now, available: 0, channels: [], observation: { ...totals, latest: trace } } }
    return { data: {} }
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('deep-links to monitoring, queries the saved pool ID and keeps both editing drafts across tab routes', async () => {
  const navigate = vi.fn()
  const view = render(page('aggregate/pool-a/monitor', navigate))
  const chart = await screen.findByRole('region', { name: 'pool.section.monitor' })
  const requests = await within(chart).findByText('gatewayTrace.requests')
  expect(requests.nextElementSibling?.textContent).toBe('5')
  expect(within(chart).getAllByText('gatewayTrace.success')[0].nextElementSibling?.textContent).toBe('3')
  expect(within(chart).getAllByText('gatewayTrace.failed')[0].nextElementSibling?.textContent).toBe('1')
  expect(within(chart).getByRole('list', { name: 'pool.monitor.switchTrend' })).toBeTruthy()
  expect(within(chart).getByText('gatewayTrace.sameSourceSwitch').textContent).toBe('gatewayTrace.sameSourceSwitch1')
  expect(within(chart).getByText('gatewayTrace.crossSourceSwitch').textContent).toBe('gatewayTrace.crossSourceSwitch2')
  expect(tab('monitor').getAttribute('aria-selected')).toBe('true')
  expect(screen.queryByRole('button', { name: 'agent.models.save' })).toBeNull()
  expect(within(chart).queryByText('gatewayTrace.recent')).toBeNull()
  expect(monitorCalls()[0][1]).toBe('/agent/model-gateway/monitor?view=request-summary&hours=6&routeId=pool-a')

  fireEvent.mouseDown(tab('members'))
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-a/members')
  view.rerender(page('aggregate/pool-a/members', navigate))
  fireEvent.change(screen.getByLabelText('pool.name'), { target: { value: 'Draft name' } })
  fireEvent.change(screen.getByLabelText('pool.modelId'), { target: { value: 'draft-id' } })
  fireEvent.mouseDown(tab('routing'))
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-a/routing')
  view.rerender(page('aggregate/pool-a/routing', navigate))
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'pool.strategy' }), { key: 'Enter' })
  fireEvent.click(await screen.findByRole('option', { name: 'pool.strategy.order' }))

  fireEvent.mouseDown(tab('monitor'))
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-a/monitor')
  view.rerender(page('aggregate/pool-a/monitor', navigate))
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'monitor.range' }), { key: 'Enter' })
  fireEvent.click((await screen.findAllByRole('option', { name: 'monitor.hours' }))[2])
  await waitFor(() => expect(monitorCalls().slice(-1)[0]?.[1]).toBe('/agent/model-gateway/monitor?view=request-summary&hours=24&routeId=pool-a'))

  const count = monitorCalls().length
  view.rerender(page('aggregate/pool-a/members', navigate))
  expect((screen.getByLabelText('pool.name') as HTMLInputElement).value).toBe('Draft name')
  expect((screen.getByLabelText('pool.modelId') as HTMLInputElement).value).toBe('draft-id')
  view.rerender(page('aggregate/pool-a', navigate))
  expect(tab('routing').getAttribute('aria-selected')).toBe('true')
  expect(screen.getByRole('combobox', { name: 'pool.strategy' }).textContent).toBe('pool.strategy.order')
  expect(monitorCalls()).toHaveLength(count)
  fireEvent.click(document.querySelector('.tt-aggregate-detail .tt-back')!)
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate')
})

it('opens another pool in the phone detail, shows its empty state and preserves the routing audit path', async () => {
  vi.mocked(useLayout).mockReturnValue({ phone: true, keyboard: 0 } as ReturnType<typeof useLayout>)
  const navigate = vi.fn()
  const view = render(page('aggregate', navigate))
  fireEvent.click(within(await screen.findByRole('region', { name: 'Pool Beta' })).getByRole('button', { name: 'pool.open' }))
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-b')
  const pushState = vi.spyOn(history, 'pushState')
  try {
    view.rerender(page('aggregate/pool-b/monitor', navigate))
    await screen.findByText('gatewayTrace.empty')
    expect(monitorCalls().slice(-1)[0]?.[1]).toContain('routeId=pool-b')
    expect(screen.queryByRole('heading', { name: 'pool.monitor.requestTrend' })).toBeNull()
    const header = document.querySelector('.tt-mobile-subpage-head')!
    expect(header.textContent).toBe('Pool Beta')
    fireEvent.click(within(header as HTMLElement).getByRole('button'))
    expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate')
    expect(pushState).not.toHaveBeenCalled()
  } finally {
    pushState.mockRestore()
  }

  view.rerender(page('aggregate/pool-a/routing', navigate))
  fireEvent.click(await screen.findByRole('button', { name: 'gatewayTrace.latestHit' }))
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/audit/request/audit-id/aggregate/pool-a')
  view.rerender(page('audit/request/audit-id/aggregate/pool-a', navigate))
  await screen.findByRole('heading', { name: 'gatewayTrace.recovered' })
  fireEvent.click(document.querySelector('.tt-mobile-subpage-head .tt-back')!)
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-a')
})

it('hands off the monitoring range to the scoped switch list and returns from a nested trace on phone', async () => {
  vi.mocked(useLayout).mockReturnValue({ phone: true, keyboard: 0 } as ReturnType<typeof useLayout>)
  const navigate = vi.fn()
  const view = render(page('aggregate/pool-a/monitor', navigate))
  fireEvent.keyDown(await screen.findByRole('combobox', { name: 'monitor.range' }), { key: 'Enter' })
  fireEvent.click((await screen.findAllByRole('option', { name: 'monitor.hours' }))[2])
  await waitFor(() => expect(monitorCalls().slice(-1)[0]?.[1]).toContain('hours=24&routeId=pool-a'))
  fireEvent.click(await screen.findByRole('button', { name: 'pool.trace.viewSwitches' }))
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-a/requests')
  view.rerender(page('aggregate/pool-a/requests', navigate))
  const row = await screen.findByRole('button', { name: /native/ })
  expect(api).toHaveBeenCalledWith('GET', '/agent/model-gateway/monitor?view=requests&hours=24&routeId=pool-a&switch=any', undefined, expect.anything())
  fireEvent.click(row)
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-a/requests/audit-id')
  view.rerender(page('aggregate/pool-a/requests/audit-id', navigate))
  await screen.findByRole('heading', { name: 'gatewayTrace.recovered' })
  expect(api).toHaveBeenCalledWith('GET', '/agent/model-gateway/monitor/requests/audit-id?routeId=pool-a', undefined, expect.anything())
  expect(screen.getByText('pool.trace.via')).toBeTruthy()
  expect(screen.getByText('pool.trace.firstToken')).toBeTruthy()
  expect(screen.getByText('gatewayTrace.upstreamLimited')).toBeTruthy()
  expect(document.querySelectorAll('.tt-mobile-subpage-head')).toHaveLength(1)
  fireEvent.click(document.querySelector('.tt-mobile-subpage-head .tt-back')!)
  expect(navigate).toHaveBeenLastCalledWith('capabilities/models/aggregate/pool-a/requests')
  view.rerender(page('aggregate/pool-a/requests', navigate))
  expect(document.activeElement).toBe(row)
  expect(screen.getByRole('combobox', { name: 'modelUsage.state' }).textContent).toBe('pool.trace.switched')
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'modelUsage.state' }), { key: 'Enter' })
  fireEvent.click(await screen.findByRole('option', { name: 'pool.trace.switchFailed' }))
  await screen.findByText('hub.directory.noMatches')
  expect(api).toHaveBeenCalledWith('GET', '/agent/model-gateway/monitor?view=requests&hours=24&routeId=pool-a&switch=failed', undefined, expect.anything())
})
