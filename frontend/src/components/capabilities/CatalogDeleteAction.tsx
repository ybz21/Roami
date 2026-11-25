import { useState } from 'react'
import { App } from 'antd'
import { useI18n } from '../../i18n'
import { TrashIcon } from '../../icons'
import { Popconfirm } from './model-controls'
import { planCatalogDeletion, type CatalogDeletion } from './catalog-deletion'
import type { ModelCatalog } from './model-hub-api'

export default function CatalogDeleteAction({ target, catalog, busy, save, onDeleted, card = false }: {
  target: CatalogDeletion
  catalog: ModelCatalog
  busy: boolean
  save: (value: ModelCatalog) => Promise<boolean>
  onDeleted: (removedIds: ReadonlySet<string>) => void
  card?: boolean
}) {
  const { t, locale } = useI18n()
  const { modal, message } = App.useApp()
  const [plan, setPlan] = useState<ReturnType<typeof planCatalogDeletion> | null>(null)
  const { item, kind } = target
  const name = item.name || item.id
  const label = t(kind === 'source' && !card ? 'hub.deleteSource' : 'capabilities.models.deleteAction')
  const changeOpen = (open: boolean) => {
    if (!open) { setPlan(null); return }
    if (busy) return
    const nextPlan = planCatalogDeletion(catalog, target)
    const { models, clients } = nextPlan
    if (models.length || clients.length) {
      const list = new Intl.ListFormat(locale)
      modal.info({
        title: t('modelDelete.blocked', { name }),
        className: 'tt-model-connection-confirm tt-model-delete-description',
        content: <>
          {models.length > 0 && <p>{t('modelDelete.models', { models: list.format(models) })}</p>}
          {clients.length > 0 && <p>{t('modelDelete.clients', { clients: list.format(clients) })}</p>}
        </>,
      })
      return
    }
    setPlan(nextPlan)
  }
  const count = plan?.removedIds.size || 0
  const details = kind === 'source' && (count > 0 || item.pluginDesktop) && <span className="tt-model-delete-description">
    {count > 0 && t('modelDelete.sourceImpact', { count: new Intl.NumberFormat(locale).format(count) })}
    {count > 0 && item.pluginDesktop && <br />}
    {item.pluginDesktop && t('hub.plugin.deleteDesktopHint')}
  </span>
  const remove = async () => {
    if (!plan || !await save(plan.next)) return
    onDeleted(plan.removedIds)
    message.success(t('modelDelete.success'))
  }
  return <Popconfirm open={!!plan} onOpenChange={changeOpen} title={<span className="tt-model-delete-description">{t('modelDelete.title', { name })}</span>}
    description={details} okText={t('capabilities.models.deleteAction')} onConfirm={remove}>
    <button type="button" className={'tt-act danger' + (card ? ' tt-model-card-delete' : '')}
      aria-label={card || kind === 'model' && !item.aggregate ? t('modelDelete.action', { name }) : undefined}
      disabled={busy}>
      {card && <TrashIcon size={16} />}{label}
    </button>
  </Popconfirm>
}
