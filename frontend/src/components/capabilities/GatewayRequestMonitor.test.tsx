// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { installRadixTestEvents } from '../ui/radix-test-events'
import GatewayRequestMonitor from './GatewayRequestMonitor'
import type { RequestSummary, RequestTotals } from './gateway-request-api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', async () => {
  const { default: strings } = await import('../../i18n/locales/en-US')
  return { useI18n: () => ({
    t: (key: string, values: Record<string, string> = {}) =>
      (strings[key as keyof typeof strings] || key).replace(/\{(\w+)\}/g, (_, name) => values[name] ?? ''),
    locale: 'en-US',
  }) }
})

const now = Date.UTC(2026, 10, 20, 14, 30)
const from = now - 600_000
const totals = (requests: number, failed: number, recovered = 0, uncertain = 0): RequestTotals =>
  ({ requests, failed, recovered, uncertain, sameSource: 0, crossSource: recovered })
const latestQuery = () => new URL(String(vi.mocked(api).mock.lastCall?.[1]), 'https://example.test').searchParams

beforeEach(() => {
  installRadixTestEvents()
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.mocked(api).mockImplementation(async (_method, path) => {
    const query = new URL(path, 'https://example.test').searchParams
    const pinned = query.has('from')
    const filtered = query.get('reason') === 'upstreamLimited'
    const aggregate = filtered ? totals(1, 1) : pinned ? totals(5, 2, 1, 1) : totals(10, 2, 1, 1)
    const data: RequestSummary = {
      now, totals: aggregate, range: { from: pinned ? from : now - 3600_000, to: now },
      points: [{ from, to: now, totals: pinned ? aggregate : totals(5, 2, 1, 1) }],
      routes: { coding: 'Code assistant' }, callers: { external: true },
      outcomes: { failed: 1, interrupted: 1 },
      failureReasons: { upstreamLimited: 1, interrupted: 1 },
      firstToken: filtered ? null : { samples: 2, p50: 120, p95: 250, p99: 300 },
      duration: filtered ? null : { samples: 2, p50: 700, p95: 900, p99: 1000 },
      tokens: filtered ? { samples: 0, input: 0, output: 0 } : { samples: 1, input: 2400, output: 600 },
      byModel: [{ id: 'coding', totals: aggregate }], bySource: [{ id: 'backup', totals: aggregate }],
    }
    return { data: { ...data, recent: [{ requestId: 'obsolete', model: 'Unrendered request', status: 429 }] } }
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

it('shows aggregate metrics without request rows and applies the selected bucket and failure reason', async () => {
  const onAudit = vi.fn()
  render(<GatewayRequestMonitor active catalog={null} onAudit={onAudit} />)
  const trend = await screen.findByRole('group', { name: 'Request volume' })
  expect(screen.getByText('0.167 req/min')).toBeTruthy()
  expect(screen.queryByRole('heading', { name: 'Recent requests' })).toBeNull()
  expect(screen.queryByText(/Unrendered request|HTTP 429/)).toBeNull()
  expect(latestQuery().get('view')).toBe('request-summary')

  const bucket = within(trend).getByRole('button')
  fireEvent.click(bucket)
  await screen.findByText('0.5 req/min')
  expect(bucket.getAttribute('aria-pressed')).toBe('true')
  const latency = screen.getByRole('table', { name: 'Latency percentiles' })
  expect(within(latency).getByRole('cell', { name: '250 ms' })).toBeTruthy()
  expect(within(latency).getByRole('cell', { name: '900 ms' })).toBeTruthy()
  expect(screen.getByText('4 tokens/s')).toBeTruthy()
  expect(screen.getByText('1 tokens/s')).toBeTruthy()
  expect(screen.getByText('Token counts are available for 1 of 2 successful requests.')).toBeTruthy()
  expect(within(screen.getByRole('table', { name: 'By requested model' })).getByText('Code assistant')).toBeTruthy()
  expect(within(screen.getByRole('table', { name: 'By final source' })).getByText('backup')).toBeTruthy()
  expect(screen.getAllByText('40%')).toHaveLength(3)

  const failure = screen.getByRole('button', { name: /Upstream rate limit/ })
  fireEvent.click(failure)
  await screen.findByText('0.1 req/min')
  expect(Object.fromEntries(latestQuery())).toMatchObject({
    from: String(from), to: String(now), end: String(now), reason: 'upstreamLimited',
  })
  expect(failure.getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByText('No token counts for successful requests in this window.')).toBeTruthy()
  expect(screen.queryByText('250 ms')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Clear filter.*Upstream rate limit/ }))
  await screen.findByText('0.5 req/min')
  expect(latestQuery().get('from')).toBe(String(from))
  expect(latestQuery().has('reason')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'View audit' }))
  expect(onAudit).toHaveBeenCalledOnce()
})

it('preserves model and caller filters while the monitor tab is hidden', async () => {
  const monitor = (active: boolean) => <GatewayRequestMonitor active={active} catalog={null} />
  const page = render(monitor(true))
  await screen.findByText('0.167 req/min')
  fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Monitoring model' }), { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('option', { name: 'Code assistant' }))
  await waitFor(() => expect(latestQuery().get('routeId')).toBe('coding'))

  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Caller' }), { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('option', { name: 'Other clients' }))
  await waitFor(() => expect(latestQuery().get('caller')).toBe('external'))
  page.rerender(monitor(false))
  const requestCount = vi.mocked(api).mock.calls.length
  document.dispatchEvent(new Event('visibilitychange'))
  expect(api).toHaveBeenCalledTimes(requestCount)
  page.rerender(monitor(true))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(requestCount + 1))
  expect(latestQuery().get('routeId')).toBe('coding')
  expect(latestQuery().get('caller')).toBe('external')
})
