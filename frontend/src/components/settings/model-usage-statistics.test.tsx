// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentSettings } from './agent-settings'
import { ModelUsageStatistics, type UsageStatistics, type UsageTotals } from './model-usage-statistics'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../i18n', () => { const t = (key: string, values?: Record<string, string>) => key + (values?.amount ? ' ' + values.amount : ''); return { useI18n: () => ({ t, locale: 'en-US' }) } })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const totals: UsageTotals = { requests: 3, charges: [{ currency: 'USD', amount: '0.006' }], estimatedCharges: [], totalTokens: 715, inputTokens: 650, outputTokens: 65, cacheReadTokens: 160, unknown: 1, pending: 0, failed: 1, estimated: 0, missingUsage: 0 }
const statistics: UsageStatistics = { days: 7, startDay: '2026-10-20', endDay: '2026-10-26', dailyStartDay: '2026-10-20', total: totals, daily: [{ ...totals, day: '2026-10-26' }], models: [{ ...totals, model: 'model-a' }], modelsTruncated: false }
const role = { baseUrl: 'https://models.example/v1', model: 'model-a', keyConfigured: false, images: false }
const configuration = { connection: { baseUrl: role.baseUrl, keyConfigured: false }, main: role, worker: role }
const usage = { ...totals, day: '2026-10-26', timezone: 'Asia/Shanghai', recent: [], statistics }
const openProxy = async () => { render(<App><AgentSettings /></App>); await screen.findByRole('tab', { name: 'agent.proxy.tab' }); fireEvent.click(screen.getByRole('tab', { name: 'agent.proxy.tab' })) }
const range = async (days: number) => { fireEvent.mouseDown(screen.getByRole('combobox', { name: 'agent.usage.range' })); fireEvent.click(await screen.findByText(`agent.usage.range.${days}`)) }

it('shows aggregate and model usage with separate input, output and cache counts', () => {
  render(<ModelUsageStatistics statistics={statistics} days={7} onDaysChange={vi.fn()} loading={false} disabled={false} />)
  expect(within(screen.getByText('agent.usage.totalTokens').parentElement!).getByText('715')).toBeTruthy()
  const model = screen.getByRole('article', { name: 'model-a' })
  expect(within(model).getByText('650')).toBeTruthy()
  expect(within(model).getByText('65')).toBeTruthy()
  expect(within(model).getByText('160')).toBeTruthy()
  expect(within(model).getByText(/agent.usage.unknown/)).toBeTruthy()
  expect(within(model).getByText(/agent.usage.partialCost/)).toBeTruthy()
  fireEvent.click(screen.getByText('agent.usage.dailyDetails'))
  expect(screen.getByRole('table')).toBeTruthy()
  expect(screen.getByText('agent.usage.accountingHint')).toBeTruthy()
})

it('switches periods without losing budget drafts and ignores an old period response', async () => {
  const responses = new Map<string, (value: unknown) => void>()
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/model-settings') return { data: configuration }
    if (path === '/agent/model-usage') return { data: usage }
    return await new Promise(resolve => responses.set(path, resolve))
  })
  await openProxy()
  await screen.findByRole('article', { name: 'model-a' })
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), { target: { value: '23' } })
  await range(30)
  await waitFor(() => expect(responses.has('/agent/model-usage?days=30')).toBe(true))
  await range(90)
  await waitFor(() => expect(responses.has('/agent/model-usage?days=90')).toBe(true))
  responses.get('/agent/model-usage?days=90')!({ data: { ...usage, statistics: { ...statistics, days: 90, models: [{ ...totals, model: 'current-90' }] } } })
  await screen.findByRole('article', { name: 'current-90' })
  responses.get('/agent/model-usage?days=30')!({ data: { ...usage, statistics: { ...statistics, days: 30, models: [{ ...totals, model: 'stale-30' }] } } })
  await waitFor(() => expect(screen.queryByRole('article', { name: 'stale-30' })).toBeNull())
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('23')
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'PUT')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.discard' }))
})

it('keeps existing totals and the draft after a statistics failure', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?days=')) throw new Error('HTTP 503')
    return { data: path === '/agent/model-settings' ? configuration : usage }
  })
  await openProxy()
  await screen.findByRole('article', { name: 'model-a' })
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), { target: { value: '13' } })
  await range(0)
  await screen.findByText('agent.proxy.loadFailed')
  expect(screen.getByRole('article', { name: 'model-a' })).toBeTruthy()
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('13')
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.discard' }))
})

it('shows one empty-period message without an empty chart or model list', () => {
  const empty = { ...Object.fromEntries(Object.keys(totals).map(key => [key, 0])), charges: [], estimatedCharges: [] } as UsageTotals
  render(<ModelUsageStatistics statistics={{ ...statistics, total: empty, models: [], daily: [] }} days={7} onDaysChange={vi.fn()} loading={false} disabled={false} />)
  expect(screen.getByText('agent.usage.empty')).toBeTruthy()
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.queryByRole('article')).toBeNull()
})

