import { useEffect, useRef, useState } from 'react'
import { App } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { ChevronRight, CopyIcon } from '../../icons'
import BackButton from '../BackButton'
import MobileSubPage from '../MobileSubPage'
import { chargeText } from '../settings/model-charges'
import { Alert, Button, Spin } from './model-controls'
import type { ModelCatalog } from './model-hub-api'
import { loadRequestDetail, type RequestAttempt, type RequestDetail, type RequestOutcome } from './gateway-request-api'

const knownReasons = ['source', 'authorization', 'directory', 'notListed', 'tools', 'context', 'pricing', 'quota', 'cooldown']
const feeStateLabel = {
  pending: 'gatewayTrace.feePending',
  unknown: 'agent.proxy.state.unknown',
  unrecorded: 'gatewayTrace.feeUnrecorded',
  missing: 'gatewayTrace.feeMissing',
  unavailable: 'gatewayTrace.feeUnavailable',
}

function attemptReason(attempt: RequestAttempt, outcome: RequestOutcome) {
  if (attempt.success) return 'success'
  if (attempt.status === 429) return 'upstreamLimited'
  if (attempt.status === 402) return 'reason.quota'
  if (attempt.status === 401 || attempt.status === 403) return 'upstreamUnauthorized'
  if (attempt.status === 408 || attempt.status === 504) return 'upstreamTimeout'
  if (attempt.error === 'MODEL_TRANSPORT_FAILED') return 'connectFailed'
  if (attempt.status === 0) return 'noResponse'
  return attempt.status >= 200 && attempt.status < 300 && outcome === 'interrupted' ? 'interrupted' : 'failed'
}

