import { useEffect, useRef, useState } from 'react'
import { Button, Spin } from 'antd'
import { useI18n } from '../../i18n'

// Unknown configuration must never become an editable set of defaults.
export function useSettingsRead(read: () => Promise<unknown>) {
  const { t } = useI18n()
  const latest = useRef(read)
  latest.current = read
  const [version, setVersion] = useState(0)
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    setState('loading')
    void latest.current().then(() => { if (alive) setState('ready') }).catch(e => {
      if (alive) { setError(e instanceof Error ? e.message : String(e)); setState('failed') }
    })
    return () => { alive = false }
  }, [version])
  return state === 'loading' ? <Spin /> : state === 'failed' ? <div role="alert">
    <p>{t('settings.readFailed')}</p><p>{error}</p>
    <Button onClick={() => setVersion(v => v + 1)}>{t('agent.retry')}</Button>
  </div> : null
}
