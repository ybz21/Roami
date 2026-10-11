import { useEffect, useState } from 'react'
import { api } from '../../api'
import { nodeApi } from '../cluster/node-url'
import { useI18n } from '../../i18n'
import { AppLaunchIcon, ChevronRight } from '../../icons'
import { appShellVersion } from './app-update'

type Info = { apk?: boolean; apkVersion?: string }

export default function AppDownloadEntry({ onGuide }: { onGuide: () => void }) {
  const { t } = useI18n()
  const eligible = /Android/i.test(navigator.userAgent) && !appShellVersion()
  const [info, setInfo] = useState<Info | null>(null)
  useEffect(() => {
    if (!eligible) return
    api('GET', '/install-info').then((r) => setInfo(r.data || {})).catch(() => setInfo({}))
  }, [eligible])
  if (!eligible || (info && !info.apk)) return null
  if (!info) return <div className="tt-app-download loading" aria-hidden="true" />

  return <section className="tt-app-download" aria-label={t('mobile.app.downloadTitle')}>
    <span className="mark"><AppLaunchIcon size={24} /></span>
    <div className="body">
      <b>{t('mobile.app.downloadTitle')}</b>
      <span>{info.apkVersion ? t('mobile.app.downloadHelpVersion', { v: info.apkVersion }) : t('mobile.app.downloadHelp')}</span>
    </div>
    <a className="download" href={nodeApi('/apk')}>{t('mobile.app.downloadAction')}</a>
    <button type="button" className="guide" onClick={onGuide}>{t('mobile.app.installGuide')}<ChevronRight size={14} /></button>
  </section>
}