export default function GatewayRequestDetail({ id, catalog, onBack, onSource, onPool, onLimits }: {
  id: string; catalog: ModelCatalog; onBack: () => void; onSource: (id: string) => void; onPool: (id: string) => void; onLimits: () => void
}) {
  const { t, locale } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const [result, setResult] = useState<{ data?: RequestDetail; failure?: 'missing' | 'requestFailed' }>()
  const [retry, setRetry] = useState(0)
  const resultHeading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    const controller = new AbortController()
    loadRequestDetail(id, controller.signal).then(({ data }) => {
      if (!controller.signal.aborted) setResult({ data })
    }).catch(error => {
      if (!controller.signal.aborted) setResult({ failure: error.status === 404 ? 'missing' : 'requestFailed' })
    })
    return () => controller.abort()
  }, [id, retry])
  const data = result?.data
  const row = data?.request
  useEffect(() => {
    if (row) resultHeading.current?.focus({ preventScroll: true })
  }, [row])
  const when = row && new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'medium' }).format(row.at)
  const sources = new Map(catalog.sources.map(source => [source.id, source.name]))
  const pool = catalog.models.find(model => model.aggregate && row && (model.id === row.routeId || model.aliases?.includes(row.routeId)))
  const knownSource = row && sources.get(row.sourceId)
  const finished = row?.outcome === 'success' || row?.outcome === 'recovered'
  const switchType = row?.switch === 'source' ? 'crossSourceSwitch' : row?.switch === 'model' ? 'sameSourceSwitch' : ''
  const attempts = data?.attempts.slice().sort((left, right) => left.attempt - right.attempt) || []
  const title = t('gatewayTrace.detail')
  const count = new Intl.NumberFormat(locale)
  const attemptTime = new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })
  const attemptFee = (billing: RequestAttempt['billing']) => {
    if (!billing) return null
    if (billing.state !== 'settled') return t(feeStateLabel[billing.state])
    return billing.currency && billing.cost != null ? chargeText([{ currency: billing.currency, amount: billing.cost }], locale)
      : t('agent.proxy.state.unknown')
  }
  const body = <div className="tt-request-detail-scroll">
    {result?.failure ? <Alert type="error" role="alert" message={t('gatewayTrace.' + result.failure)}
      action={result.failure === 'requestFailed' && <Button onClick={() => { setResult(undefined); setRetry(value => value + 1) }}>{t('agent.retry')}</Button>} /> : !row ? <Spin /> : <>
      <header className="tt-request-detail-result">
        <h3 ref={resultHeading} tabIndex={-1} className={'tt-request-outcome is-' + row.outcome}>{t('gatewayTrace.' + row.outcome)}</h3>
        <p><strong>{pool?.name || row.model}</strong> · {row.caller === 'external' ? t('hub.gateway.externalClient') : row.caller} · <time dateTime={new Date(row.at).toISOString()}>{when}</time></p>
        {row.outcome === 'blocked' && <p>{t('gatewayTrace.blockedBeforeSend')}</p>}
      </header>
      <dl className="tt-request-totals">
        <div><dt>{t('gatewayTrace.response')}</dt><dd>{row.status > 0 ? 'HTTP ' + row.status : t('gatewayTrace.noResponse')}</dd></div>
        <div><dt>{t('gatewayTrace.attempts')}</dt><dd>{count.format(row.attempts || 0)}</dd></div>
        <div><dt>{t('gatewayTrace.duration')}</dt><dd>{count.format(row.durationMs)} ms</dd></div>
      </dl>
      {(row.upstreamModel || row.sourceId) && <dl className="tt-request-totals tt-request-routing-summary">
        <div>
          <dt>{t(finished ? 'gatewayTrace.actualHit' : 'gatewayTrace.lastAttempt')}</dt>
          <dd>{row.upstreamModel && <span translate="no">{row.upstreamModel}</span>}{row.sourceId && <small>{knownSource || t('gatewayTrace.sourceRemoved')}</small>}</dd>
        </div>
        {switchType && <div><dt>{t('gatewayTrace.latestSwitch')}</dt><dd>{t('gatewayTrace.' + switchType)}</dd></div>}
      </dl>}
      {row.outcome === 'blocked' && <section className="tt-request-blocks"><h3>{t('gatewayTrace.whyBlocked')}</h3>
        {Object.keys(row.blocks || {}).length > 0
          ? <ul>{Object.entries(row.blocks || {}).map(([reason, total]) => <li key={reason}>
            <span>{t('gatewayTrace.reason.' + (knownReasons.includes(reason) ? reason : 'unknown'))}</span><strong>{count.format(total)}</strong>
          </li>)}</ul>
          : <p className="agent-settings-hint">{t('gatewayTrace.reason.unknown')}</p>}
      </section>}
      {!!attempts.length && <section className="tt-request-path"><h3>{t('gatewayTrace.path')}</h3>
        <ol>{attempts.map(attempt => <li key={attempt.attempt}>
          <span className={'tt-request-path-step ' + (attempt.success ? 'is-success' : 'is-failed')} aria-label={t('gatewayTrace.step', { step: count.format(attempt.attempt) })}>{count.format(attempt.attempt)}</span>
          <div>
            <strong translate="no">{attempt.model}</strong>
            <span>{sources.get(attempt.sourceId) || t('gatewayTrace.sourceRemoved')}</span>
            {attempt.billing && <span>{t('agent.usage.cost')} · {attemptFee(attempt.billing)}</span>}
          </div>
          <div className="tt-request-path-result">
            <strong className={'tt-request-outcome ' + (attempt.success ? 'is-success' : 'is-failed')}>{t('gatewayTrace.' + attemptReason(attempt, row.outcome))}</strong>
            {attempt.status > 0 && <small>HTTP {attempt.status}</small>}
            {attempt.at > 0 && <time dateTime={new Date(attempt.at).toISOString()}>{attemptTime.format(attempt.at)}</time>}
          </div>
        </li>)}</ol>
      </section>}
      {data && !data.complete && <p className="agent-settings-hint">{t('gatewayTrace.partial')}</p>}
      <div className="tt-request-actions">
        {pool && <Button onClick={() => onPool(pool.id)}>{t('gatewayWorkspace.viewPool')}</Button>}
        {knownSource && <Button onClick={() => onSource(row.sourceId)}>{t('gatewayWorkspace.viewSource')}</Button>}
        {row.error === 'MODEL_PROXY_DAILY_LIMIT' && <Button onClick={onLimits}>{t('gatewayTrace.viewLimits')}</Button>}
      </div>
      <details className="tt-routing-guide tt-request-technical"><summary><ChevronRight />{t('gatewayTrace.technical')}</summary>
        {!!row.error && <p><code>{row.error}</code></p>}
        {attempts.map(attempt => (attempt.error || attempt.billing?.upstreamRequestId) && <div key={attempt.attempt}>
          <p>{t('gatewayTrace.step', { step: count.format(attempt.attempt) })} {attempt.error && <code>{attempt.error}</code>}</p>
          {attempt.billing?.upstreamRequestId && <p>{t('agent.gateway.upstreamRequestId')} <code translate="no">{attempt.billing.upstreamRequestId}</code></p>}
        </div>)}
        <p>{t('gatewayTrace.requestId')} <code>{row.requestId}</code></p>
        <Button icon={<CopyIcon />} onClick={async () => {
          try { await navigator.clipboard.writeText(row.requestId); message.success(t('common.copied')) }
          catch { message.error(t('gatewayWorkspace.copyFailed')) }
        }}>{t('gatewayTrace.copyRequest')}</Button>
      </details>
    </>}
  </div>
  return phone ? <MobileSubPage title={title} onBack={onBack} manageHistory={false} search={false}>{body}</MobileSubPage>
    : <section className="tt-request-detail" aria-label={title}><header className="tt-pagehead"><BackButton onClick={onBack} /><h2>{title}</h2></header>{body}</section>
}
