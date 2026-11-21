import { useLayoutEffect, useRef } from 'react'
import { useI18n } from '../../i18n'
import { ChevronRight } from '../../icons'
import { usePageActive } from '../../page-activity'
import { Alert, Button, Select, Spin } from './model-controls'
import { useGatewayRequests } from './gateway-request-api'
import type { ModelCatalog } from './model-hub-api'

const filters = ['all', 'switched', 'recovered', 'switchFailed'] as const
export type AggregationRequestFilter = typeof filters[number]

export default function AggregationRequestList({ poolId, catalog, active, visible, hours, filter, onHours, onFilter, onRequest }: {
  poolId: string; catalog: ModelCatalog; active: boolean; visible: boolean; hours: number; filter: AggregationRequestFilter
  onHours: (hours: number) => void; onFilter: (filter: AggregationRequestFilter) => void; onRequest: (id: string) => void
}) {
  const { t, locale } = useI18n()
  const pageActive = usePageActive()
  const state = useGatewayRequests(active && visible && pageActive, hours, poolId, '', filter === 'recovered' ? filter : '', null, undefined,
    filter === 'switched' ? 'any' : filter === 'switchFailed' ? 'failed' : '')
  const scroll = useRef<HTMLElement>(null)
  const opened = useRef<{ button: HTMLButtonElement; top: number }>()
  const sources = new Map(catalog.sources.map(source => [source.id, source.name]))
  const count = new Intl.NumberFormat(locale)
  const time = new Intl.DateTimeFormat(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const duration = new Intl.NumberFormat(locale, { style: 'unit', unit: 'millisecond' })

  useLayoutEffect(() => {
    if (!visible || !opened.current || !scroll.current) return
    scroll.current.scrollTop = opened.current.top
    if (opened.current.button.isConnected) opened.current.button.focus({ preventScroll: true })
    opened.current = undefined
  }, [visible])

  return <section ref={scroll} className="tt-routing-editor tt-pool-requests" hidden={!visible} aria-label={t('pool.section.requests')} aria-busy={state.pending}>
    <div className="tt-request-toolbar">
      <label className="agent-settings-field">{t('monitor.range')}<Select<number> aria-label={t('monitor.range')} value={hours} options={[1, 6, 24].map(value => ({ value, label: t('monitor.hours', { hours: value }) }))} onChange={onHours} /></label>
      <label className="agent-settings-field">{t('modelUsage.state')}<Select<AggregationRequestFilter> aria-label={t('modelUsage.state')} value={filter} options={filters.map(value => ({ value, label: t(value === 'recovered' ? 'gatewayTrace.recovered' : 'pool.trace.' + value) }))} onChange={onFilter} /></label>
    </div>
    {state.failed && <Alert type="error" role="alert" message={t('monitor.failed')} action={<Button onClick={state.retry}>{t('agent.retry')}</Button>} />}
    {state.unsupported && <p className="agent-settings-hint">{t('gatewayTrace.unsupported')}</p>}
    {state.pending ? <Spin /> : state.data && (state.data.recent.length ? <>
      <ul className="tt-request-list">
        {state.data.recent.map(row => <li key={row.requestId}>
          <button type="button" onClick={event => {
            opened.current = { button: event.currentTarget, top: scroll.current?.scrollTop || 0 }
            onRequest(row.requestId)
          }}>
            <span className="tt-request-row-model">
              <strong translate="no">{row.upstreamModel || row.model}</strong>
              {row.sourceId && <small>{sources.get(row.sourceId) || t('gatewayTrace.sourceRemoved')}</small>}
              <small>{row.caller === 'external' ? t('hub.gateway.externalClient') : row.caller} · <time dateTime={new Date(row.at).toISOString()}>{time.format(row.at)}</time></small>
            </span>
            <span className="tt-request-row-result">
              <strong className={'tt-request-outcome is-' + row.outcome}>{t('gatewayTrace.' + row.outcome)}</strong>
              {row.switch && <small>{t(row.switch === 'source' ? 'gatewayTrace.crossSourceSwitch' : 'gatewayTrace.sameSourceSwitch')}</small>}
              <small>{t('pool.trace.attemptCount', { count: count.format(row.attempts || 0) })} · {duration.format(row.durationMs)}</small>
            </span>
            <ChevronRight />
          </button>
        </li>)}
      </ul>
      {state.data.recent.length === 50 && <p className="agent-settings-hint">{t('gatewayTrace.recentLimit')}</p>}
    </> : <p className="agent-settings-hint">{t(filter === 'all' ? 'gatewayTrace.empty' : 'hub.directory.noMatches')}</p>)}
  </section>
}
