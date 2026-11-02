import { useI18n } from '../../i18n'
import { ClockIcon, UsageRing } from '../../icons'
import { useLayout } from '../../layout'
import { CTX_FULL, CTX_TIGHT, fmtElapsed } from './status'
import './usage-indicator.css'

export type UsageIndicatorProps = {
  quota?: number
  elapsed?: number
  accent?: string
  onElapsedClick?: () => void
  elapsedExpanded?: boolean
}

export function UsageIndicator({ quota, elapsed, accent = 'var(--accent)', onElapsedClick, elapsedExpanded }: UsageIndicatorProps) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const color = quota != null && quota >= CTX_FULL ? 'var(--danger)'
    : quota != null && quota >= CTX_TIGHT ? 'var(--warn)' : accent
  if (quota == null && elapsed == null) return null

  const duration = elapsed != null && <><ClockIcon size={12} /><span>{fmtElapsed(elapsed)}</span></>
  return (
    <div className="cc-usage">
      {quota != null && (
        <span className="cc-usage-item" title={t('chat.quotaTitle')}>
          <UsageRing percent={quota} color={color} />
          <span>{t(phone ? 'chat.quotaShort' : 'chat.quotaTitle')}</span>
          <span style={{ color }}>{new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(quota / 100)}</span>
        </span>
      )}
      {elapsed != null && (onElapsedClick ? (
        <button type="button" className="cc-usage-item" title={t('chat.elapsedTitle')}
          aria-label={t('chat.elapsedTitle')} aria-expanded={elapsedExpanded} onClick={onElapsedClick}>
          {duration}
        </button>
      ) : <span className="cc-usage-item" title={t('chat.elapsedTitle')}>{duration}</span>)}
    </div>
  )
}
