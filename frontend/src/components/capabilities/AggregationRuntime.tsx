import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCatalog } from './model-hub-api'
import type { RoutingStatus, useRoutingStatus } from './model-routing-api'
import { Alert, Button, Spin } from './model-controls'
import { candidateIdentity } from './routing-preview'

export default function AggregationRuntime({ model, catalog, status, hasDraft }: {
  model: CatalogModel; catalog: ModelCatalog; status: ReturnType<typeof useRoutingStatus>; hasDraft: boolean
}) {
  const { t, locale } = useI18n()
  if (model.enabled === false) return <p className="agent-settings-hint">{t('pool.disabled')}</p>
  if (status.failed) return <Alert type="error" role="alert" message={t('pool.statusFailed')} action={<Button onClick={status.retry}>{t('agent.retry')}</Button>} />
  if (!status.data) return <div className="tt-pool-status"><Spin size="small" /></div>

  const members = new Map(model.candidates.map(member => [candidateIdentity(member), member]))
  const blocks = new Map(status.data.members?.map(member => [candidateIdentity(member), member.block]))
  const ranks = new Map<string, number>()
  const channels = new Map<string, RoutingStatus['channels']>()
  for (const channel of status.data.channels) {
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

  return <details className="tt-routing-guide tt-pool-status">
    <summary><ChevronRight />{t('pool.runtimeOrder')}<small>{t('pool.runtimeAvailable', { count: number.format(ranks.size), total: number.format(members.size) })}</small>
      {ranks.size > 0 && <small>{t('pool.runtimeFirst', { model: name(members.get(order[0])!) })}</small>}
    </summary>
    {hasDraft && <p className="agent-settings-hint">{t('pool.savedRuntime')}</p>}
    {!ranks.size && <p className="agent-settings-hint">{t('pool.noneAvailable')}</p>}
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
}
