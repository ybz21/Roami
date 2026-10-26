import { useI18n } from '../../i18n'

export type ModelCharge = { currency: string; amount: string }
export const chargeText = (charges: ModelCharge[], locale: string) => charges.map(charge => {
  const [whole, fractional = ''] = charge.amount.split('.')
  const fraction = fractional.replace(/0+$/, '').padEnd(2, '0')
  const parts = new Intl.NumberFormat(locale, { style: 'currency', currency: charge.currency, currencyDisplay: 'code', minimumFractionDigits: 2 }).formatToParts(BigInt(whole))
  return parts.map(part => part.type === 'fraction' ? fraction : part.value).join('')
}).join(' · ')

export function ModelCharges({ charges, estimatedCharges, incomplete = false }: { charges: ModelCharge[]; estimatedCharges: ModelCharge[]; incomplete?: boolean }) {
  const { t, locale } = useI18n()
  return <span className="agent-model-charges">
    <span>{charges.length ? (incomplete ? t('agent.usage.partialCost', { amount: chargeText(charges, locale) }) : chargeText(charges, locale)) : t('agent.proxy.costUnknown')}</span>
    {estimatedCharges.length > 0 && <small>{t('agent.proxy.historicalEstimate', { amount: chargeText(estimatedCharges, locale) })}</small>}
  </span>
}
