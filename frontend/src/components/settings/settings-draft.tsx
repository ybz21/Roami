import { useEffect, useRef, useState } from 'react'
import { useCurrentNodeId } from '../cluster/node-url'
import { useI18n } from '../../i18n'

// Keep secrets in memory; page and dialog navigation can recover edits without writing keys to storage.
const drafts = new Map<string, unknown>()
export function useSettingsDraft<T>(id: string, value: T, baseline: T, restore: (draft: T) => void, ready = true) {
  const node = useCurrentNodeId(), { t } = useI18n()
  const key = `${node || 'local'}:${id}`
  const initialized = useRef('')
  const [restored, setRestored] = useState(false)
  const dirty = ready && JSON.stringify(value) !== JSON.stringify(baseline)
  useEffect(() => {
    if (!ready) return
    if (initialized.current !== key) {
      initialized.current = key
      if (drafts.has(key)) { restore(drafts.get(key) as T); setRestored(true); return }
    }
    if (dirty) drafts.set(key, value)
    else drafts.delete(key)
  }, [key, ready, value, baseline, dirty])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  return dirty ? <p role="status">{t(restored ? 'settings.draftRestored' : 'settings.draftKept')}</p> : null
}
