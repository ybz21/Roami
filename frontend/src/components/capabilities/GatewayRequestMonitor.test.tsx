// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayRequestMonitor from './GatewayRequestMonitor'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({
  t: (key: string, values?: { label?: string }) => values?.label ? key + ' ' + values.label : key,
  locale: 'en-US',
}) }))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('pins the chart, filters by a failure reason and restores the clicked audit row on return', async () => {
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  const now = Date.UTC(2026, 10, 20, 14, 30), from = now - 600_000
  const totals = { requests: 2, failed: 2, recovered: 0, uncertain: 0, sameSource: 0, crossSource: 0 }
  const rows = [
    { requestId: 'limited', at: now - 100, routeId: 'coding', model: 'Code assistant', caller: 'external', outcome: 'failed', status: 429 },
    { requestId: 'interrupted', at: now - 200, routeId: 'coding', model: 'Code assistant', caller: 'external', outcome: 'interrupted', status: 200 },
  ]
  vi.mocked(api).mockImplementation(async (_method, path) => {
    const query = new URL(path, 'https://example.test').searchParams
    return { data: {
      now, totals, points: [{ from, to: now, totals }], routes: { coding: 'Code assistant' }, callers: { external: true },
      outcomes: { failed: 1, interrupted: 1 }, failureReasons: { upstreamLimited: 1, interrupted: 1 },
      recent: query.get('reason') === 'upstreamLimited' ? rows.slice(0, 1) : rows,
    } }
  })
  const onRequest = vi.fn()
  const monitor = (active: boolean) => <GatewayRequestMonitor active={active} catalog={null} onRequest={onRequest} />
  const page = render(monitor(true))
  fireEvent.click(await screen.findByRole('button', { name: 'gatewayTrace.bucket' }))
  const recent = within(page.container.querySelector<HTMLElement>('.tt-request-recent')!)
  const failure = await screen.findByRole('button', { name: /gatewayTrace.upstreamLimited/ }) as HTMLButtonElement
  await waitFor(() => expect(failure.disabled).toBe(false))
  fireEvent.click(failure)

  const row = await recent.findByRole('button', { name: /Code assistant.*HTTP 429/ }) as HTMLButtonElement
  await waitFor(() => {
    expect(row.disabled).toBe(false)
    expect(recent.queryByRole('button', { name: /HTTP 200/ })).toBeNull()
  })
  const requestURL = new URL(String(vi.mocked(api).mock.lastCall?.[1]), 'https://example.test')
  expect(Object.fromEntries(requestURL.searchParams)).toMatchObject({
    from: String(from), to: String(now), end: String(now), reason: 'upstreamLimited',
  })
  fireEvent.click(row)
  expect(onRequest).toHaveBeenCalledWith('limited')
  page.rerender(monitor(false))
  page.rerender(monitor(true))
  expect(document.activeElement).toBe(row)
  expect(failure.getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: 'gatewayTrace.bucket' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: 'gatewayTrace.removeFilter gatewayTrace.upstreamLimited' }))
  await recent.findByRole('button', { name: /HTTP 200/ })
  const resetURL = new URL(String(vi.mocked(api).mock.lastCall?.[1]), 'https://example.test')
  expect(resetURL.searchParams.get('from')).toBe(String(from))
  expect(resetURL.searchParams.has('reason')).toBe(false)
})
