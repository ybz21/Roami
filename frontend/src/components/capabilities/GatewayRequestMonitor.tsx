import { useState } from 'react'
import { usePageActive } from '../../page-activity'
import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import { Alert, Button, Select, Spin } from './model-controls'
import type { ModelCatalog } from './model-hub-api'
import { useGatewayRequests, type RequestWindow } from './gateway-request-api'

const outcomes = ['blocked', 'exhausted', 'interrupted', 'failed', 'recovered', 'success', 'uncertain'] as const

export default function GatewayRequestMonitor({ active, catalog, onRequest }: {
  active: boolean; catalog: ModelCatalog | null; onRequest: (id: string) => void
}) {
  const { t, locale } = useI18n()
  const [hours, setHours] = useState(6), [route, setRoute] = useState(''), [caller, setCaller] = useState('')
  const [window, setWindow] = useState<RequestWindow | null>(null), [outcome, setOutcome] = useState('')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const pageActive = usePageActive()
  const state = useGatewayRequests(active && pageActive, hours, route, caller, outcome, window)
  const data = state.data
  const names = new Map([...Object.entries(data?.routes || {}), ...(catalog?.models.map(model => [model.id, model.name] as const) || [])])
  if (route && !names.has(route)) names.set(route, route)
  const callers = new Set([...Object.keys(data?.callers || {}), ...(caller ? [caller] : [])])
  const number = new Intl.NumberFormat(locale)
  const clock = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' })
  const stamp = new Intl.DateTimeFormat(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const peak = Math.max(1, ...(data?.points.map(point => point.totals.requests) || []))
  const count = (value: number) => number.format(value)
  const callerName = (value: string) => value === 'external' ? t('hub.gateway.externalClient') : value
  const selected = !!(route || caller)
  const select = (label: string, value: string, options: { value: string; label: string }[], change: (value: string) => void) =>
    <label className="agent-settings-field">{label}<Select virtual={false} aria-label={label} value={value} options={options} onChange={change} /></label>

  return <section className="tt-request-monitor" hidden={!active} aria-label={t('gatewayTrace.requests')} aria-busy={state.pending}>
    <div className="tt-request-toolbar">
      <label className="agent-settings-field">{t('monitor.range')}<Select virtual={false} aria-label={t('monitor.range')} value={hours} options={[1, 6, 24].map(value => ({ value, label: t('monitor.hours', { hours: value }) }))} onChange={value => { setHours(value); setWindow(null) }} /></label>
      <Button aria-expanded={filtersOpen} onClick={() => setFiltersOpen(open => !open)}>{t('modelUsage.filters')}</Button>
      {selected && <span>{[route && names.get(route), callerName(caller)].filter(Boolean).join(' · ')}</span>}
    </div>
    {filtersOpen && <div className="tt-request-toolbar">
      {select(t('monitor.model'), route, [{ value: '', label: t('monitor.allModels') }, ...[...names].map(([value, label]) => ({ value, label }))], setRoute)}
      {select(t('gatewayTrace.caller'), caller, [{ value: '', label: t('gatewayTrace.allCallers') }, ...[...callers].map(value => ({ value, label: callerName(value) }))], setCaller)}
    </div>}
    {state.failed && <Alert type="error" role="alert" message={t('monitor.failed')} action={<Button onClick={state.retry}>{t('agent.retry')}</Button>} />}
    {!data ? state.unsupported ? <p className="agent-settings-hint">{t('gatewayTrace.unsupported')}</p> : !state.failed && <Spin /> : <>
      {data.totals.requests > 0 && <>
        <dl className="tt-request-totals">
          <div><dt>{t('gatewayTrace.requests')}</dt><dd>{count(data.totals.requests)}</dd></div>
          <div><dt>{t('gatewayTrace.finalFailures')}</dt><dd className="is-failed">{count(data.totals.failed)}</dd></div>
          <div><dt>{t('gatewayTrace.recovered')}</dt><dd className="is-recovered">{count(data.totals.recovered)}</dd></div>
        </dl>
        <section className="tt-request-trend" aria-label={t('monitor.trend')}>
          <div className="tt-request-section-head"><h3>{t('monitor.trend')}</h3><div className="tt-request-legend">{(['success', 'recovered', 'failed', 'uncertain'] as const).map(key => <span key={key} className={'is-' + key}>{t('gatewayTrace.' + key)}</span>)}</div></div>
          <div className="tt-request-bars" role="group" aria-label={t('monitor.trend')}>
            {data.points.map((point, index) => {
              const totals = point.totals
              const groups = { success: totals.requests - totals.failed - totals.recovered - totals.uncertain, recovered: totals.recovered, failed: totals.failed, uncertain: totals.uncertain }
              const label = t('gatewayTrace.bucket', { time: clock.format(point.from), count: count(totals.requests), failed: count(totals.failed), recovered: count(totals.recovered) })
              const pressed = window?.from === point.from
              return <button type="button" key={index} aria-pressed={pressed} aria-label={label} onClick={() => setWindow(pressed ? null : { from: point.from, to: point.to, end: data.now })}>
                <span className="tt-request-bar-stack" aria-hidden="true">{Object.entries(groups).map(([key, value]) => <i key={key} className={'is-' + key} style={{ height: value / peak * 100 + '%' }} />)}</span>
                <time>{clock.format(point.from)}</time>
              </button>
            })}
          </div>
        </section>
      </>}
      <div className="tt-request-section-head"><h3>{t('gatewayTrace.recent')}</h3>{window && <Button onClick={() => setWindow(null)}>{clock.format(window.from)} – {clock.format(window.to)} · {t('modelUsage.clear')}</Button>}</div>
      {Object.keys(data.outcomes).length > 0 && <div className="tt-request-outcomes" role="group" aria-label={t('gatewayTrace.filterOutcome')}>
        {outcomes.filter(key => data.outcomes[key] || outcome === key).map(key =>
          <button className="tt-act" type="button" aria-pressed={outcome === key} key={key} onClick={() => setOutcome(outcome === key ? '' : key)}>{t('gatewayTrace.' + key)} <strong>{count(data.outcomes[key] || 0)}</strong></button>
        )}
      </div>}
      {!data.recent.length ? <p className="agent-settings-hint">{t(window || outcome || selected ? 'hub.directory.noMatches' : 'gatewayTrace.empty')}</p> :
        <ul className="tt-request-list">{data.recent.map(row =>
          <li key={row.requestId}><button type="button" className="tt-act" disabled={state.pending} onClick={() => onRequest(row.requestId)}>
            <strong>{names.get(row.routeId) || row.model}</strong><span className={'tt-request-outcome is-' + row.outcome}>{t('gatewayTrace.' + row.outcome)}</span>
            <small>{callerName(row.caller)} · {stamp.format(row.at)}</small>{row.status > 0 && <small>HTTP {row.status}</small>}<ChevronRight />
          </button></li>
        )}</ul>}
      {data.recent.length === 50 && <p className="agent-settings-hint">{t('gatewayTrace.recentLimit')}</p>}
    </>}
  </section>
}
