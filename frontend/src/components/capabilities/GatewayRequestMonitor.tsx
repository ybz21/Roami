import { useId, useState } from 'react'
import { usePageActive } from '../../page-activity'
import { CloseIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { Alert, Button, Select, Spin } from './model-controls'
import type { ModelCatalog } from './model-hub-api'
import { requestFailureReasons, successfulRequests, useGatewayRequestSummary, type RequestFailureReason, type RequestWindow } from './gateway-request-api'
import GatewayRequestDiagnostics from './GatewayRequestDiagnostics'

const outcomes = ['blocked', 'exhausted', 'interrupted', 'failed', 'recovered', 'success', 'uncertain'] as const
const series = ['success', 'recovered', 'failed', 'uncertain'] as const
const failureLabel = (reason: RequestFailureReason) => 'gatewayTrace.' + (reason === 'quota' ? 'reason.quota' : reason)

export default function GatewayRequestMonitor({ active, catalog, onAudit }: {
  active: boolean; catalog: ModelCatalog | null; onAudit?: () => void
}) {
  const { t, locale } = useI18n()
  const [hours, setHours] = useState(1)
  const [route, setRoute] = useState('')
  const [caller, setCaller] = useState('')
  const [window, setWindow] = useState<RequestWindow | null>(null)
  const [outcome, setOutcome] = useState('')
  const [reason, setReason] = useState<RequestFailureReason>()
  const [preferReasons, setPreferReasons] = useState(true)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filterId = useId()
  const pageActive = usePageActive()
  const state = useGatewayRequestSummary(active && pageActive, hours, route, caller, outcome, window, reason)

  const data = state.data
  const names = new Map([...Object.entries(data?.routes || {}), ...(catalog?.models.map(model => [model.id, model.name] as const) || [])])
  if (route && !names.has(route)) names.set(route, route)
  const callers = new Set([...Object.keys(data?.callers || {}), ...(caller ? [caller] : [])])
  const number = new Intl.NumberFormat(locale)
  const rate = new Intl.NumberFormat(locale, { maximumSignificantDigits: 3 })
  const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 })
  const clock = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
  const stamp = new Intl.DateTimeFormat(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const peak = Math.max(1, ...(data?.points.map(point => point.totals.requests) || []))
  const count = (value: number) => number.format(value)
  const callerName = (value: string) => value === 'external' ? t('hub.gateway.externalClient') : value
  const selected = !!(route || caller || window || outcome || reason)
  const windowLabel = window && stamp.formatRange(window.from, window.to)
  const failureRows = requestFailureReasons.filter(key => data?.failureReasons?.[key] || reason === key)
  const showReasons = preferReasons && failureRows.length > 0
  const breakdownLabel = t(showReasons ? 'gatewayTrace.failureBreakdown' : 'gatewayTrace.breakdown')
  const breakdown = showReasons ? failureRows.map(key => ({
    key, label: t(failureLabel(key)), total: data?.failureReasons?.[key] || 0, pressed: reason === key, tone: 'failed',
    toggle: () => { setOutcome(''); setReason(reason === key ? undefined : key) },
  })) : outcomes.filter(key => data?.outcomes[key] || outcome === key).map(key => ({
    key, label: t('gatewayTrace.' + key), total: data?.outcomes[key] || 0, pressed: outcome === key, tone: key,
    toggle: () => { setReason(undefined); setOutcome(outcome === key ? '' : key) },
  }))
  breakdown.sort((a, b) => b.total - a.total)
  const breakdownTotal = breakdown.reduce((total, row) => total + row.total, 0)
  const select = (label: string, value: string, options: { value: string; label: string }[], change: (value: string) => void) =>
    <label className="agent-settings-field">{label}<Select virtual={false} aria-label={label} value={value} options={options} onChange={change} /></label>
  const filterChip = (label: string, clear: () => void) =>
    <button type="button" className="tt-act" aria-label={t('gatewayTrace.removeFilter', { label })} onClick={clear}><span>{label}</span><CloseIcon size={14} /></button>

  return <section className="tt-request-monitor" hidden={!active} aria-label={t('gatewayTrace.requests')}>
    <div className="tt-request-toolbar">
      <label className="agent-settings-field">{t('monitor.range')}<Select virtual={false} aria-label={t('monitor.range')} value={hours} options={[1, 6, 24].map(value => ({ value, label: value === 1 ? t('gatewayTrace.lastHour') : t('monitor.hours', { hours: value }) }))} onChange={value => { setHours(value); setWindow(null) }} /></label>
      <Button aria-expanded={filtersOpen} aria-controls={filterId} onClick={() => setFiltersOpen(open => !open)}>{t('modelUsage.filters')}</Button>
      {onAudit && <Button className="tt-request-open-audit" onClick={onAudit}>{t('gatewayTrace.openAudit')}</Button>}
    </div>
    <div className="tt-request-toolbar" id={filterId} hidden={!filtersOpen}>
      {select(t('monitor.model'), route, [{ value: '', label: t('monitor.allModels') }, ...[...names].map(([value, label]) => ({ value, label }))], setRoute)}
      {select(t('gatewayTrace.caller'), caller, [{ value: '', label: t('gatewayTrace.allCallers') }, ...[...callers].map(value => ({ value, label: callerName(value) }))], setCaller)}
    </div>
    {selected && <div className="tt-request-filter-chips">
      {route && filterChip(names.get(route) || route, () => setRoute(''))}
      {caller && filterChip(callerName(caller), () => setCaller(''))}
      {windowLabel && filterChip(windowLabel, () => setWindow(null))}
      {outcome && filterChip(t('gatewayTrace.' + outcome), () => setOutcome(''))}
      {reason && filterChip(t(failureLabel(reason)), () => setReason(undefined))}
    </div>}
    {state.failed && <Alert type="error" role="alert" message={t('monitor.failed')} action={<Button onClick={state.retry}>{t('agent.retry')}</Button>} />}
    {state.pending && data && <p className="agent-settings-hint" role="status">{t('gatewayTrace.updating')}</p>}
    {!data ? state.unsupported ? <p className="agent-settings-hint">{t('gatewayTrace.summaryUnsupported')}</p> : !state.failed && <Spin /> :
      <div aria-busy={state.pending}>
        {data.totals.requests > 0 && <dl className="tt-request-totals">
          <div><dt>{t('gatewayTrace.requests')}</dt><dd>{count(data.totals.requests)}</dd></div>
          <div><dt>{t('gatewayTrace.requestRate')}</dt><dd>{t('gatewayTrace.perMinute', { value: rate.format(data.totals.requests * 60_000 / (data.range.to - data.range.from)) })}</dd></div>
          <div><dt>{t('gatewayTrace.successRate')}</dt><dd>{percent.format(successfulRequests(data.totals) / data.totals.requests)}</dd></div>
          <div><dt>{t('gatewayTrace.finalFailures')}</dt><dd className={data.totals.failed ? 'is-failed' : undefined}>{count(data.totals.failed)}</dd></div>
          <div><dt>{t('gatewayTrace.recovered')}</dt><dd className={data.totals.recovered ? 'is-recovered' : undefined}>{count(data.totals.recovered)}</dd></div>
        </dl>}
        {(breakdown.length > 0 || data.points.some(point => point.totals.requests > 0) || window) && <div className="tt-request-charts">
          <section className="tt-request-trend" aria-label={t('gatewayTrace.volume')}>
            <div className="tt-request-section-head"><h3>{t('gatewayTrace.volume')}</h3></div>
            <div className="tt-request-legend">{series.map(key => <span key={key} className={'is-' + key}>{t('gatewayTrace.' + key)}</span>)}</div>
            <div className="tt-request-plot">
              <div className="tt-request-scale" aria-hidden="true"><span>{count(peak)}</span><span>{count(0)}</span></div>
              <div className="tt-request-bars" role="group" aria-label={t('gatewayTrace.volume')}>
                {data.points.map((point, index) => {
                  const totals = point.totals
                  const groups = { success: successfulRequests(totals) - totals.recovered, recovered: totals.recovered, failed: totals.failed, uncertain: totals.uncertain }
                  const label = t('gatewayTrace.bucket', { time: stamp.formatRange(point.from, point.to), count: count(totals.requests), failed: count(totals.failed), recovered: count(totals.recovered) })
                  const pressed = window?.from === point.from
                  return <button type="button" key={index} aria-pressed={pressed} aria-label={label} onClick={() => setWindow(pressed ? null : { from: point.from, to: point.to, end: data.now })}>
                    <span className="tt-request-bar-stack" aria-hidden="true">{series.map(key => <i key={key} className={'is-' + key} style={{ height: groups[key] / peak * 100 + '%' }} />)}</span>
                    <time dateTime={new Date(point.from).toISOString()}>{clock.format(point.from)}</time>
                  </button>
                })}
              </div>
            </div>
          </section>
          <section className="tt-request-breakdown" aria-label={breakdownLabel}>
            <div className="tt-request-section-head">
              <h3>{breakdownLabel}</h3>
              {failureRows.length > 0 && <Button onClick={() => setPreferReasons(!showReasons)}>{t(showReasons ? 'gatewayTrace.breakdown' : 'gatewayTrace.failureBreakdown')}</Button>}
            </div>
            {breakdown.length ? <ul className="tt-request-outcomes">
              {breakdown.map(row => <li key={row.key}>
                <button className={'tt-act is-' + row.tone} type="button" aria-pressed={row.pressed} onClick={row.toggle}>
                  <span>{row.label}</span><strong>{count(row.total)} · {breakdownTotal ? percent.format(row.total / breakdownTotal) : percent.format(0)}</strong>
                  <span className="tt-request-outcome-track" aria-hidden="true"><i style={{ width: (breakdownTotal ? row.total / breakdownTotal * 100 : 0) + '%' }} /></span>
                </button>
              </li>)}
            </ul> : <p className="agent-settings-hint">{t('gatewayTrace.empty')}</p>}
          </section>
        </div>}
        {data.totals.requests > 0
          ? <GatewayRequestDiagnostics data={data} names={names} sources={catalog?.sources} />
          : <p className="agent-settings-hint">{t(selected ? 'gatewayTrace.filteredEmpty' : 'gatewayTrace.empty')}</p>}
      </div>}
  </section>
}
