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
  const resolved = observations ? observations.requests - observations.uncertain : 0

  return <section className="tt-pool-status">
    <div className="tt-request-section-head">
      <h3>{t('pool.runtimeOrder')}</h3>
      <small>{t('pool.strategy.' + model.strategy)}</small>
    </div>
    {hasDraft && <p className="agent-settings-hint">{t('pool.savedRuntime')}</p>}
    {!ranks.size && <p className="agent-settings-hint">{t('pool.noneAvailable')}</p>}
    <ol className="tt-pool-route">
      <li><span>{t('gatewayWorkspace.gatewayName')}</span><strong>{model.id}</strong></li>
      <li><span>{t('gatewayTrace.primary')}</span><strong>{ready.length ? name(members.get(ready[0])!) : t('pool.noneAvailable')}</strong></li>
      {ready.length > 1 && <li><span>{t('gatewayTrace.backup')}</span><strong>{name(members.get(ready[1])!)}</strong></li>}
    </ol>
    <dl className="tt-request-totals">
      <div><dt>{t('pool.ready')}</dt><dd>{number.format(ready.length)} / {number.format(members.size)}</dd></div>
      <div><dt>{t('gatewayTrace.coolingMembers')}</dt><dd>{number.format(cooling)}</dd></div>
      <div><dt>{t('gatewayTrace.recentFailureRate')}</dt><dd>{observations && resolved > 0 ? new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(observations.failed / resolved) : t('monitor.pending')}</dd></div>
      <div><dt>{t('gatewayTrace.recentSwitches')}</dt><dd>{observations?.requests ? number.format(observations.sameSource + observations.crossSource) : t('monitor.pending')}</dd></div>
    </dl>
    {(latest || latestSwitch) && <div className="tt-request-actions">
      {latest && <Button onClick={() => onRequest(latest.requestId)}>{t('gatewayTrace.latestHit', { model: latest.upstreamModel || latest.model })}</Button>}
      {latestSwitch && latestSwitch.requestId !== latest?.requestId && <Button onClick={() => onRequest(latestSwitch.requestId)}>{t('gatewayTrace.latestSwitch')}</Button>}
      {latestSwitch && observations && <small>{t('gatewayTrace.switchCounts', { same: number.format(observations.sameSource), cross: number.format(observations.crossSource) })}</small>}
    </div>}
    <details className="tt-routing-guide">
    <summary><ChevronRight />{t('gatewayTrace.memberStatus')}</summary>
    {order.map(key => {
      const member = members.get(key)!, rank = ranks.get(key), block = blocks.get(key), group = channels.get(key) || []
      const source = member.sourceId === '@group' ? t('pool.groups') : catalog.sources.find(row => row.id === member.sourceId)?.name
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
