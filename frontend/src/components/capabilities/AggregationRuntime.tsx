import { Alert, Button, Spin } from 'antd'
import { useI18n } from '../../i18n'
import { useRoutingStatus } from './model-routing-api'
import type { CatalogModel, ModelSource } from './model-hub-api'

export default function AggregationRuntime({ model, sources, revision, active }: { model: CatalogModel; sources: ModelSource[]; revision: string; active: boolean }) {
  const { t, locale } = useI18n(), status = useRoutingStatus(model.id, active && model.enabled !== false, revision)
  const date = (value: number) => new Intl.DateTimeFormat(locale, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(value)
  if (model.enabled === false) return <p className="agent-settings-hint">{t('pool.disabled')}</p>
  return <section className="tt-pool-status" aria-label={t('pool.runtime')}>
    {status.failed && <Alert type="error" role="alert" message={t('pool.statusFailed')} action={<Button onClick={status.retry}>{t('agent.retry')}</Button>} />}
    {!status.data ? !status.failed && <Spin /> : !status.data.channels.length ? <p className="agent-settings-hint">{t('pool.noneAvailable')}</p> : <>
      <p className="agent-settings-hint">{t('pool.availableCount', { count: status.data.available })}</p>
      <div className="tt-routing-channel-list">{status.data.channels.map((channel, index) => {
        const at = channel.restUntil || channel.resetAt || channel.expiresAt
        return <div className="tt-routing-channel" key={channel.sourceId + '/' + channel.model + '/' + channel.account}>
          <div><strong>{channel.model}</strong><small>{sources.find(source => source.id === channel.sourceId)?.name || t('pool.groups')} · {t('pool.channel', { index: index + 1 })}</small></div>
          <span>{t(channel.ready ? 'pool.ready' : 'pool.resting')}</span>
          <small>{channel.remaining === null ? t('pool.unknown') : t('pool.remaining', { count: new Intl.NumberFormat(locale).format(channel.remaining) })}</small>
          {!!at && <small>{t(channel.restUntil ? 'pool.until' : channel.resetAt ? 'pool.resetAt' : 'pool.expireAt')} {date(at)}</small>}
        </div>
      })}</div>
    </>}
  </section>
}

