import { useEffect, useRef, useState } from 'react'
import { Spin } from 'antd'
import { useI18n } from '../../i18n'
import { useThemeMode } from '../../theme'
import { useLayout } from '../../layout'
import type { EChartsType } from 'echarts/core'

export type ChartPoint = { key: string; label: string; total: number; values: number[]; totalText?: string; valueTexts?: string[] }
export type ChartSeries = { label: string; color: string }
type Props = { points: ChartPoint[]; series: ChartSeries[]; selected: string; label: string; integer?: boolean; onSelect: (key: string) => void; format: (value: number) => string }

export function ModelUsageChart(props: Props) {
  const { t } = useI18n()
  const { mode } = useThemeMode(), { coarse } = useLayout()
  const [loading, setLoading] = useState(true), [failed, setFailed] = useState(false)
  const element = useRef<HTMLDivElement>(null), chart = useRef<EChartsType | null>(null), current = useRef(props)
  current.current = props
  const draw = useRef<(() => void) | null>(null)
  useEffect(() => {
    let disposed = false
    let initialize: (() => void) | null = null
    setLoading(true); setFailed(false)
    const observer = new ResizeObserver(() => {
      if (!element.current?.clientWidth || !element.current.clientHeight) return
      if (chart.current) chart.current.resize()
      else initialize?.()
    })
    if (element.current) observer.observe(element.current)
    void import('./usage-chart-renderer').then(({ createUsageChart }) => {
      if (disposed || !element.current) return
      initialize = () => {
        if (disposed || !element.current?.clientWidth || chart.current) return
        const view = createUsageChart(element.current, () => current.current, coarse)
        chart.current = view.chart; draw.current = view.draw; view.draw(); setLoading(false)
      }
      initialize()
    }).catch(() => { if (!disposed) { setLoading(false); setFailed(true) } })
    return () => { disposed = true; observer.disconnect(); chart.current?.dispose(); chart.current = null; draw.current = null }
  }, [mode, coarse])
  useEffect(() => { draw.current?.() }, [props])
  return <div className="agent-usage-chart-frame"><div ref={element} hidden={failed} className="agent-usage-chart" role="img" aria-label={props.label} />{loading && <div className="agent-usage-chart-message"><Spin size="small" /></div>}{failed && <p className="agent-settings-hint">{t('agent.usage.chartUnavailable')}</p>}</div>
}
