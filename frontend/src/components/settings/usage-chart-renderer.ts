import { init, use, type EChartsCoreOption } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ChartPoint, ChartSeries } from './model-usage-chart'

use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

type Props = { points: ChartPoint[]; series: ChartSeries[]; selected: string; label: string; integer?: boolean; onSelect: (key: string) => void; format: (value: number) => string }
export function createUsageChart(element: HTMLDivElement, read: () => Props, coarse: boolean) {
  const chart = init(element, null, { renderer: 'canvas' })
  const style = () => getComputedStyle(element)
  const token = (name: string) => style().getPropertyValue(name).trim()
  const size = (name: string) => parseFloat(token(name))
  const draw = () => {
    const props = read()
    const tooltip = (input: unknown) => {
      const index = (Array.isArray(input) ? input[0] : input)?.dataIndex
      const point = props.points[index]
      const content = document.createElement('div')
      if (!point) return content
      const title = document.createElement('strong'); title.textContent = `${point.label} · ${point.totalText ?? props.format(point.total)}`; content.append(title)
      props.series.forEach((series, index) => {
        if (!point.values[index]) return
        const row = document.createElement('div'); row.textContent = `${series.label} · ${point.valueTexts?.[index] ?? props.format(point.values[index])}`; content.append(row)
      })
      return content
    }
    const option: EChartsCoreOption = {
      animation: false,
      textStyle: { fontFamily: style().fontFamily, fontSize: size('--fs-meta'), color: token('--text-dim') },
      grid: { top: size('--sp-4'), right: size('--sp-2'), bottom: size('--sp-2'), left: size('--sp-2'), containLabel: true },
      tooltip: { trigger: 'axis', triggerOn: coarse ? 'click' : 'mousemove|click', confine: true, enterable: false, formatter: tooltip, backgroundColor: token('--bg-elevated'), borderColor: token('--border'), borderWidth: 1, padding: size('--sp-3'), textStyle: { color: token('--text-bright'), fontSize: size('--fs-meta') }, extraCssText: `border-radius:${token('--r-sm')};box-shadow:none;max-width:100%;white-space:normal;overflow-wrap:anywhere`, axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: props.points.map(point => point.label), axisTick: { show: false }, axisLine: { lineStyle: { color: token('--border-subtle') } }, axisLabel: { hideOverlap: true, color: token('--text-dim') } },
      yAxis: { type: 'value', minInterval: props.integer ? 1 : 0, splitLine: { lineStyle: { color: token('--border-subtle') } }, axisLabel: { color: token('--text-dim'), formatter: (value: number) => props.format(value) } },
      series: props.series.map((series, index) => ({ type: 'bar', name: series.label, stack: 'usage', barMaxWidth: size('--sp-5') * 2, itemStyle: { color: token(series.color) }, data: props.points.map(point => ({ value: point.values[index] || 0, itemStyle: { opacity: point.key === props.selected ? 1 : 0.7 } })) })),
    }
    chart.setOption(option, { notMerge: true })
  }
  chart.getZr().on('click', event => {
    if (!chart.containPixel('grid', [event.offsetX, event.offsetY])) return
    const index = Math.round(chart.convertFromPixel({ xAxisIndex: 0 }, event.offsetX) as number)
    const point = read().points[index]
    if (point) read().onSelect(point.key)
  })
  return { chart, draw }
}
