import type { AnchorHTMLAttributes, ButtonHTMLAttributes } from 'react'
import { useI18n } from '../i18n'
import { ChevronLeft } from '../icons'

type BackLabel = { label?: string }

export default function BackButton({ label, className, ...props }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'type'> & BackLabel) {
  const { t } = useI18n()
  return <button {...props} type="button" className={'tt-back' + (className ? ' ' + className : '')} aria-label={label || props['aria-label'] || t('common.back')}><ChevronLeft size={20} /></button>
}

export function BackLink({ label, className, ...props }: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'children'> & BackLabel & { href: string }) {
  const { t } = useI18n()
  return <a {...props} className={'tt-back' + (className ? ' ' + className : '')} aria-label={label || props['aria-label'] || t('common.back')}><ChevronLeft size={20} /></a>
}
