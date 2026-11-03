import { init, use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

export function createTrend(element: HTMLDivElement, points: { date: string; label: string; value: number | null }[], name: string, unit: string, coarse: boolean, format: (value: number) => string) {
  const chart = init(element, null, { renderer: 'canvas' })
  const style = getComputedStyle(element)
  const token = (key: string) => style.getPropertyValue(key).trim()
  const space = (key: string) => parseFloat(token(key))
  chart.setOption({
    animation: false,
    color: [token('--accent')],
    textStyle: { color: token('--text-dim'), fontSize: space('--fs-meta'), fontFamily: style.fontFamily },
    grid: { top: space('--sp-3'), left: space('--sp-2'), right: space('--sp-4'), bottom: space('--sp-1'), containLabel: true },
    tooltip: { show: !coarse, trigger: 'axis', renderMode: 'richText', valueFormatter: (value: unknown) => typeof value === 'number' ? `${format(value)} ${unit}` : '', backgroundColor: token('--bg-elevated'), borderColor: token('--border'), textStyle: { color: token('--text-bright') } },
    xAxis: { type: 'category', data: points.map(p => p.label), boundaryGap: true, axisTick: { show: false }, axisLine: { lineStyle: { color: token('--border-subtle') } }, axisLabel: { color: token('--text-dim') } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: token('--text-dim'), formatter: format }, splitLine: { lineStyle: { color: token('--border-subtle') } } },
    series: [{ type: 'line', name, data: points.map(p => p.value), connectNulls: false, symbolSize: space('--sp-2'), lineStyle: { color: token('--accent') }, itemStyle: { color: token('--accent') } }],
  })
  return chart
}
