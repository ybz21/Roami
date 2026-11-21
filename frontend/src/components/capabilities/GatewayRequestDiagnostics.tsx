import { useState } from 'react'
import { useI18n } from '../../i18n'
import { Button } from './model-controls'
import { successfulRequests, type RequestGroup, type RequestSummary } from './gateway-request-api'
import type { ModelSource } from './model-hub-api'

const initialRows = 6

function RequestGroupSummary({ title, dimension, rows, name }: {
  title: string; dimension: string; rows: RequestGroup[]; name: (id: string) => string
}) {
  const { t, locale } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const count = new Intl.NumberFormat(locale)
  const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 })
  return <section className="tt-request-panel">
    <h3>{title}</h3>
    <table className="tt-request-metric-table" aria-label={title}>
      <thead><tr>
        <th scope="col">{dimension}</th>
        <th scope="col">{t('gatewayTrace.requests')}</th>
        <th scope="col">{t('gatewayTrace.successRate')}</th>
        <th scope="col">{t('gatewayTrace.finalFailures')}</th>
      </tr></thead>
      <tbody>{rows.slice(0, expanded ? rows.length : initialRows).map(({ id, totals }) =>
        <tr key={id}>
          <th scope="row">{name(id)}</th>
          <td>{count.format(totals.requests)}</td>
          <td>{percent.format(successfulRequests(totals) / totals.requests)}</td>
          <td className={totals.failed ? 'is-failed' : undefined}>{count.format(totals.failed)}</td>
        </tr>)}
      </tbody>
    </table>
    {rows.length > initialRows && <Button type="text" aria-expanded={expanded} onClick={() => setExpanded(current => !current)}>
      {t(expanded ? 'gatewayTrace.showFewerGroups' : 'gatewayTrace.showAllGroups', { count: count.format(rows.length) })}
    </Button>}
  </section>
}

export default function GatewayRequestDiagnostics({ data, names, sources = [] }: {
  data: RequestSummary; names: ReadonlyMap<string, string>; sources?: ModelSource[]
}) {
  const { t, locale } = useI18n()
  const count = new Intl.NumberFormat(locale)
  const ms = new Intl.NumberFormat(locale, { style: 'unit', unit: 'millisecond', maximumFractionDigits: 1 })
  const rate = new Intl.NumberFormat(locale, { maximumSignificantDigits: 3 })
  const sourceNames = new Map(sources.map(source => [source.id, source.name]))
  const durationSeconds = (data.range.to - data.range.from) / 1000
  const latency = [
    { label: t('gatewayTrace.firstTokenLatency'), stats: data.firstToken },
    { label: t('gatewayTrace.totalLatency'), stats: data.duration },
  ]
  return <>
    <div className="tt-request-panels">
      <section className="tt-request-panel">
        <h3>{t('gatewayTrace.latency')}</h3>
        <table className="tt-request-metric-table tt-request-latency" aria-label={t('gatewayTrace.latency')}>
          <thead><tr>
            <th scope="col">{t('monitor.metric')}</th>
            {[50, 95, 99].map(value => <th scope="col" key={value}>{t('gatewayTrace.percentile', { value })}</th>)}
          </tr></thead>
          <tbody>{latency.map(({ label, stats }) => <tr key={label}>
            <th scope="row">{label}{stats && <small>{t('gatewayTrace.samples', { count: count.format(stats.samples) })}</small>}</th>
            {stats ? <><td>{ms.format(stats.p50)}</td><td>{ms.format(stats.p95)}</td><td>{ms.format(stats.p99)}</td></>
              : <td colSpan={3}>{t('gatewayTrace.noSamples')}</td>}
          </tr>)}</tbody>
        </table>
        <p className="agent-settings-hint">{t('gatewayTrace.latencyScope')}</p>
      </section>
      <section className="tt-request-panel">
        <h3>{t('gatewayTrace.tokenThroughput')}</h3>
        {data.tokens.samples > 0 ? <>
          <dl className="tt-request-throughput">
            <div><dt>{t('gatewayTrace.inputTokens')}</dt><dd>{t('gatewayTrace.tokensPerSecond', { value: rate.format(data.tokens.input / durationSeconds) })}</dd>
              <dd><small>{t('gatewayTrace.tokenCount', { count: count.format(data.tokens.input) })}</small></dd></div>
            <div><dt>{t('gatewayTrace.outputTokens')}</dt><dd>{t('gatewayTrace.tokensPerSecond', { value: rate.format(data.tokens.output / durationSeconds) })}</dd>
              <dd><small>{t('gatewayTrace.tokenCount', { count: count.format(data.tokens.output) })}</small></dd></div>
          </dl>
          <p className="agent-settings-hint">{t('gatewayTrace.tokenCoverage', { count: count.format(data.tokens.samples), total: count.format(successfulRequests(data.totals)) })}</p>
        </> : <p className="agent-settings-hint">{t('gatewayTrace.noUsage')}</p>}
      </section>
    </div>
    <div className="tt-request-panels">
      <RequestGroupSummary title={t('gatewayTrace.byModel')} dimension={t('monitor.model')} rows={data.byModel} name={id => names.get(id) || id} />
      <RequestGroupSummary title={t('gatewayTrace.bySource')} dimension={t('hub.source')} rows={data.bySource} name={id => id ? sourceNames.get(id) || id : t('gatewayTrace.noSource')} />
    </div>
  </>
}
