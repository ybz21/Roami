// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ModelUsageStatistics, type UsageStatistics, type UsageTotals } from './model-usage-statistics'
vi.mock('./model-usage-chart', () => ({ ModelUsageChart: ({ points, onSelect, label }: any) => <div role="img" aria-label={label}>{points.map((point: any) => <button type="button" key={point.key} aria-label={'chart-' + point.key} onClick={() => onSelect(point.key)}>{point.label}</button>)}</div> }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../i18n', () => { const t = (key: string, values?: Record<string, string>) => key + (values?.amount ? ' ' + values.amount : ''); return { useI18n: () => ({ t, locale: 'en-US' }) } })
afterEach(() => { cleanup(); vi.clearAllMocks(); history.replaceState(null, '', '#/') })
const totals: UsageTotals = { requests: 3, charges: [{ currency: 'USD', amount: '0.006' }], estimatedCharges: [], totalTokens: 715, inputTokens: 650, outputTokens: 65, cacheReadTokens: 160, unknown: 1, pending: 0, failed: 1, estimated: 0, missingUsage: 0 }
const statistics: UsageStatistics = { days: 7, startDay: '2026-10-20', endDay: '2026-10-26', dailyStartDay: '2026-10-20', total: totals, daily: [{ ...totals, day: '2026-10-26' }], models: [{ ...totals, model: 'model-a' }], modelsTruncated: false }

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
  expect(within(screen.getByRole('region', { name: 'agent.usage.pointDetails' })).getAllByText(/CNY.*2.00/).length).toBeGreaterThan(0)
})

it('stacks model tokens into a total, keeps model colors when ranking changes and expands exact daily values', () => {
  const first = {...totals, requests:3, totalTokens:60, unknown:0, pending:0, charges:[{currency:'USD',amount:'0.02'}], model:'a'}
  const second = {...first, requests:2, totalTokens:40, charges:[{currency:'USD',amount:'0.08'}], model:'b'}
  const aggregate = {...first, requests:5, totalTokens:100, charges:[{currency:'USD',amount:'0.10'}]}
  const stacked = {...statistics, seriesModels:['a','b'], total:aggregate, daily:[{...aggregate, day:'2026-10-26', models:[first,second]}], models:[first,second]}
  const onDayChange=vi.fn(), onDaysChange=vi.fn()
  const view=render(<ModelUsageStatistics statistics={stacked} days={7} onDaysChange={onDaysChange} onDayChange={onDayChange} loading={false} disabled={false} />)
  const point = screen.getByRole('region', {name:'agent.usage.pointDetails'})
  expect(within(point).getByText('100')).toBeTruthy()
  expect(within(point).getByText('a')).toBeTruthy()
  expect(within(point).getByText('b')).toBeTruthy()
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
  fireEvent.click(within(screen.getByRole('region',{name:'agent.usage.pointDetails'})).getByRole('button',{name:'agent.usage.viewDayModels'}))
  expect(onDayChange).toHaveBeenCalledWith('2026-10-26');expect(onDaysChange).toHaveBeenCalledWith(1)
  fireEvent.mouseDown(screen.getByRole('combobox',{name:'agent.usage.chartMetric'}))
  fireEvent.click(screen.getByText('agent.usage.cost · USD',{selector:'.ant-select-item-option-content'}))
  expect(within(point).getByText(/USD.*0.02/)).toBeTruthy()
  expect(within(point).getByText(/USD.*0.08/)).toBeTruthy()
})

it('includes Other models in the stack and the legend without losing the total', () => {
  const first={...totals,requests:1,totalTokens:20,model:'a'}
  const other={...totals,requests:4,totalTokens:80,model:null}
  render(<ModelUsageStatistics statistics={{...statistics,seriesModels:['a'],seriesTruncated:true,daily:[{...totals,requests:5,totalTokens:100,day:'2026-10-26',models:[first,other]}]}} days={7} onDaysChange={vi.fn()} loading={false} disabled={false} />)
  expect(within(screen.getByRole('list',{name:'agent.usage.legend'})).getByText('agent.usage.otherModels')).toBeTruthy()
  expect(within(screen.getByRole('region',{name:'agent.usage.pointDetails'})).getByText('agent.usage.otherModels')).toBeTruthy()
  expect(screen.getByText('agent.usage.seriesLimit')).toBeTruthy()
})
