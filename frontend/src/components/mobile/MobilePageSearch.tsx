import type { RefObject } from 'react'
import { CloseIcon, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'

export default function MobilePageSearch({ value, onChange, placeholder, resultCount, inputRef }: {
  value: string
  onChange: (value: string) => void
  placeholder: string
  resultCount?: string
  inputRef?: RefObject<HTMLInputElement | null>
}) {
  const { t } = useI18n()
  return (
    <div className="tt-mobile-page-search">
      <SearchIcon size={18} />
      <input ref={inputRef} value={value} onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder} aria-label={placeholder} autoComplete="off" spellCheck={false} />
      {value && resultCount && <span className="count">{resultCount}</span>}
      {value && <button type="button" aria-label={t('common.clear')} onClick={() => { onChange(''); inputRef?.current?.focus() }}>
        <CloseIcon size={16} />
      </button>}
    </div>
  )
}