it('shows unknown instead of zero cost when a model has no settled known charges', () => {
  const unknown = { ...totals, requests: 1, charges: [], unknown: 1, pending: 0, failed: 0, estimated: 0 }
  render(<ModelUsageStatistics statistics={{ ...statistics, models: [{ ...unknown, model: 'unpriced-model' }] }} days={7} onDaysChange={vi.fn()} loading={false} disabled={false} />)
  const model = screen.getByRole('article', { name: 'unpriced-model' })
  expect(within(model).getByText('agent.proxy.costUnknown')).toBeTruthy()
  expect(within(model).queryByText(/CN¥0\.00/)).toBeNull()
})


it('keeps currencies and historical estimates separate in totals, daily rows and model fees', () => {
  const mixed = { ...totals, charges: [{currency: 'USD', amount: '0.1'}, {currency: 'CNY', amount: '2'}], estimatedCharges: [{currency: 'CNY', amount: '9'}] }
  render(<ModelUsageStatistics statistics={{ ...statistics, total: mixed, daily: [{...mixed, day: '2026-10-26'}], models: [{...mixed, model: 'mixed'}] }} days={7} onDaysChange={vi.fn()} loading={false} disabled={false} />)
  const model = screen.getByRole('article', {name: 'mixed'})
  expect(within(model).getByText(/agent.usage.partialCost/)).toBeTruthy()
  expect(within(model).getByText(/agent.proxy.historicalEstimate.*CNY.*9/)).toBeTruthy()
  expect(within(model).getByText(/agent.usage.partialCost.*USD.*0.10.*CNY.*2.00/)).toBeTruthy()
  fireEvent.mouseDown(screen.getByRole('combobox', {name: 'agent.usage.chartMetric'}))
  fireEvent.click(screen.getByText('agent.usage.cost · CNY', {selector: '.ant-select-item-option-content'}))
  expect(document.querySelector('.agent-usage-bar-column > span')?.getAttribute('style')).toBe('height: 100%;')
})

it('shows 24 hourly buckets for a selected date and keeps the budget draft across date changes', async () => {
  const hour = { ...totals, requests: 2, unknown: 0, failed: 0, charges: [{currency: 'USD', amount: '0.2'}] }
  const hours = Array.from({length: 24}, (_, index) => ({...hour, hour: index, requests: index === 14 ? 2 : 0, totalTokens: index === 14 ? 715 : 0, charges: index === 14 ? hour.charges : []}))
  const dayStatistics = { ...statistics, days: 1, hourly: hours }
  vi.mocked(api).mockImplementation(async (_method, path) => ({data: path === '/agent/model-settings' ? configuration : path.includes('days=1') ? {...usage, statistics: dayStatistics} : usage}))
  await openProxy(); await screen.findByRole('article', {name: 'model-a'})
  fireEvent.change(screen.getByLabelText('agent.proxy.dailyLimit'), {target: {value: '9'}})
  await range(1)
  await screen.findByText('agent.usage.hourly')
  expect(document.querySelectorAll('.agent-usage-bar-column')).toHaveLength(24)
  fireEvent.click(screen.getByText('agent.usage.hourlyDetails'))
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(25)
  expect(within(screen.getByRole('table')).getByText('14:00')).toBeTruthy()
  fireEvent.mouseDown(screen.getByRole('combobox', {name: 'agent.usage.chartMetric'}))
  fireEvent.click(screen.getByText('agent.proxy.requests', {selector: '.ant-select-item-option-content'}))
  const bars = document.querySelectorAll('.agent-usage-bar-column > span')
  expect(bars[14].getAttribute('style')).toBe('height: 100%;')
  expect(bars[13].getAttribute('style')).toBe('height: 0%;')
  fireEvent.change(screen.getByLabelText('agent.usage.day'), {target: {value: '2026-10-25'}})
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/model-usage?days=1&day=2026-10-25')).toBe(true))
  expect((screen.getByLabelText('agent.proxy.dailyLimit') as HTMLInputElement).value).toBe('9')
  fireEvent.click(screen.getByRole('button', {name: 'agent.models.discard'}))
})

