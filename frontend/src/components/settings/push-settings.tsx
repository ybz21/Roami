// 设置页的「推送通知」：一个开关 + 「发一条测试」。开关的真值问浏览器（有没有订阅），不存偏好
import { useEffect, useState } from 'react'
import { Button, Switch, App as AntApp } from 'antd'
import { useI18n } from '../../i18n'
import { api } from '../../api'
import { disablePush, enablePush, pushEnabled, pushSupported } from '../../push'

export function PushSettings() {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [on, setOn] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { void pushEnabled().then(setOn) }, [])
  const toggle = async (v: boolean) => {
    setBusy(true)
    try {
      if (v) {
        const r = await enablePush()
        if (r === 'ok') setOn(true)
        else message.warning(t(r === 'denied' ? 'set.pushDenied' : r === 'unsupported' ? 'set.pushUnsupported' : 'set.pushFailed'))
      } else { await disablePush(); setOn(false) }
    } finally { setBusy(false) }
  }
  const test = async () => {
    try { const r = await api('POST', '/push/test'); message.success(t('set.pushTestSent', { n: r.data?.devices ?? 0 })) }
    catch (e: any) { message.error(e.message) }
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-3)' }}>
      <Switch checked={on} loading={busy} disabled={!pushSupported()} onChange={toggle} />
      {on && <Button size="small" onClick={test}>{t('set.pushTest')}</Button>}
    </span>
  )
}
