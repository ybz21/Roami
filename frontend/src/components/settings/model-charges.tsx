import { useI18n } from '../../i18n'

export type ModelCharge = { currency: string; amount: string }
export const chargeText = (charges: ModelCharge[], locale: string) => charges.map(charge => {
  const [whole, fractional = ''] = charge.amount.split('.')
  const fraction = fractional.replace(/0+$/, '').padEnd(2, '0')
  const parts = new Intl.NumberFormat(locale, { style: 'currency', currency: charge.currency, currencyDisplay: 'code', minimumFractionDigits: 2 }).formatToParts(BigInt(whole))
  return parts.map(part => part.type === 'fraction' ? fraction : part.value).join('')
}).join(' · ')

export function ModelCharges({ charges, localCharges = [], estimatedCharges, incomplete = false }: { charges: ModelCharge[]; localCharges?: ModelCharge[]; estimatedCharges: ModelCharge[]; incomplete?: boolean }) {
  const { t, locale } = useI18n()
  const onlyLocal = charges.length > 0 && charges.length === localCharges.length && charges.every(charge => localCharges.some(local => local.currency === charge.currency && local.amount === charge.amount))
  const total = chargeText(charges, locale)
  return <span className="agent-model-charges">
    <span>{charges.length ? (onlyLocal ? t('agent.proxy.localEstimateAmount', { amount: total }) : incomplete ? t('agent.usage.partialCost', { amount: total }) : total) : t('agent.proxy.costUnknown')}</span>
    {!onlyLocal && localCharges.length > 0 && <small>{t('agent.proxy.includesLocalEstimate', { amount: chargeText(localCharges, locale) })}</small>}
    {estimatedCharges.length > 0 && <small>{t('agent.proxy.historicalEstimate', { amount: chargeText(estimatedCharges, locale) })}</small>}
  </span>
}
