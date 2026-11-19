import { useEffect, useState } from 'react'
import { App } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { CopyIcon } from '../../icons'
import BackButton from '../BackButton'
import MobileSubPage from '../MobileSubPage'
import { Alert, Button, Spin } from './model-controls'
import type { ModelCatalog } from './model-hub-api'
import { loadRequestDetail, type RequestDetail } from './gateway-request-api'

const knownReasons = ['source', 'authorization', 'directory', 'notListed', 'tools', 'context', 'pricing', 'quota', 'cooldown']

export default function GatewayRequestDetail({ id, catalog, onBack, onSource, onPool, onLimits }: {
  id: string; catalog: ModelCatalog; onBack: () => void; onSource: (id: string) => void; onPool: (id: string) => void; onLimits: () => void
}) {
  const { t, locale } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const [result, setResult] = useState<{ data?: RequestDetail; failure?: 'missing' | 'requestFailed' }>()
  const [retry, setRetry] = useState(0)
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
  const when = row && new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'medium' }).format(row.at)
  const sources = new Map(catalog.sources.map(source => [source.id, source.name]))
  const pool = catalog.models.find(model => model.aggregate && row && (model.id === row.routeId || model.aliases?.includes(row.routeId)))
  const knownSource = row && sources.get(row.sourceId)
  const title = t('gatewayTrace.detail')
  const count = new Intl.NumberFormat(locale)
  const body = <div className="tt-request-detail-scroll">
    {result?.failure ? <Alert type="error" role="alert" message={t('gatewayTrace.' + result.failure)}
      action={result.failure === 'requestFailed' && <Button onClick={() => { setResult(undefined); setRetry(value => value + 1) }}>{t('agent.retry')}</Button>} /> : !row ? <Spin /> : <>
      <header className="tt-request-detail-result">
        <div><h3>{pool?.name || row.model}</h3><p>{row.caller === 'external' ? t('hub.gateway.externalClient') : row.caller} · <time>{when}</time></p></div>
        <strong className={'tt-request-outcome is-' + row.outcome}>{t('gatewayTrace.' + row.outcome)}</strong>
      </header>
      <dl className="tt-request-totals">
        <div><dt>{t('gatewayTrace.response')}</dt><dd>{row.status > 0 ? 'HTTP ' + row.status : t('monitor.pending')}</dd></div>
        <div><dt>{t('gatewayTrace.attempts')}</dt><dd>{count.format(row.attempts || 0)}</dd></div>
        <div><dt>{t('gatewayTrace.duration')}</dt><dd>{count.format(row.durationMs)} ms</dd></div>
      </dl>
      {row.outcome === 'blocked' && <section className="tt-request-blocks"><h3>{t('gatewayTrace.whyBlocked')}</h3>
        {Object.keys(row.blocks || {}).length > 0
          ? <ul>{Object.entries(row.blocks || {}).map(([reason, total]) => <li key={reason}>
            <span>{t('gatewayTrace.reason.' + (knownReasons.includes(reason) ? reason : 'unknown'))}</span><strong>{count.format(total)}</strong>
          </li>)}</ul>
          : <p className="agent-settings-hint">{t('gatewayTrace.reason.unknown')}</p>}
      </section>}
      {!!data?.attempts.length && <section className="tt-request-path"><h3>{t('gatewayTrace.path')}</h3>
        <ol>{data.attempts.map(attempt => <li key={attempt.attempt}>
          <div><small>{t('gatewayTrace.step', { step: count.format(attempt.attempt) })}</small><strong>{attempt.model}</strong><span>{sources.get(attempt.sourceId) || t('gatewayTrace.sourceRemoved')}</span></div>
          <span className={'tt-request-outcome ' + (attempt.success ? 'is-success' : 'is-failed')}>{attempt.status ? 'HTTP ' + attempt.status : t('gatewayTrace.connectFailed')} · {t(attempt.success ? 'gatewayTrace.success' : 'gatewayTrace.failed')}</span>
        </li>)}</ol>
      </section>}
      {data && !data.complete && <p className="agent-settings-hint">{t('gatewayTrace.partial')}</p>}
      <div className="tt-request-actions">
        {pool && <Button onClick={() => onPool(pool.id)}>{t('gatewayWorkspace.viewPool')}</Button>}
        {knownSource && <Button onClick={() => onSource(row.sourceId)}>{t('gatewayWorkspace.viewSource')}</Button>}
        {row.error === 'MODEL_PROXY_DAILY_LIMIT' && <Button onClick={onLimits}>{t('gatewayTrace.viewLimits')}</Button>}
      </div>
      <details className="tt-routing-guide tt-request-technical"><summary>{t('gatewayTrace.technical')}</summary>
        {!!row.error && <p><code>{row.error}</code></p>}
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