it('ignores a stale day response after selecting another date', async () => {
  const responses = new Map<string, (value: unknown) => void>()
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('&day=')) return await new Promise(resolve => responses.set(path, resolve))
    return {data: path === '/agent/model-settings' ? configuration : usage}
  })
  await openProxy(); await screen.findByRole('article', {name: 'model-a'}); await range(1)
  const input = screen.getByLabelText('agent.usage.day')
  fireEvent.change(input, {target: {value:'2026-10-24'}})
  await waitFor(() => expect(responses.has('/agent/model-usage?days=1&day=2026-10-24')).toBe(true))
  fireEvent.change(input, {target: {value:'2026-10-25'}})
  await waitFor(() => expect(responses.has('/agent/model-usage?days=1&day=2026-10-25')).toBe(true))
  responses.get('/agent/model-usage?days=1&day=2026-10-25')!({data:{...usage,statistics:{...statistics,days:1,hourly:[],models:[{...totals,model:'current-day'}]}}})
  await screen.findByRole('article',{name:'current-day'})
  responses.get('/agent/model-usage?days=1&day=2026-10-24')!({data:{...usage,statistics:{...statistics,days:1,hourly:[],models:[{...totals,model:'stale-day'}]}}})
  await waitFor(() => expect(screen.queryByRole('article',{name:'stale-day'})).toBeNull())
})

it('stacks model tokens into a total, keeps model colors when ranking changes and expands exact daily values', () => {
  const first = {...totals, requests:3, totalTokens:60, unknown:0, pending:0, charges:[{currency:'USD',amount:'0.02'}], model:'a'}
  const second = {...first, requests:2, totalTokens:40, charges:[{currency:'USD',amount:'0.08'}], model:'b'}
  const aggregate = {...first, requests:5, totalTokens:100, charges:[{currency:'USD',amount:'0.10'}]}
  const stacked = {...statistics, seriesModels:['a','b'], total:aggregate, daily:[{...aggregate, day:'2026-10-26', models:[first,second]}], models:[first,second]}
  const onDayChange=vi.fn(), onDaysChange=vi.fn()
  const view=render(<ModelUsageStatistics statistics={stacked} days={7} onDaysChange={onDaysChange} onDayChange={onDayChange} loading={false} disabled={false} />)
  const segments=()=>[...document.querySelectorAll('.agent-usage-stack > span')]
  expect(segments().map(el=>el.getAttribute('style'))).toEqual([expect.stringContaining('height: 60%'),expect.stringContaining('height: 40%')])
  const red=document.querySelector('.agent-usage-legend [data-model="a"] > span')?.getAttribute('style')
  const green=document.querySelector('.agent-usage-legend [data-model="b"] > span')?.getAttribute('style')
  expect(red).toContain('--usage-series-0');expect(green).toContain('--usage-series-1')
  view.rerender(<ModelUsageStatistics statistics={{...stacked,seriesModels:['b','a']}} days={7} onDaysChange={onDaysChange} onDayChange={onDayChange} loading={false} disabled={false} />)
  expect(document.querySelector('.agent-usage-legend [data-model="a"] > span')?.getAttribute('style')).toBe(red)
  expect(document.querySelector('.agent-usage-legend [data-model="b"] > span')?.getAttribute('style')).toBe(green)
  fireEvent.click(screen.getByText('agent.usage.dailyDetails'))
  fireEvent.click(screen.getByRole('button',{name:'agent.usage.expandPoint'}))
  expect(document.querySelectorAll('.agent-usage-model-detail')).toHaveLength(2)
  expect(within(screen.getByRole('table')).getByText('60')).toBeTruthy()
  expect(within(screen.getByRole('table')).getByText('40')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'agent.usage.viewDayModels'}))
  expect(onDayChange).toHaveBeenCalledWith('2026-10-26');expect(onDaysChange).toHaveBeenCalledWith(1)
  fireEvent.mouseDown(screen.getByRole('combobox',{name:'agent.usage.chartMetric'}))
  fireEvent.click(screen.getByText('agent.usage.cost · USD',{selector:'.ant-select-item-option-content'}))
  expect(document.querySelector('.agent-usage-stack [data-model="a"]')?.getAttribute('style')).toContain('height: 20%')
  expect(document.querySelector('.agent-usage-stack [data-model="b"]')?.getAttribute('style')).toContain('height: 80%')
})

it('includes Other models in the stack and the legend without losing the total', () => {
  const first={...totals,requests:1,totalTokens:20,model:'a'}
  const other={...totals,requests:4,totalTokens:80,model:null}
  render(<ModelUsageStatistics statistics={{...statistics,seriesModels:['a'],seriesTruncated:true,daily:[{...totals,requests:5,totalTokens:100,day:'2026-10-26',models:[first,other]}]}} days={7} onDaysChange={vi.fn()} loading={false} disabled={false} />)
  expect(within(screen.getByRole('list',{name:'agent.usage.legend'})).getByText('agent.usage.otherModels')).toBeTruthy()
  expect(document.querySelector('.agent-usage-stack [data-model=""]')?.getAttribute('style')).toContain('height: 80%')
  expect(screen.getByText('agent.usage.seriesLimit')).toBeTruthy()
})
