import { ChevronRight, MergeIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel } from './model-hub-api'

export default function AggregationPoolCard({ model, unsaved, disabled, onOpen }: {
  model: CatalogModel; unsaved: boolean; disabled: boolean; onOpen: () => void
}) {
  const { t, locale } = useI18n()
  const name = model.name.trim() || model.id
  const preview = new Intl.ListFormat(locale, { style: 'short', type: 'conjunction' }).format(model.candidates.slice(0, 3).map(row => row.model))
  return <section className="tt-model-connection tt-aggregate-card" aria-label={name}>
    <button type="button" className="tt-model-connection-open" aria-label={t('pool.open', { name })} disabled={disabled} onClick={onOpen} />
    <div className="tt-model-connection-head"><span className="tt-model-connection-icon"><MergeIcon size={24} /></span><div><strong>{name}</strong>{model.id !== name && <small>{model.id}</small>}</div><ChevronRight /></div>
    <dl className="tt-model-connection-settings"><div><dt>{t('pool.strategy')}</dt><dd>{t('pool.strategy.' + model.strategy)}</dd></div><div><dt>{t('pool.status')}</dt><dd>{t(model.enabled === false ? 'pool.disabled' : 'pool.enabled')}</dd></div></dl>
    <div className="tt-model-connection-preview"><span>{t('pool.memberCount', { count: new Intl.NumberFormat(locale).format(model.candidates.length) })}</span>{!!model.candidates.length && <p>{preview}</p>}</div>
    {unsaved && <small className="tt-pool-draft-label">{t('pool.unsaved')}</small>}
  </section>
}
