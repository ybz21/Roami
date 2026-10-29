// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { AgentSettings } from './agent-settings'
import type { GatewayConfiguration, GatewayUsage } from './local-model-gateway'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
const layout = vi.hoisted(() => ({ phone: false, keyboard: false }))
vi.mock('../../layout', () => ({ useLayout: () => layout }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('./model-usage-chart', () => ({ ModelUsageChart: () => <div role="img" aria-label="usage chart" /> }))
const role = { baseUrl: 'https://models.example/v1', keyConfigured: true, model: 'fixture', images: false }
const connection = { connection: { baseUrl: role.baseUrl, keyConfigured: true }, main: role, worker: { ...role, model: 'fixture-worker' } }
const config: GatewayConfiguration = { currency: 'CNY', timezone: 'UTC', dailyLimit: 2, pricing: { default: { input_per_million: 0, output_per_million: 0, cache_read_per_million: 0 }, models: { fixture: { input_per_million: 2, output_per_million: 4, cache_read_per_million: 1 } } } }
const usage: GatewayUsage = { day: '2026-10-29', from: '2026-10-23', to: '2026-10-29', days: 7, timezone: 'UTC', today: [], groups: [], hourly: [], recent: [] }
let currentConfig: GatewayConfiguration, currentUsage: GatewayUsage
beforeEach(() => {
  layout.phone = false; layout.keyboard = false
  currentConfig = structuredClone(config); currentUsage = structuredClone(usage)
  history.replaceState(null, '', '#/settings/agent/runtime?modelTab=proxy')
  vi.mocked(api).mockImplementation(async (method, path, body) => {
    if (path === '/agent/model-settings') return { data: connection }
    if (path === '/agent/model-gateway/settings') { if (method === 'PUT') currentConfig = body; return { data: currentConfig } }
    if (path.startsWith('/agent/model-gateway/usage')) return { data: currentUsage }
    return { data: {} }
  })
})

it('keeps the focused field above the save bar when the phone keyboard opens', async () => {
  layout.phone = true
  const page = () => <div data-testid="settings-scroll" style={{ overflowY: 'auto' }}><App><AgentSettings /></App></div>
  const view = render(page())
  const input = await screen.findByLabelText('agent.proxy.dailyLimit')
  const pane = screen.getByTestId('settings-scroll')
  const footer = input.closest('form')!.querySelector('.agent-settings-save')!
  let footerTop = 500
  input.getBoundingClientRect = () => ({ bottom: 350 } as DOMRect)
  pane.getBoundingClientRect = () => ({ bottom: 500 } as DOMRect)
  footer.getBoundingClientRect = () => ({ top: footerTop } as DOMRect)
  pane.scrollTo = vi.fn()
  act(() => input.focus())
  footerTop = 300; layout.keyboard = true
  view.rerender(page())
  await waitFor(() => expect(pane.scrollTo).toHaveBeenCalledWith({ top: expect.any(Number), behavior: 'instant' }))
  expect(vi.mocked(pane.scrollTo).mock.calls[0][0]).toMatchObject({ top: expect.any(Number) })
  expect((vi.mocked(pane.scrollTo).mock.calls[0][0] as ScrollToOptions).top).toBeGreaterThanOrEqual(50)
})
afterEach(() => {
  for (const button of document.querySelectorAll('button')) if (button.textContent === 'agent.models.discard') fireEvent.click(button)
  cleanup(); vi.clearAllMocks(); history.replaceState(null, '', '#/')
})
const setup = () => render(<App><AgentSettings /></App>)
const tab = (name: string) => fireEvent.click(screen.getByRole('tab', { name }))

it('opens the restored billing deep link using Go settings and usage only', async () => {
  setup()
  const limit = await screen.findByLabelText('agent.proxy.dailyLimit') as HTMLInputElement
  expect(limit.value).toBe('2')
  expect((screen.getByLabelText('agent.gateway.timezone') as HTMLInputElement).value).toBe('UTC')
  await screen.findByText('agent.usage.empty')
  expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/model-gateway/usage?days=7')).toBe(true)
  expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/model-usage')).toBe(false)
})

it('preserves model and billing drafts across tabs and saves only the local gateway configuration', async () => {
  setup(); await screen.findByLabelText('agent.proxy.dailyLimit')
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), { target: { value: '0' } })
  tab('agent.gateway.modelsTab')
  fireEvent.change(await screen.findByLabelText('agent.models.apiKey'), { target: { value: 'fixture' } })
  tab('agent.proxy.prices')
  fireEvent.click(await screen.findByRole('button', { name: /fixture agent.prices.configured/ }))
  fireEvent.change(screen.getByLabelText('agent.proxy.priceLabel', { selector: '#agent-price-0-input' }), { target: { value: '3.123456789' } })
  tab('agent.proxy.tab')
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('0')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/settings', { ...config, dailyLimit: 0, pricing: { ...config.pricing, models: { fixture: { ...config.pricing.models.fixture, input_per_million: 3.123456789 } } } }))
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT' && call[1] === '/agent/model-settings')).toBe(false)
  tab('agent.gateway.modelsTab')
  expect((screen.getByLabelText('agent.models.apiKey') as HTMLInputElement).value).toBe('fixture')
})

it('retains price and limit drafts after a rejected save', async () => {
  const original = vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async (...args) => {
    if (args[0] === 'PUT') throw { apiError: { code: 'MODEL_PROXY_CURRENCY_MISMATCH' } }
    return original(...args)
  })
  setup(); await screen.findByLabelText('agent.proxy.dailyLimit')
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await screen.findByText('agent.gateway.periodBusy')
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('5')
  expect((screen.getByRole('button', { name: 'agent.models.save' }) as HTMLButtonElement).disabled).toBe(false)
})

