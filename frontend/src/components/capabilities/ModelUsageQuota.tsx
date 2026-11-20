import { useState } from 'react'
import { Button, Input } from 'antd'
import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import type { GatewaySettingsController } from '../settings/gateway-settings'
import { remainingGatewayCharge } from '../settings/local-model-gateway'
import { ModelCharges, chargeText } from '../settings/model-charges'
import type { UsageTotals } from '../settings/model-usage-statistics'

export default function ModelUsageQuota({ controller, today, totals, timezone }: {
  controller: GatewaySettingsController; today?: UsageTotals; totals: UsageTotals; timezone?: string
}) {
  const { t, locale } = useI18n()
  const [editing, setEditing] = useState(false)
  const { saved, draft } = controller
  const limit = saved?.dailyLimit ?? null
  const pending = t('modelUsage.pendingBalance')
  const limitText = !saved ? pending : limit === null
    ? t('agent.proxy.unlimited') : chargeText([{ currency: saved.currency, amount: String(limit) }], locale)
  const remaining = limit === null ? limitText : !saved || !today || today.pending > 0 || today.unknown > 0
    ? pending : chargeText([remainingGatewayCharge(limit, saved.currency, today.charges)], locale)
  const cacheRate = totals.inputTokens ? new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(totals.cacheReadTokens / totals.inputTokens) : t('agent.usage.noRate')
  return <section className="model-usage-quota">
    <div className="model-usage-heading">
      <div className="model-usage-quota-summary">
        <span>{t('agent.proxy.todayCost')} {today ? <ModelCharges charges={today.charges} estimatedCharges={today.estimatedCharges} /> : pending}</span>
        <span>{t('agent.proxy.dailyLimit')} <strong>{limitText}</strong></span>
      </div>
      <Button disabled={!draft} aria-expanded={editing} onClick={() => setEditing(value => !value)}>{t('modelUsage.editLimit')}</Button>
    </div>
    <details className="model-usage-quota-details">
      <summary><ChevronRight />{t('modelInteraction.allowanceDetails')}</summary>
      <p className="agent-settings-hint">{t('modelUsage.limitScope')} {timezone && t('modelUsage.accountingTimezone', { timezone })}</p>
      <p>{t('modelUsage.remaining')} {remaining}</p>
      <p>{t('agent.usage.cacheRate')} {cacheRate}</p>
    </details>
    {editing && draft && <form className="agent-settings-form model-usage-limit-form" onSubmit={event => { event.preventDefault(); void controller.save('limits') }}>
      {controller.notice}
      <label className="agent-settings-field"><span>{t('agent.proxy.dailyLimit')}</span><Input aria-label={t('agent.proxy.dailyLimit')} type="number" min={0} max={1000000} step="any" placeholder={t('agent.proxy.unlimited')} value={draft.dailyLimit} onChange={event => controller.setDraft(previous => previous && ({ ...previous, dailyLimit: event.target.value }))} /></label>
      <label className="agent-settings-field"><span>{t('agent.proxy.currency')}</span><Input aria-label={t('agent.proxy.currency')} value={draft.currency} onChange={event => controller.setDraft(previous => previous && ({ ...previous, currency: event.target.value }))} /></label>
      <label className="agent-settings-field"><span>{t('agent.gateway.timezone')}</span><Input aria-label={t('agent.gateway.timezone')} value={draft.timezone} onChange={event => controller.setDraft(previous => previous && ({ ...previous, timezone: event.target.value }))} /></label>
      <div className="agent-settings-save"><Button onClick={() => controller.discard('limits')} disabled={controller.saving}>{t('agent.models.discard')}</Button><Button htmlType="submit" type="primary" loading={controller.saving} disabled={!controller.limitsDirty || !controller.validLimits}>{t('agent.models.save')}</Button></div>
    </form>}
  </section>
}
