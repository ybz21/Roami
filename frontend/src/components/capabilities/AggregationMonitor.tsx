import { useState } from 'react'
import { useI18n } from '../../i18n'
import { usePageActive } from '../../page-activity'
import { Alert, Button, Select, Spin } from './model-controls'
import { successfulRequests, useGatewayRequestSummary, type RequestTotals } from './gateway-request-api'
import './gateway-request.css'
import './aggregation-monitor.css'

type Series = { key: string; label: string; count: (totals: RequestTotals) => number }
type Point = { from: number; to: number; totals: RequestTotals }

function AggregationTrend({ title, points, series, totals }: {
  title: string; points: Point[]; series: Series[]; totals?: RequestTotals
}) {
  const { t, locale } = useI18n()
  const number = new Intl.NumberFormat(locale)
  const clock = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
  const stamp = new Intl.DateTimeFormat(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const list = new Intl.ListFormat(locale)
  const peak = Math.max(1, ...points.map(point => series.reduce((sum, row) => sum + row.count(point.totals), 0)))

  return <>
    <h3>{title}</h3>
    <div className="tt-request-legend">{series.map(row => <span key={row.key} className={'is-' + row.key}>
      {row.label}{totals && <strong>{number.format(row.count(totals))}</strong>}
    </span>)}</div>
    <div className="tt-request-plot">
      <div className="tt-request-scale" aria-hidden="true"><span>{number.format(peak)}</span><span>{number.format(0)}</span></div>
      <ol className="tt-request-bars tt-pool-monitor-bars" role="list" aria-label={title}>
        {points.map(point => {
          const range = stamp.formatRange(point.from, point.to)
          const counts = list.format(series.map(row => `${row.label} ${number.format(row.count(point.totals))}`))
          const label = t('pool.monitor.bucket', { range, counts })
          return <li key={point.from} title={label} aria-label={label}>
            <span className="tt-request-bar-stack" aria-hidden="true">{series.map(row =>
              <i key={row.key} className={'is-' + row.key} style={{ height: row.count(point.totals) / peak * 100 + '%' }} />
            )}</span>
            <time dateTime={new Date(point.from).toISOString()} aria-hidden="true">{clock.format(point.from)}</time>
          </li>
        })}
      </ol>
    </div>
  </>
}

export default function AggregationMonitor({ poolId, visible, active }: { poolId: string; visible: boolean; active: boolean }) {
  const { t, locale } = useI18n()
  const pageActive = usePageActive()
  const [hours, setHours] = useState(6)
  const state = useGatewayRequestSummary(active && visible && pageActive, hours, poolId, '', '', null)
  const data = state.pending ? undefined : state.data
  const number = new Intl.NumberFormat(locale)
  const outcomes: Series[] = [
    { key: 'success', label: t('gatewayTrace.success'), count: successfulRequests },
    { key: 'failed', label: t('gatewayTrace.failed'), count: totals => totals.failed },
    { key: 'uncertain', label: t('gatewayTrace.uncertain'), count: totals => totals.uncertain },
  ]
  const switches: Series[] = [
    { key: 'same-source', label: t('gatewayTrace.sameSourceSwitch'), count: totals => totals.sameSource },
    { key: 'cross-source', label: t('gatewayTrace.crossSourceSwitch'), count: totals => totals.crossSource },
  ]

  return <section className="tt-routing-editor tt-pool-monitor" hidden={!visible} aria-label={t('pool.section.monitor')} aria-busy={state.pending}>
    <div className="tt-request-toolbar">
      <label className="agent-settings-field">{t('monitor.range')}<Select<number> aria-label={t('monitor.range')} value={hours} options={[1, 6, 24].map(value => ({ value, label: t('monitor.hours', { hours: value }) }))} onChange={setHours} /></label>
    </div>
    {state.failed && <Alert type="error" role="alert" message={t('monitor.failed')} action={<Button onClick={state.retry}>{t('agent.retry')}</Button>} />}
    {state.unsupported && <p className="agent-settings-hint">{t('gatewayTrace.unsupported')}</p>}
    {state.pending ? <Spin /> : data && (data.totals.requests === 0 ? <p className="agent-settings-hint">{t('gatewayTrace.empty')}</p> : <>
      <dl className="tt-request-totals">
        <div><dt>{t('gatewayTrace.requests')}</dt><dd>{number.format(data.totals.requests)}</dd></div>
        <div><dt>{t('gatewayTrace.success')}</dt><dd>{number.format(successfulRequests(data.totals))}</dd></div>
        <div><dt>{t('gatewayTrace.failed')}</dt><dd className={data.totals.failed ? 'is-failed' : undefined}>{number.format(data.totals.failed)}</dd></div>
      </dl>
      <div className="tt-request-charts tt-pool-monitor-charts">
        <section className="tt-request-trend"><AggregationTrend title={t('pool.monitor.requestTrend')} points={data.points} series={outcomes} /></section>
        <section className="tt-request-breakdown"><AggregationTrend title={t('pool.monitor.switchTrend')} points={data.points} series={switches} totals={data.totals} /></section>
      </div>
    </>)}
  </section>
}
