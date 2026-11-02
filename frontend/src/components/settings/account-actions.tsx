import { useEffect, useState } from 'react'
import { App, Button } from 'antd'
import { useI18n } from '../../i18n'
import { ExitFullscreenIcon, FullscreenIcon, LogoutIcon } from '../../icons'

export function fullscreenSupported() {
  return typeof document !== 'undefined' && !!(document.documentElement.requestFullscreen || (document.documentElement as any).webkitRequestFullscreen)
}

export function FullscreenAction({ controller }: { controller?: { active: boolean; toggle: () => void } }) {
  const { t } = useI18n()
  const [active, setActive] = useState(false)
  useEffect(() => {
    const onChange = () => setActive(!!(document.fullscreenElement || (document as any).webkitFullscreenElement))
    onChange()
    document.addEventListener('fullscreenchange', onChange)
    document.addEventListener('webkitfullscreenchange', onChange)
    return () => {
      document.removeEventListener('fullscreenchange', onChange)
      document.removeEventListener('webkitfullscreenchange', onChange)
    }
  }, [])
  if (!controller && !fullscreenSupported()) return null
  const current = controller?.active ?? active
  const toggle = () => {
    if (controller) { controller.toggle(); return }
    const doc: any = document, root: any = document.documentElement
    if (doc.fullscreenElement || doc.webkitFullscreenElement) (doc.exitFullscreen || doc.webkitExitFullscreen)?.call(doc)
    else (root.requestFullscreen || root.webkitRequestFullscreen)?.call(root)
  }
  return <Button icon={current ? <ExitFullscreenIcon size={14} /> : <FullscreenIcon size={14} />} onClick={toggle}>
    {t(current ? 'common.exitFullscreen' : 'common.fullscreen')}
  </Button>
}

export function LogoutAction({ onLogout }: { onLogout: () => void }) {
  const { t } = useI18n(), { modal } = App.useApp()
  return <Button danger icon={<LogoutIcon size={14} />} onClick={() => modal.confirm({
    title: t('common.logoutConfirm'), okText: t('common.logout'), cancelText: t('common.cancel'),
    okButtonProps: { danger: true }, onOk: onLogout,
  })}>{t('common.logout')}</Button>
}
