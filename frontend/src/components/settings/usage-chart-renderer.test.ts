// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ option: null as any, click: null as any, selected: vi.fn() }))
vi.mock('echarts/core', () => ({ use: vi.fn(), init: () => ({ setOption: (option: any) => { state.option = option }, getZr: () => ({ on: (_name: string, callback: any) => { state.click = callback } }), containPixel: () => true, convertFromPixel: () => 1 }) }))
vi.mock('echarts/charts', () => ({ BarChart: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
import { createUsageChart } from './usage-chart-renderer'
afterEach(() => { document.body.replaceChildren(); vi.clearAllMocks() })

it('keeps stacked values and selects the clicked date, including zero-height bars', () => {
  const element = document.createElement('div'); document.body.append(element)
  const view = createUsageChart(element, () => ({ points: [{ key: 'first', label: 'Oct 26', total: 100, values: [60, 40] }, { key: 'second', label: 'Oct 27', total: 0, values: [0, 0] }], series: [{ label: 'main', color: '--accent' }, { label: 'worker', color: '--ok' }], selected: 'first', label: 'Tokens', format: String, onSelect: state.selected }), false)
  view.draw()
  expect(state.option.series.map((series: any) => series.data.map((point: any) => point.value))).toEqual([[60, 0], [40, 0]])
  state.click({ offsetX: 100, offsetY: 100 })
  expect(state.selected).toHaveBeenCalledWith('second')
})

it('renders untrusted model names as text rather than tooltip HTML', () => {
  const element = document.createElement('div'); document.body.append(element)
  const name = '<img src=x onerror=alert(1)>'
  const view = createUsageChart(element, () => ({ points: [{ key: 'day', label: 'Oct 27', total: 100, values: [100] }], series: [{ label: name, color: '--accent' }], selected: 'day', label: 'Tokens', format: String, onSelect: vi.fn() }), true)
  view.draw()
  const tooltip = state.option.tooltip.formatter([{ dataIndex: 0 }]) as HTMLElement
  expect(tooltip.textContent).toContain(name)
  expect(tooltip.querySelector('img')).toBeNull()
  expect(state.option.tooltip.triggerOn).toBe('click')
})