it('reconciles an unknown charge only after amount, reason and explicit confirmation', async () => {
  currentUsage.recent = [{ id: 'unknown-call', day: usage.day, model: 'fixture', role: 'main', state: 'unknown', currency: 'CNY', cost: null, startedMs: Date.UTC(2026, 9, 29), inputTokens: null, outputTokens: null, cacheReadTokens: null, errorCode: 'MODEL_PROXY_USAGE_UNKNOWN', httpStatus: 200, reconciliation: '' }]
  setup(); await screen.findByLabelText('agent.proxy.dailyLimit')
  fireEvent.click(await screen.findByText('agent.proxy.recent'))
  fireEvent.click(screen.getByRole('button', { name: 'agent.gateway.reconcile' }))
  const dialog = await screen.findByRole('dialog')
  expect((within(dialog).getByRole('button', { name: 'agent.gateway.confirmReconcile' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(within(dialog).getByLabelText('agent.gateway.amount'), { target: { value: '.75' } })
  fireEvent.change(within(dialog).getByLabelText('agent.gateway.reason'), { target: { value: 'verified receipt' } })
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT')).toBe(false)
  fireEvent.click(within(dialog).getByRole('button', { name: 'agent.gateway.confirmReconcile' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/calls/unknown-call', { amount: .75, reason: 'verified receipt' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('sends date selection to the Go ledger and preserves the selected range', async () => {
  setup(); await screen.findByText('agent.usage.empty')
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'agent.usage.range' }))
  fireEvent.click(screen.getByText('agent.usage.range.1', { selector: '.ant-select-item-option-content' }))
  fireEvent.change(await screen.findByLabelText('agent.usage.day'), { target: { value: '2026-10-28' } })
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/model-gateway/usage?days=1&day=2026-10-28')).toBe(true))
  tab('agent.proxy.prices'); tab('agent.proxy.tab')
  expect((screen.getByLabelText('agent.usage.day') as HTMLInputElement).value).toBe('2026-10-28')
})


it('filters statistics and recent receipts while retaining all-source today and unsaved settings', async () => {
  const row = { day: usage.day, role: 'main', model: 'same-model', currency: 'CNY', requests: 1, inputTokens: 100, outputTokens: 20, cacheReadTokens: 10, pending: 0, unknown: 0, usageUnknown: 0, failed: 0, cost: '1.000000000' }
  currentUsage = { ...usage, today: [{ ...row, requests: 3 }], groups: [{ ...row, requests: 3 }] }
  setup(); await screen.findByText('agent.usage.totalRequests')
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), { target: { value: '9' } })
  currentUsage = { ...currentUsage, source: 'rsi', groups: [{ ...row, source: 'rsi' }], recent: [{ id: 'legacy-rsi', day: usage.day, model: 'same-model', role: 'main', sessionId: 'rsi-legacy', source: 'rsi', state: 'known', currency: 'CNY', cost: '1.000000000', startedMs: Date.UTC(2026, 9, 29), inputTokens: 100, outputTokens: 20, cacheReadTokens: 10, errorCode: '', httpStatus: 200, reconciliation: '' }] }
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'agent.usage.source' }))
  fireEvent.click(screen.getByText('agent.usage.source.rsi', { selector: '.ant-select-item-option-content' }))
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/model-gateway/usage?days=7&source=rsi')).toBe(true))
  await waitFor(() => expect(within(screen.getByText('agent.usage.totalRequests').parentElement!).getByText('1')).toBeTruthy())
  expect(within(screen.getAllByText('agent.proxy.requests')[0].parentElement!).getByText('3')).toBeTruthy()
  expect(screen.getByText('agent.usage.sourceHint')).toBeTruthy()
  fireEvent.click(screen.getByText('agent.proxy.recent'))
  expect(screen.getByText(/agent.proxy.rsi ·/)).toBeTruthy()
  tab('agent.proxy.prices'); tab('agent.proxy.tab')
  expect(screen.getByText('agent.usage.source.rsi', { selector: '.ant-select-selection-item' })).toBeTruthy()
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('9')
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT')).toBe(false)
})

it('hides a previous source during loading and ignores an aborted source response', async () => {
  const row = { day: usage.day, role: 'main', model: 'ordinary-only-model', currency: 'CNY', requests: 1, inputTokens: 100, outputTokens: 20, cacheReadTokens: 10, pending: 0, unknown: 0, usageUnknown: 0, failed: 0, cost: '1.000000000' }
  currentUsage = { ...usage, today: [row], groups: [row] }
  const original = vi.mocked(api).getMockImplementation()!
  let finish: (value: any) => void = () => {}
  vi.mocked(api).mockImplementation((...args) => args[1].includes('source=rsi') ? new Promise(resolve => { finish = resolve }) : original(...args))
  setup(); await screen.findByRole('article', { name: 'ordinary-only-model' })
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'agent.usage.source' }))
  fireEvent.click(screen.getByText('agent.usage.source.rsi', { selector: '.ant-select-item-option-content' }))
  expect(screen.queryByRole('article', { name: 'ordinary-only-model' })).toBeNull()
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'agent.usage.source' }))
  fireEvent.click(screen.getByText('agent.usage.source.other', { selector: '.ant-select-item-option-content' }))
  await screen.findByRole('article', { name: 'ordinary-only-model' })
  await act(async () => finish({ data: { ...usage, groups: [{ ...row, model: 'late-rsi-model' }] } }))
  expect(screen.queryByText('late-rsi-model')).toBeNull()
  expect(screen.getByRole('article', { name: 'ordinary-only-model' })).toBeTruthy()
})
