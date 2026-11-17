import { useMemo, useEffect, useRef, useState } from 'react'
import { useCurrentNodeId } from '../cluster/node-url'
import { useWorkspaceStateStore } from '../../view-state'
import { useI18n } from '../../i18n'

// Keep secrets in memory; page and dialog navigation can recover edits without writing keys to storage.
export function useSettingsDraft<T>(id: string, value: T, baseline: T, restore: (draft: T) => void, ready = true) {
  const node = useCurrentNodeId(), { t } = useI18n()
  const store = useWorkspaceStateStore()
  const drafts = useMemo(() => store.node(node).child('drafts'), [store, node])
  const key = id
  const identity = JSON.stringify([...drafts.path, key])
  const initialized = useRef('')
  const [restored, setRestored] = useState(false)
  const dirty = ready && JSON.stringify(value) !== JSON.stringify(baseline)
  useEffect(() => {
    if (!ready) return
    if (initialized.current !== identity) {
      initialized.current = identity
      if (drafts.has(key)) { restore(drafts.get(key) as T); setRestored(true); return }
    }
    if (dirty) drafts.set(key, value, 'draft')
    else drafts.delete(key)
  }, [identity, drafts, key, ready, value, baseline, dirty])
  return dirty ? <p role="status">{t(restored ? 'settings.draftRestored' : 'settings.draftKept')}</p> : null
}
