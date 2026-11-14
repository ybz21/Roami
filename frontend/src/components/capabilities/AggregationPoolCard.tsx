import { useId, useState } from 'react'
import { Alert, Button, Popconfirm, Spin, Tabs } from 'antd'
import { ChevronDown, ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import RoutingStrategyPreview from './RoutingStrategyPreview'
import { useRoutingStatus } from './model-routing-api'
import type { CatalogModel, ModelSource } from './model-hub-api'

function LiveChannels({ model, sources, revision, active }: { model: CatalogModel; sources: ModelSource[]; revision: string; active: boolean }) {
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

export default function AggregationPoolCard({ model, sources, pools, revision, active, expanded, editing, busy, canEdit, inUse, onToggle, onEdit, onEnable, onDelete, onChange }: {
  model: CatalogModel; sources: ModelSource[]; pools: CatalogModel[]; revision: string; active: boolean; expanded: boolean; editing: boolean; busy: boolean; canEdit: boolean; inUse: boolean
  onToggle: () => void; onEdit: () => void; onEnable: () => void; onDelete: () => Promise<boolean>; onChange?: (patch: Partial<CatalogModel>) => void
}) {
  const { t } = useI18n(), bodyId = useId(), [tab, setTab] = useState('runtime')
  const name = model.name.trim() || t('pool.create')
  const preview = <RoutingStrategyPreview model={model} sources={sources} pools={pools} onChange={onChange} disabled={busy || !active} showTitle={editing} />
  return <section className={'tt-routing-pool' + (expanded ? ' is-expanded' : '') + (editing ? ' is-editing' : '')} aria-label={name}>
    <header className="tt-pool-card-head">
      <button type="button" className="tt-pool-select" aria-label={t('pool.detailsFor', { name })} aria-expanded={expanded} aria-controls={bodyId} disabled={editing || !canEdit} onClick={onToggle}>
        <span className="tt-pool-identity"><strong>{name}</strong>{model.id !== name && <code>{model.id}</code>}<span className="tt-pool-summary"><span>{t(model.enabled === false ? 'pool.disabled' : 'pool.enabled')}</span><span>{t('pool.strategy.' + model.strategy)}</span><span>{t('pool.memberCount', { count: model.candidates.length })}</span></span></span>
        {!editing && <span className="tt-pool-expand">{t(expanded ? 'pool.hideDetails' : 'pool.showDetails')}{expanded ? <ChevronDown /> : <ChevronRight />}</span>}
      </button>
      <div className="tt-pool-actions">{editing ? <span className="tt-pool-draft-label">{t('pool.unsaved')}</span> : <>
        <Button disabled={busy || !canEdit} onClick={onEdit}>{t('hub.configure')}</Button>
        <Button disabled={busy} onClick={onEnable}>{t(model.enabled === false ? 'pool.enable' : 'pool.disable')}</Button>
        <Popconfirm title={t('pool.delete')} onConfirm={onDelete}><button type="button" className="tt-act danger" disabled={busy || inUse}>{t('capabilities.models.deleteAction')}</button></Popconfirm>
      </>}</div>
    </header>
    <div className="tt-pool-body" id={bodyId} hidden={!expanded}>
      {expanded && (editing ? preview : <Tabs activeKey={tab} onChange={setTab} items={[
        { key: 'runtime', label: t('pool.runtime'), children: active && tab === 'runtime' && <LiveChannels model={model} sources={sources} revision={revision} active={active} /> },
        { key: 'preview', label: t('pool.preview'), children: active && tab === 'preview' && <><details className="tt-routing-guide"><summary>{t('pool.policyDetails')}</summary><p>{t('pool.strategy.' + model.strategy + '.detail')}</p>{model.strategy === 'cheap' && <p>{t('pool.timePriceHint')}</p>}</details>{preview}</> },
      ]} />)}
    </div>
  </section>
}
