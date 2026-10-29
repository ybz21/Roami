import type { ReactNode } from 'react'
import { Fragment, useRef, useState } from 'react'
import { Input, Select } from 'antd'
import { useI18n } from '../../i18n'
import { ModelCharges, chargeText, type ModelCharge } from './model-charges'
import { ModelUsageChart } from './model-usage-chart'

export type UsageTotals = { requests: number; charges: ModelCharge[]; localCharges?: ModelCharge[]; localEstimated?: number; estimatedCharges: ModelCharge[]; totalTokens: number; inputTokens: number; outputTokens: number; cacheReadTokens: number; unknown: number; pending: number; failed: number; estimated: number; missingUsage: number }
export type UsageModelPart = UsageTotals & { model: string | null }
export type UsagePoint = UsageTotals & { models?: UsageModelPart[] }
export type UsageStatistics = { days: number; startDay: string; endDay: string; dailyStartDay: string; total: UsageTotals; daily: (UsagePoint & { day: string })[]; hourly?: (UsagePoint & { hour: number })[]; seriesModels?: string[]; seriesTruncated?: boolean; models: (UsageTotals & { model: string })[]; modelsTruncated: boolean }

export function ModelUsageStatistics({ statistics, days, onDaysChange, selectedDay, today, onDayChange, loading, disabled, sourceControl, filterHint }: { sourceControl?: ReactNode; filterHint?: string; statistics?: UsageStatistics; days: number; onDaysChange: (days: number) => void; selectedDay?: string; today?: string; onDayChange?: (day: string) => void; loading: boolean; disabled: boolean }) {
  const { t, locale } = useI18n()
  const [metric, setMetric] = useState('totalTokens'), [expandedPoint, setExpandedPoint] = useState(''), [selectedPoint, setSelectedPoint] = useState('')
  const previousColors = useRef(new Map<string, number>())
  const count = (value: number) => new Intl.NumberFormat(locale).format(value)
  const day = (value: string, full = false) => new Intl.DateTimeFormat(locale, { ...(full ? { year: 'numeric' as const } : {}), month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(value + 'T00:00:00Z'))
  const status = (total: UsageTotals) => [total.unknown ? t('agent.usage.unknown', { count: count(total.unknown) }) : '', total.pending ? t('agent.usage.pending', { count: count(total.pending) }) : '', total.failed ? t('agent.usage.failed', { count: count(total.failed) }) : ''].filter(Boolean).join(' · ')
  const currencies = statistics?.total.charges.map(charge => charge.currency) || []
  const selectedMetric = ['requests', 'totalTokens', ...currencies].includes(metric) ? metric : 'totalTokens'
  const metricValue = (row: UsageTotals) => selectedMetric === 'totalTokens' || selectedMetric === 'requests' ? row[selectedMetric] : Number(row.charges.find(charge => charge.currency === selectedMetric)?.amount || 0)
  const metricText = (row: UsageTotals) => selectedMetric === 'totalTokens' || selectedMetric === 'requests' ? count(row[selectedMetric]) : chargeText(row.charges.filter(charge => charge.currency === selectedMetric), locale) || (row.unknown > 0 || row.pending > 0 ? t('agent.proxy.costUnknown') : chargeText([{ currency: selectedMetric, amount: '0' }], locale))
  const hourly = statistics?.days === 1
  const time = (hour: number) => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'UTC' }).format(new Date(Date.UTC(2000, 0, 1, hour)))
  const points = hourly ? (statistics.hourly || []).map(row => ({ ...row, key: String(row.hour), label: time(row.hour) })) : (statistics?.daily || []).map(row => ({ ...row, key: row.day, label: day(row.day) }))
  const metricLabel = selectedMetric === 'totalTokens' ? t('agent.proxy.tokens') : selectedMetric === 'requests' ? t('agent.proxy.requests') : t('agent.usage.cost') + ' · ' + selectedMetric
  const fees = (row: UsageTotals) => <ModelCharges charges={row.charges} localCharges={row.localCharges} estimatedCharges={row.estimatedCharges} incomplete={row.unknown > 0 || row.pending > 0} />
  const seriesNames = statistics?.seriesModels || statistics?.models.slice(0, 4).map(row => row.model) || []
  const colorIndices = new Map<string, number>(), usedColors = new Set<number>()
  for (const name of seriesNames) {
    const previous = previousColors.current.get(name)
    if (previous !== undefined && !usedColors.has(previous)) { colorIndices.set(name, previous); usedColors.add(previous) }
  }
  for (const name of seriesNames) if (!colorIndices.has(name)) {
    const index = [0, 1, 2, 3].find(value => !usedColors.has(value)) ?? 0
    colorIndices.set(name, index); usedColors.add(index)
  }
  for (const [name, index] of colorIndices) previousColors.current.set(name, index)
  const seriesColor = (model: string | null) => model === null ? 'var(--usage-series-other)' : `var(--usage-series-${colorIndices.get(model) ?? 0})`
  const seriesLabel = (model: string | null) => model === null ? t('agent.usage.otherModels') : model
  const pointParts = (row: UsagePoint): UsageModelPart[] => {
    const parts = row.models || (row.requests ? [{ ...row, model: null }] : [])
    return [...parts].sort((a, b) => (a.model === null ? 4 : seriesNames.indexOf(a.model)) - (b.model === null ? 4 : seriesNames.indexOf(b.model)))
  }
  const chosenPoint = points.find(point => point.key === selectedPoint) || [...points].reverse().find(point => point.requests > 0) || points[points.length - 1]
  const legend: (string | null)[] = [...seriesNames, ...(points.some(row => pointParts(row).some(part => part.model === null)) ? [null] : [])]


  return <section className="agent-usage-statistics" aria-busy={loading} aria-label={t('agent.usage.title')}>
    <div className="agent-usage-toolbar"><h3>{t('agent.usage.title')}</h3><div className="agent-usage-filters">{sourceControl}{days === 1 && onDayChange && <Input type="date" aria-label={t('agent.usage.day')} value={selectedDay || ''} max={today} disabled={disabled} onChange={event => { if (event.target.value) onDayChange(event.target.value) }} />}<Select aria-label={t('agent.usage.range')} value={days} disabled={disabled} virtual={false} options={[1, 7, 30, 90, 0].map(value => ({ value, label: t('agent.usage.range.' + value) }))} onChange={onDaysChange} /></div></div>
    {filterHint && <p className="agent-settings-hint">{filterHint}</p>}
    {loading && <p className="agent-settings-hint" role="status">{t('agent.usage.loading')}</p>}
    {statistics && <>
      <p className="agent-settings-hint">{t('agent.usage.period', { start: day(statistics.startDay, true), end: day(statistics.endDay, true) })}</p>
      <div className="agent-proxy-totals" role="status">
        <div><span>{t('agent.usage.totalCost')}</span><strong>{fees(statistics.total)}</strong></div>
        <div><span>{t('agent.usage.totalRequests')}</span><strong>{count(statistics.total.requests)}</strong></div>
        <div><span>{t('agent.usage.totalTokens')}</span><strong>{count(statistics.total.totalTokens)}</strong></div>
        <div><span>{t('agent.usage.cacheRate')}</span><strong>{statistics.total.inputTokens > 0 ? new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(statistics.total.cacheReadTokens / statistics.total.inputTokens) : t('agent.usage.noRate')}</strong></div>
      </div>
      <p className="agent-settings-hint">{t('agent.usage.tokenBreakdown', { input: count(statistics.total.inputTokens), output: count(statistics.total.outputTokens), cache: count(statistics.total.cacheReadTokens) })}</p>
      {status(statistics.total) && <p className="agent-settings-hint" role="status">{status(statistics.total)}</p>}
      {statistics.total.missingUsage > 0 && <p className="agent-settings-hint">{t('agent.usage.incomplete', { missing: count(statistics.total.missingUsage) })}</p>}
      {statistics.total.requests === 0 ? <p className="agent-settings-hint">{t('agent.usage.empty')}</p> : <>
        <div className="agent-usage-toolbar"><h4>{t(hourly ? 'agent.usage.hourly' : 'agent.usage.daily')}</h4><Select aria-label={t('agent.usage.chartMetric')} value={selectedMetric} disabled={disabled} virtual={false} options={[{ value: 'totalTokens', label: t('agent.proxy.tokens') }, { value: 'requests', label: t('agent.proxy.requests') }, ...currencies.map(currency => ({ value: currency, label: t('agent.usage.cost') + ' · ' + currency }))]} onChange={setMetric} /></div>
        {statistics.dailyStartDay !== statistics.startDay && <p className="agent-settings-hint">{t('agent.usage.dailyWindow', { count: count(statistics.daily.length) })}</p>}
        {hourly && <p className="agent-settings-hint">{t('agent.usage.hourlyHint')}</p>}
        <ul className="agent-usage-legend" aria-label={t('agent.usage.legend')}>{legend.map(model => <li key={JSON.stringify(model)} data-model={model ?? ''}><span className="agent-usage-swatch" style={{ background: seriesColor(model) }} aria-hidden="true" /><span>{seriesLabel(model)}</span></li>)}</ul>
        {statistics.seriesTruncated && <p className="agent-settings-hint">{t('agent.usage.seriesLimit')}</p>}
        <ModelUsageChart integer={selectedMetric === 'totalTokens' || selectedMetric === 'requests'} points={points.map(row => ({ key: row.key, label: row.label, total: metricValue(row), totalText: metricText(row), valueTexts: legend.map(model => metricText(pointParts(row).find(part => part.model === model) || { ...row, totalTokens: 0, requests: 0, charges: [] })), values: legend.map(model => metricValue(pointParts(row).find(part => part.model === model) || { ...row, totalTokens: 0, requests: 0, charges: [] })) }))} series={legend.map(model => ({ label: seriesLabel(model), color: model === null ? '--usage-series-other' : `--usage-series-${colorIndices.get(model) ?? 0}` }))} selected={chosenPoint?.key || ''} label={t(hourly ? 'agent.usage.hourlyChartLabel' : 'agent.usage.chartLabel', { metric: metricLabel })} onSelect={setSelectedPoint} format={value => new Intl.NumberFormat(locale, { notation: value > 0 && value < 0.000001 ? 'scientific' : 'compact', maximumSignificantDigits: 3 }).format(value)} />
        <p className="agent-settings-hint">{t('agent.usage.chartHint')}</p>
        {chosenPoint && <section className="agent-usage-point" aria-label={t('agent.usage.pointDetails')}>
          <div className="agent-usage-toolbar"><Select aria-label={t('agent.usage.point')} value={chosenPoint.key} disabled={disabled} virtual={false} options={points.map(point => ({ value: point.key, label: point.label }))} onChange={setSelectedPoint} />{!hourly && onDayChange && 'day' in chosenPoint && <button type="button" className="tt-act" onClick={() => { onDayChange(chosenPoint.day); onDaysChange(1) }}>{t('agent.usage.viewDayModels')}</button>}</div>
          <div className="agent-proxy-totals"><div><span>{t('agent.proxy.tokens')}</span><strong>{count(chosenPoint.totalTokens)}</strong></div><div><span>{t('agent.proxy.requests')}</span><strong>{count(chosenPoint.requests)}</strong></div><div><span>{t('agent.usage.cost')}</span><strong>{chosenPoint.requests ? fees(chosenPoint) : t('agent.usage.noRate')}</strong></div></div>
          <p className="agent-settings-hint">{t('agent.usage.tokenBreakdown', { input: count(chosenPoint.inputTokens), output: count(chosenPoint.outputTokens), cache: count(chosenPoint.cacheReadTokens) })}</p>
          {status(chosenPoint) && <p className="agent-settings-hint">{status(chosenPoint)}</p>}
          <ul className="agent-usage-point-models">{pointParts(chosenPoint).map(part => <li key={JSON.stringify(part.model)}><strong><span className="agent-usage-swatch" style={{ background: seriesColor(part.model) }} aria-hidden="true" />{seriesLabel(part.model)}</strong><span>{t('agent.usage.pointUsage', { tokens: count(part.totalTokens), requests: count(part.requests) })}</span>{fees(part)}</li>)}</ul>
        </section>}
        <details className="agent-model-advanced agent-usage-daily"><summary>{t(hourly ? 'agent.usage.hourlyDetails' : 'agent.usage.dailyDetails')}</summary><table><thead><tr><th scope="col">{t(hourly ? 'agent.usage.time' : 'agent.usage.date')}</th><th scope="col">{t('agent.proxy.requests')}</th><th scope="col">{t('agent.proxy.tokens')}</th><th scope="col">{t('agent.usage.cost')}</th></tr></thead><tbody>{points.map(row => {
          const key = statistics.startDay + ':' + hourly + ':' + row.key, parts = pointParts(row), expanded = expandedPoint === key
          return <Fragment key={row.key}>
            <tr><th scope="row">{parts.length ? <button type="button" className="tt-act" aria-expanded={expanded} aria-label={t('agent.usage.expandPoint', { time: row.label })} onClick={() => setExpandedPoint(expanded ? '' : key)}>{row.label}</button> : row.label}</th><td>{count(row.requests)}</td><td>{count(row.totalTokens)}</td><td>{row.requests ? fees(row) : t('agent.usage.noRate')}{status(row) && <small>{status(row)}</small>}</td></tr>
            {expanded && parts.map(part => <tr className="agent-usage-model-detail" key={JSON.stringify(part.model)}><th scope="row"><span className="agent-usage-swatch" style={{ background: seriesColor(part.model) }} aria-hidden="true" />{seriesLabel(part.model)}</th><td>{count(part.requests)}</td><td>{count(part.totalTokens)}</td><td>{fees(part)}{status(part) && <small>{status(part)}</small>}</td></tr>)}
            {expanded && !hourly && onDayChange && 'day' in row && <tr><td colSpan={4}><button type="button" className="tt-act" onClick={() => { onDayChange(row.day); onDaysChange(1) }}>{t('agent.usage.viewDayModels')}</button></td></tr>}
          </Fragment>
        })}</tbody></table></details>
        <h4>{t('agent.usage.byModel')}</h4>
        <div className="agent-usage-models">{statistics.models.map(row => <article className="agent-usage-model" key={row.model} aria-label={row.model}>
          <div className="agent-usage-model-head"><strong>{row.model}</strong><strong>{fees(row)}</strong></div>
          <dl>{([['requests', 'agent.proxy.requests'], ['inputTokens', 'agent.usage.input'], ['outputTokens', 'agent.usage.output'], ['cacheReadTokens', 'agent.usage.cache']] as const).map(([key, label]) => <div key={key}><dt>{t(label)}</dt><dd>{count(row[key])}</dd></div>)}</dl>
          {status(row) && <p className="agent-settings-hint">{status(row)}</p>}
        </article>)}</div>
        {statistics.modelsTruncated && <p className="agent-settings-hint">{t('agent.usage.modelsTruncated')}</p>}
      </>}
      <p className="agent-settings-hint">{t('agent.usage.accountingHint')}</p>
    </>}
  </section>
}
