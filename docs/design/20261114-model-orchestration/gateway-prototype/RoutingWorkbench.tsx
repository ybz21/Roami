import { useRef, useState } from 'react'
import { useI18n } from '../../../../frontend/src/i18n'
import { useLayout } from '../../../../frontend/src/layout'
import { ChevronRight } from '../../../../frontend/src/icons'
import { candidateIdentity } from '../../../../frontend/src/components/capabilities/routing-preview'
import type { RequestOutcome } from '../../../../frontend/src/components/capabilities/gateway-request-api'
import { readWorkbench } from './fixture'

const failed = ['blocked', 'exhausted', 'interrupted', 'failed']
const outcomeGroups = ['success', 'recovered', 'failed'] as const
type Group = typeof outcomeGroups[number]
const outcomeGroup = (outcome: RequestOutcome) => failed.includes(outcome) ? 'failed' : outcome
const pages = [
  ['catalog', '#/catalog'], ['aggregate', '#/aggregate'], ['usage', '#/usage'],
  ['monitor', '#/monitor/requests'], ['audit', '#/audit'], ['gateway', '#directory'], ['speech', '#/speech'],
]

export function RoutingWorkbench() {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const zh = locale === 'zh-CN'
  const [poolId, setPoolId] = useState('free')
  const [hours, setHours] = useState(1)
  const [group, setGroup] = useState<Group | ''>('')
  const [chosen, setChosen] = useState('')
  const pathHeading = useRef<HTMLHeadingElement>(null)
  const { pools, pool, poolRoute, requests, sources, traces } = readWorkbench(poolId, hours)
  const sourceName = (id: string) => sources.find(source => source.id === id)?.name || t('gatewayTrace.sourceRemoved')
  const sourceLink = (id: string) => '#/catalog/source/' + encodeURIComponent(id) + '?from=workbench'
  const editPoolLink = pool && '#/aggregate/' + encodeURIComponent(pool.id) + '?from=workbench'
  const formatted = new Intl.NumberFormat(locale)
  const clock = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const visible = traces.filter(({ request }) => !group || group === outcomeGroup(request.outcome))
  const trace = visible.find(({ request }) => request.requestId === chosen) || visible[0]
  const counts = {
    success: requests?.outcomes.success || 0,
    recovered: requests?.outcomes.recovered || 0,
    failed: requests?.totals.failed || 0,
  }
  const total = requests?.totals.requests || 0
  const waiting = poolRoute?.channels.filter(row => !row.ready) || []
  const ready = poolRoute?.channels.filter(row => row.ready) || []
  const result = trace?.request
  const failedAttempt = trace?.attempts.find(attempt => !attempt.success)
  const affectedSource = sources.find(source => source.id === failedAttempt?.sourceId)
  const attemptTitle = (status: number, success: boolean) => t('gatewayTrace.' + (success ? 'success'
    : status === 429 ? 'upstreamLimited' : status === 402 ? 'reason.quota'
      : result?.outcome === 'interrupted' ? 'interrupted' : 'failed'))
  const selectTrace = (id: string) => {
    setChosen(id)
    if (phone) requestAnimationFrame(() => {
      pathHeading.current?.scrollIntoView({ block: 'start' })
      pathHeading.current?.focus({ preventScroll: true })
    })
  }
  const updateGroup = (value: Group) => {
    setChosen('')
    setGroup(group === value ? '' : value)
  }

  return <div className="routing-workbench">
    <header className="tt-pagehead routing-workbench-head">
      <h1>{zh ? '调度与排查' : 'Routing & incidents'}</h1>
      {pools.length > 0 && <label className="routing-workbench-field">{t('hub.tab.aggregate')}
        <select value={pool?.id} onChange={event => { setPoolId(event.target.value); setChosen(''); setGroup('') }}>
          {pools.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select>
      </label>}
    </header>
    {!pool ? <p className="routing-workbench-empty"><a href="#/aggregate">{t('pool.create')}</a></p> : <div className="routing-workbench-grid">
      <section className="routing-workbench-order" aria-labelledby="workbench-order">
        <div className="routing-workbench-section-head"><h2 id="workbench-order">{zh ? '现在会怎么调度' : 'How the next call is routed'}</h2>
          <a href={editPoolLink}>{zh ? '编辑调度' : 'Edit routing'}<ChevronRight /></a></div>
        <p className="routing-workbench-meta"><span>{pool.enabled === false ? t('pool.disabled') : t('pool.strategy.' + pool.strategy)}</span>
          <span>{t('pool.runtimeAvailable', { count: formatted.format(ready.length), total: formatted.format(pool.candidates.length) })}</span></p>
        {ready.length > 0 ? <ol className="routing-workbench-order-list">
          {ready.map((member, index) => <li key={candidateIdentity(member)}>
            <a href={sourceLink(member.sourceId)}>
              <span className="routing-workbench-index" aria-hidden="true">{index + 1}</span>
              <div><small>{t(index ? 'gatewayTrace.backup' : 'gatewayTrace.primary')}</small><strong translate="no">{member.model}</strong>
                <span translate="no">{sourceName(member.sourceId)}</span></div><ChevronRight />
            </a>
          </li>)}
        </ol> : <p className="routing-workbench-empty">{t('pool.noneAvailable')}</p>}
        {!!waiting.length && pool.enabled !== false && <details className="routing-workbench-skips">
          <summary><ChevronRight />{zh ? '暂不可用' : 'Temporarily unavailable'} <strong>{waiting.length}</strong></summary>
          <ul>{waiting.map(member => <li key={candidateIdentity(member)}><div><strong translate="no">{member.model}</strong><small>{sourceName(member.sourceId)}</small></div>
            <span>{member.restUntil ? (zh ? '冷却至 ' : 'Cooling down until ') + clock.format(member.restUntil) : t('pool.unchecked')}</span></li>)}</ul>
        </details>}
        <a className="routing-workbench-more" href="#/monitor/sources">{zh ? '对比来源表现' : 'Compare model sources'}<ChevronRight /></a>
      </section>

      <section className="routing-workbench-requests" aria-labelledby="workbench-requests">
        <div className="routing-workbench-section-head"><h2 id="workbench-requests">{zh ? '请求结果' : 'Request outcomes'}</h2>
          <label className="routing-workbench-field"><span className="sr-only">{t('monitor.range')}</span>
            <select value={hours} onChange={event => { setHours(Number(event.target.value)); setChosen(''); setGroup('') }}>
              {[1, 6, 24].map(value => <option value={value} key={value}>{t('monitor.hours', { hours: value })}</option>)}
            </select>
          </label>
        </div>
        {total > 0 ? <>
          <div className="routing-workbench-distribution" role="img" aria-label={outcomeGroups.map(key => t('gatewayTrace.' + key) + ' ' + counts[key]).join(' · ')}>
            {outcomeGroups.map(key => counts[key] > 0 && <span className={'is-' + key} key={key} style={{ flexGrow: counts[key] }} />)}
          </div>
          <div className="routing-workbench-filters">
            <button type="button" onClick={() => { setGroup(''); setChosen('') }} aria-pressed={!group}>{zh ? '全部' : 'All'} <strong>{formatted.format(total)}</strong></button>
            {outcomeGroups.map(key => <button type="button" key={key} aria-pressed={group === key} disabled={!counts[key]} onClick={() => updateGroup(key)}>
              <span className={'routing-workbench-swatch is-' + key} aria-hidden="true" />{t('gatewayTrace.' + key)} <strong>{formatted.format(counts[key])}</strong>
            </button>)}
          </div>
          <div className="routing-workbench-inspection">
            <div className="routing-workbench-recent">
              <h3>{t('gatewayTrace.recent')}</h3>
              <ul>{visible.slice(0, 6).map(({ request }) => <li key={request.requestId}>
                <button type="button" aria-pressed={result?.requestId === request.requestId} onClick={() => selectTrace(request.requestId)}>
                  <time dateTime={new Date(request.at).toISOString()}>{clock.format(request.at)}</time>
                  <span>{t('gatewayTrace.' + request.outcome)}</span><ChevronRight />
                </button>
              </li>)}</ul>
              <a className="routing-workbench-more" href="#/monitor/requests">{zh ? '打开请求监控' : 'Open request monitoring'}<ChevronRight /></a>
            </div>
            {trace && result && <section className="routing-workbench-path" aria-labelledby="workbench-path">
              <h3 id="workbench-path" tabIndex={-1} ref={pathHeading}>{zh ? '这次实际怎么走' : 'What happened in this call'}</h3>
              <div className="routing-workbench-result">
                <strong className={'tt-request-outcome is-' + result.outcome}>{t('gatewayTrace.' + result.outcome)}</strong>
                <small>HTTP {result.status}</small>
              </div>
              {trace.attempts.length ? <ol className="routing-workbench-trace">
                {trace.attempts.map(attempt => <li key={attempt.attempt}><span className="routing-workbench-index">{attempt.attempt}</span>
                  <div><strong translate="no">{attempt.model}</strong><small>{sourceName(attempt.sourceId)}</small></div>
                  <span className={'tt-request-outcome ' + (attempt.success ? 'is-success' : 'is-failed')}>
                    {attemptTitle(attempt.status, attempt.success)}<small>HTTP {attempt.status}</small>
                  </span>
                </li>)}
              </ol> : <><p>{t('gatewayTrace.blockedBeforeSend')}</p><ul className="routing-workbench-blocks">
                {Object.entries(result.blocks || {}).map(([reason, count]) => <li key={reason}>
                  <span>{t('gatewayTrace.reason.' + reason)}</span><strong>{formatted.format(count)}</strong>
                </li>)}
              </ul></>}
              <div className="routing-workbench-actions">
                <a className="routing-workbench-more" href={'#/audit/request/' + encodeURIComponent(result.requestId) + '/workbench'}>
                  {zh ? '查看完整审计' : 'Open full audit'}<ChevronRight />
                </a>
                {affectedSource && <a className="routing-workbench-more" href={sourceLink(affectedSource.id)}>
                  {failedAttempt?.status === 429 ? (zh ? '查看限流来源' : 'Open rate-limited source') : (zh ? '查看异常来源' : 'Open affected source')}<ChevronRight />
                </a>}
                {result.outcome === 'blocked' && <a className="routing-workbench-more" href={editPoolLink}>
                  {zh ? '检查聚合配置' : 'Check pool configuration'}<ChevronRight />
                </a>}
              </div>
            </section>}
          </div>
        </> : <p className="routing-workbench-empty">{t('gatewayTrace.empty')}</p>}
      </section>
    </div>}
    <nav className="routing-workbench-nav" aria-label={zh ? '模型管理页面' : 'Model management pages'}>
      {pages.map(([key, link]) => <a key={key} href={link}>{t('hub.tab.' + key)}<ChevronRight /></a>)}
    </nav>
  </div>
}
