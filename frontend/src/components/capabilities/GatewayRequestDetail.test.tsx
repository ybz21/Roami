// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayRequestDetail from './GatewayRequestDetail'
import type { GatewayRequest, RequestAttempt } from './gateway-request-api'
import type { ModelCatalog } from './model-hub-api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))

const at = Date.UTC(2026, 10, 20, 6, 27, 42)
const catalog: ModelCatalog = {
  revision: 'live', baseUrl: '', drafts: [], uses: {},
  sources: [
    { id: 'preferred', name: 'WorkBuddy', baseUrl: '', protocol: 'openai-completions', authMode: 'api_key' },
    { id: 'fallback', name: 'OpenRouter', baseUrl: '', protocol: 'openai-completions', authMode: 'api_key' },
  ],
  models: [{ id: 'current-pool', aliases: ['daily-coding'], name: 'Daily coding', aggregate: true, protocol: 'openai-completions', strategy: 'smart', candidates: [] }],
}
const row: GatewayRequest = {
  requestId: 'request-audit', routeId: 'daily-coding', at, model: 'Recorded pool', caller: 'external',
  outcome: 'recovered', sourceId: 'fallback', upstreamModel: 'qwen', status: 200, durationMs: 992, attempts: 2, switch: 'source',
}
const limited: RequestAttempt = { attempt: 1, sourceId: 'preferred', model: 'ds', at, status: 429, success: false, error: 'MODEL_HTTP_429' }
const served: RequestAttempt = { attempt: 2, sourceId: 'fallback', model: 'qwen', at: at + 83, status: 200, success: true }

afterEach(() => { cleanup(); vi.resetAllMocks() })

function openRequest(request: GatewayRequest, attempts: RequestAttempt[], complete = true) {
  vi.mocked(api).mockResolvedValue({ data: { request, attempts, complete } })
  const onSource = vi.fn(), onPool = vi.fn(), onBack = vi.fn(), onLimits = vi.fn()
  render(<App><GatewayRequestDetail id={request.requestId} catalog={catalog} {...{ onBack, onSource, onPool, onLimits }} /></App>)
  return { onSource, onPool }
}

it('shows the recorded winner, labels the switch, and presents chronological attempts with their timestamps', async () => {
  const { onSource, onPool } = openRequest(row, [served, limited])
  const outcome = await screen.findByRole('heading', { name: 'gatewayTrace.recovered' })
  await waitFor(() => expect(document.activeElement).toBe(outcome))
  const hit = screen.getByText('gatewayTrace.actualHit').nextElementSibling!
  expect(within(hit as HTMLElement).getByText('qwen')).toBeTruthy()
  expect(within(hit as HTMLElement).getByText('OpenRouter')).toBeTruthy()
  expect(screen.getByText('gatewayTrace.crossSourceSwitch')).toBeTruthy()
  const [first, second] = screen.getAllByRole('listitem')
  expect(within(first).getByText('gatewayTrace.upstreamLimited')).toBeTruthy()
  expect(within(second).getByText('gatewayTrace.success')).toBeTruthy()
  expect(second.querySelector('time')?.dateTime).toBe(new Date(served.at).toISOString())
  expect(screen.getByText('MODEL_HTTP_429').closest('details')?.open).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'gatewayWorkspace.viewSource' }))
  fireEvent.click(screen.getByRole('button', { name: 'gatewayWorkspace.viewPool' }))
  expect(onSource).toHaveBeenCalledWith('fallback')
  expect(onPool).toHaveBeenCalledWith('current-pool')
})

it('retains the last attempted model and terminal missing response even if all attempt records have expired', async () => {
  openRequest({ ...row, outcome: 'unknown', status: 0, sourceId: 'removed' }, [], false)
  await screen.findByRole('heading', { name: 'gatewayTrace.unknown' })
  expect(screen.getByText('gatewayTrace.noResponse')).toBeTruthy()
  const lastAttempt = screen.getByText('gatewayTrace.lastAttempt').nextElementSibling as HTMLElement
  expect(within(lastAttempt).getByText('qwen')).toBeTruthy()
  expect(within(lastAttempt).getByText('gatewayTrace.sourceRemoved')).toBeTruthy()
  expect(screen.queryByText('gatewayTrace.actualHit')).toBeNull()
  expect(screen.getByText('gatewayTrace.partial')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'gatewayWorkspace.viewSource' })).toBeNull()
})

it('keeps HTTP 200 visible when output ends unsuccessfully', async () => {
  openRequest({ ...row, outcome: 'interrupted', attempts: 1, switch: undefined }, [{ ...served, attempt: 1, success: false }])
  expect(await screen.findByRole('heading', { name: 'gatewayTrace.interrupted' })).toBeTruthy()
  const attempt = screen.getByRole('listitem')
  expect(within(attempt).getByText('gatewayTrace.interrupted')).toBeTruthy()
  expect(within(attempt).getByText('HTTP 200')).toBeTruthy()
  expect(screen.getByText('gatewayTrace.lastAttempt')).toBeTruthy()
})

it.each([
  { outcome: 'blocked', sourceId: '', upstreamModel: undefined, attempts: [], blocks: { pricing: 2 }, reason: 'gatewayTrace.reason.pricing' },
  { outcome: 'exhausted', sourceId: 'fallback', upstreamModel: 'qwen', attempts: [limited, { ...served, status: 402, success: false }], reason: 'gatewayTrace.reason.quota' },
] as const)('distinguishes $outcome with HTTP 503 from rejection or attempted upstreams', async ({ outcome, sourceId, upstreamModel, attempts, reason, ...extra }) => {
  openRequest({ ...row, ...extra, outcome, sourceId, upstreamModel, status: 503, attempts: attempts.length, switch: undefined }, [...attempts])
  expect(await screen.findByRole('heading', { name: 'gatewayTrace.' + outcome })).toBeTruthy()
  expect(screen.getByText('HTTP 503')).toBeTruthy()
  expect(screen.getByText(reason)).toBeTruthy()
  expect(!!screen.queryByText('gatewayTrace.lastAttempt')).toBe(outcome === 'exhausted')
})
