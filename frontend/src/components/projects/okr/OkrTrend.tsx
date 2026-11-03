import { useEffect, useMemo, useRef, useState } from 'react'
import { Select } from 'antd'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { useThemeMode } from '../../../theme'
import type { EChartsType } from 'echarts/core'
import { dailyHistory, dateOffset, shanghaiDate, sourceObservations, type Workspace } from './okr-workspace'

export default function OkrTrend({ workspace, title }: { workspace: Workspace; title?: string }) {
  const { t, locale } = useI18n()
  const { coarse } = useLayout()
  const { mode } = useThemeMode()
  const [chosen, setChosen] = useState(workspace.metrics[0]?.id || '')
  const [failed, setFailed] = useState(false)
  const metric = workspace.metrics.find(m => m.id === chosen) || workspace.metrics[0]
  const rows = useMemo(() => metric ? dailyHistory(sourceObservations(workspace, metric)).filter(row => row.date >= workspace.startDate && row.date <= workspace.endDate) : [], [workspace, metric])
  const latest = rows[0]
  const number = (v: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(v)
  const day = (v: string) => new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', timeZone: 'Asia/Shanghai' }).format(new Date(v + 'T00:00:00+08:00'))
  const dates = useMemo(() => {
    const end = workspace.endDate < shanghaiDate() ? workspace.endDate : shanghaiDate()
    const start = dateOffset(end, -13) < workspace.startDate ? workspace.startDate : dateOffset(end, -13)
    const result: string[] = []
    for (let date = start; date <= end; date = dateOffset(date, 1)) result.push(date)
    return result
  }, [workspace.startDate, workspace.endDate])
  const element = useRef<HTMLDivElement>(null)
  const chart = useRef<EChartsType | null>(null)
  useEffect(() => {
    let disposed = false
    setFailed(false)
    const render = async () => {
      const { createTrend } = await import('./okr-trend-renderer')
      if (disposed || !element.current) return
      chart.current = createTrend(element.current, dates.map(date => ({ date, label: day(date), value: rows.find(row => row.date === date)?.latest.value ?? null })), metric?.name || '', metric?.unit || '', coarse, number)
    }
    if (rows.length) void render().catch(() => { if (!disposed) setFailed(true) })
    const observer = new ResizeObserver(() => chart.current?.resize())
    if (element.current) observer.observe(element.current)
    return () => { disposed = true; observer.disconnect(); chart.current?.dispose(); chart.current = null }
  }, [rows, dates, metric, locale, coarse, mode]) // eslint-disable-line react-hooks/exhaustive-deps
  return <section className="okr-trend">
    <div className="okr-section-head"><div><h3>{title || t('okr.trend')}</h3><p className="okr-muted">{t('okr.recentDays')}</p></div><Select aria-label={t('okr.trendMetric')} value={metric?.id} onChange={setChosen} options={workspace.metrics.map(m => ({ value: m.id, label: m.name }))} /></div>
    {latest ? <>
      <div className="okr-trend-value"><strong>{number(latest.latest.value)} <small>{metric?.unit}</small></strong><span>{day(latest.date)} · {latest.delta === null ? t('okr.noDailyComparison') : t('okr.latestDelta', { value: new Intl.NumberFormat(locale, { signDisplay: 'always', maximumFractionDigits: 2 }).format(latest.delta), unit: metric?.unit || '' })}</span></div>
      {rows.length === 1 && <p className="okr-muted">{t('okr.firstDay')}</p>}
      <div ref={element} className="okr-trend-canvas" role="img" aria-label={t('okr.trendLabel', { name: metric?.name || '' })} />
      {failed && <p className="okr-muted">{t('okr.chartFailed')}</p>}
      <details><summary>{t('okr.trendTable')}</summary><table className="okr-trend-table"><thead><tr><th>{t('okr.date')}</th><th>{t('okr.value')}</th><th>{t('okr.dayChange')}</th></tr></thead><tbody>{rows.slice(0, 14).map(row => <tr key={row.date}><td>{day(row.date)}</td><td>{number(row.latest.value)} {metric?.unit}</td><td>{row.delta === null ? t('okr.deltaUnknown') : number(row.delta)}</td></tr>)}</tbody></table></details>
    </> : <p className="okr-trend-empty">{t('okr.noEvidence')}</p>}
  </section>
}
