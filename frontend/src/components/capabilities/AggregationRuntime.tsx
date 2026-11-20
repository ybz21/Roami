import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCatalog } from './model-hub-api'
import type { RoutingStatus, useRoutingStatus } from './model-routing-api'
import { Alert, Button, Spin } from './model-controls'
import { candidateIdentity } from './routing-preview'

export default function AggregationRuntime({ model, catalog, status, hasDraft, onRequest }: {
  model: CatalogModel; catalog: ModelCatalog; status: ReturnType<typeof useRoutingStatus>; hasDraft: boolean; onRequest: (id: string) => void
}) {
  const { t, locale } = useI18n()
  if (model.enabled === false) return <p className="agent-settings-hint">{t('pool.disabled')}</p>
  if (status.failed) return <Alert type="error" role="alert" message={t('pool.statusFailed')} action={<Button onClick={status.retry}>{t('agent.retry')}</Button>} />
  const snapshot = status.data
  if (!snapshot) return <div className="tt-pool-status"><Spin size="small" /></div>

  const members = new Map(model.candidates.map(member => [candidateIdentity(member), member]))
  const blocks = new Map(snapshot.members?.map(member => [candidateIdentity(member), member.block]))
  const ranks = new Map<string, number>()
  const channels = new Map<string, RoutingStatus['channels']>()
  for (const channel of snapshot.channels) {
    const key = candidateIdentity(channel)
    if (!members.has(key)) continue
    const group = channels.get(key) || []
    group.push(channel)
    channels.set(key, group)
    if (channel.ready && !ranks.has(key)) ranks.set(key, ranks.size + 1)
  }
  const order = [...ranks.keys(), ...[...members.keys()].filter(key => !ranks.has(key))]
  const name = (member: CatalogModel['candidates'][number]) => member.sourceId === '@group'
    ? catalog.models.find(pool => pool.id === member.model)?.name || member.model
    : member.model
  const number = new Intl.NumberFormat(locale)
  const date = new Intl.DateTimeFormat(locale, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

  const ready = order.filter(key => ranks.has(key))
  const observations = snapshot.observation
  const latest = observations?.latest
  const latestSwitch = observations?.latestSwitch
  const cooling = [...channels.values()].filter(group => group.some(channel => (channel.restUntil || 0) > snapshot.now)).length
  const sourceName = (sourceId: string) => sourceId === '@group' ? t('pool.groups') : catalog.sources.find(row => row.id === sourceId)?.name
  const resolved = observations ? observations.requests - observations.uncertain : 0

  return <section className="tt-pool-status">
    <div className="tt-request-section-head">
      <h3>{t('pool.runtimeOrder')}</h3>
      <div className="tt-pool-runtime-meta"><small>{t('pool.strategy.' + model.strategy)}</small>
        <span className={ready.length ? 'is-ready' : 'is-blocked'}>{t('pool.runtimeAvailable', { count: number.format(ready.length), total: number.format(members.size) })}</span>
      </div>
    </div>
    {hasDraft && <p className="agent-settings-hint">{t('pool.savedRuntime')}</p>}
    <div className="tt-pool-runtime-body">
    {!ready.length ? <p className="tt-pool-unavailable">{t('pool.noneAvailable')}</p> :
      <ol className="tt-pool-route">
        {ready.slice(0, 2).map((key, index) => {
          const member = members.get(key)!
          return <li key={key}>
            <span className="tt-pool-route-rank" aria-hidden="true">{number.format(index + 1)}</span>
            <div><small>{t(index ? 'gatewayTrace.backup' : 'gatewayTrace.primary')}</small><strong>{name(member)}</strong>
              {sourceName(member.sourceId) && <span>{sourceName(member.sourceId)}</span>}
            </div>
          </li>
        })}
        {ready.length === 1 && members.size > 1 && <li className="tt-pool-route-unavailable">
          <span className="tt-pool-route-rank" aria-hidden="true">2</span>
          <div><strong>{t('gatewayTrace.noBackup')}</strong></div>
        </li>}
      </ol>}
    <dl className="tt-request-totals">
      <div><dt>{t('gatewayTrace.coolingMembers')}</dt><dd>{number.format(cooling)}</dd></div>
      <div><dt>{t('gatewayTrace.recentFailureRate')}</dt><dd>{observations && resolved > 0 ? new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(observations.failed / resolved) : t('monitor.pending')}</dd></div>
      <div><dt>{t('gatewayTrace.recentSwitches')}</dt><dd>{observations?.requests ? number.format(observations.sameSource + observations.crossSource) : t('monitor.pending')}</dd></div>
    </dl>
    </div>
    {(latest || latestSwitch) && <div className="tt-request-actions">
      {latest && <Button onClick={() => onRequest(latest.requestId)}>{t('gatewayTrace.latestHit', { model: latest.upstreamModel || latest.model })}</Button>}
      {latestSwitch && latestSwitch.requestId !== latest?.requestId && <Button onClick={() => onRequest(latestSwitch.requestId)}>{t('gatewayTrace.latestSwitch')}</Button>}
      {latestSwitch && observations && <small>{t('gatewayTrace.switchCounts', { same: number.format(observations.sameSource), cross: number.format(observations.crossSource) })}</small>}
    </div>}
    <details className="tt-routing-guide" open={!ready.length || undefined}>
    <summary><ChevronRight />{t('gatewayTrace.memberStatus')}</summary>
    {order.map(key => {
      const member = members.get(key)!, rank = ranks.get(key), block = blocks.get(key), group = channels.get(key) || []
      const source = sourceName(member.sourceId)
      return <div className="tt-routing-channel" key={key}>
        <span>{rank ? t('pool.runtimeRank', { rank: number.format(rank) }) : t('pool.runtimeSkipped')}</span>
        <div><strong>{name(member)}</strong>{source && <small>{source}</small>}</div>
        {!rank && <small>{t(block ? 'orchestration.routingBlock.' + block : group.length ? 'pool.resting' : 'pool.unchecked')}</small>}
        {group.length > 0 && <ul>{group.map((channel, index) => {
          const at = channel.restUntil || channel.resetAt || channel.expiresAt
          return <li key={channel.account}>
            {group.length > 1 && <small>{t('pool.channel', { index: number.format(index + 1) })}</small>}
            <small>{t(channel.ready ? 'pool.ready' : 'pool.resting')}</small>
            <small>{channel.remaining == null ? t('pool.unknown') : t('pool.remaining', { count: number.format(channel.remaining) })}</small>
            {!!at && <small>{t(channel.restUntil ? 'pool.until' : channel.resetAt ? 'pool.resetAt' : 'pool.expireAt')} {date.format(at)}</small>}
          </li>
        })}</ul>}
      </div>
    })}
    </details>
  </section>
}
