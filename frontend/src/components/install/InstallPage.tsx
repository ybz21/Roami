// 「装到手机」（24 稿 M-B）：三步清单 装证书 → 加到主屏 → 开推送，每步亮着「已做 / 未做」，
// 做完推送那步就能收到锁屏通知。桌面上打开只提示在手机浏览器开这个地址（扫码配对 2026-09-28 删了：
// 手机版就是网页本身，省一次敲口令不值一套令牌）。
import { useEffect, useState, type ReactNode } from 'react'
import { Button, Spin, Typography } from 'antd'
import { api } from '../../api'
import { nodeApi } from '../cluster/node-url'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { AppLaunchIcon, CheckIcon, ShieldIcon, DeviceIcon, MegaphoneIcon } from '../../icons'
import { usePwaInstall } from '../auth/install'
import { PushSettings } from '../settings/push-settings'
import { pushEnabled, pushSupported } from '../../push'

type Info = { tls: boolean; selfSigned: boolean; apk?: boolean }

function isIOS(): boolean {
  const ua = navigator.userAgent || ''
  return /iphone|ipad|ipod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

function Step({ n, icon, title, done, children }: { n: number; icon: ReactNode; title: string; done: boolean; children: ReactNode }) {
  const { t } = useI18n()
  return (
    <section className={`tt-install-step${done ? ' done' : ''}`}>
      <div className="hd">
        <span className="ic">{icon}</span>
        <b>{n}. {title}</b>
        {done && <span className="ok"><CheckIcon size={13} />{t('install.stepDone')}</span>}
      </div>
      <div className="bd">{children}</div>
    </section>
  )
}

export default function InstallPage() {
  const { t } = useI18n()
  const { phone } = useLayout()
  const [info, setInfo] = useState<Info | null>(null)
  useEffect(() => { api('GET', '/install-info').then((r) => setInfo(r.data)).catch(() => setInfo({ tls: false, selfSigned: false })) }, [])

  const { installed, install, guide } = usePwaInstall()
  const [pushOn, setPushOn] = useState(false)
  useEffect(() => { void pushEnabled().then(setPushOn) }, [])
  // 证书装好了浏览器才把本站当安全上下文；没装的话 SW / 推送 / 麦克风全都没有
  const secure = typeof window !== 'undefined' && window.isSecureContext && 'serviceWorker' in navigator
  const ios = isIOS()

  if (info === null) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>
  const needCert = info.tls && info.selfSigned

  return (
    <div className="tt-install">
      {!phone && <div className="tt-pagehead" style={{ marginBottom: 'var(--sp-4)' }}><div className="ttl"><div className="kicker">{t('install.eyebrow')}</div><h2>{t('install.pageTitle')}</h2><p>{t('install.pageLead')}</p></div></div>}

      {!phone && (
        <section className="tt-install-qr">
          <div className="txt">
            <b>{t('install.openOnPhone')}</b>
            <p>{t('install.openOnPhoneHelp')}</p>
            <Typography.Text code copyable>{location.origin}</Typography.Text>
          </div>
        </section>
      )}

      {/* 安卓真 App（mobile/android 打的包，部署者放到 <dataDir>/roami.apk 才出现）：
          装了它就不用下面三步——网址在 App 里输，通知走 App 自己的长连接 */}
      {info.apk && !ios && (
        <section className="tt-install-step app">
          <div className="hd"><span className="ic"><AppLaunchIcon size={16} /></span><b>{t('install.appTitle')}</b></div>
          <div className="bd">
            <p>{t('install.appHelp')}</p>
            <Button type="primary" href={nodeApi('/apk')}>{t('install.appDownload')}</Button>
          </div>
        </section>
      )}

      {needCert && (
        <Step n={1} icon={<ShieldIcon size={16} />} title={t('install.certTitle')} done={secure}>
          <p>{t('install.certWhyShort')}</p>
          <ol>
            <li><a href="/cert.crt" target="_blank" rel="noreferrer">{t('install.downloadCert')}</a></li>
            {ios
              ? <><li>{t('install.certIos2')}</li><li>{t('install.certIos3')}</li></>
              : <><li>{t('install.certStep2')}</li><li>{t('install.certStep3')}</li></>}
            <li>{t('install.certReopen')}</li>
          </ol>
        </Step>
      )}

      <Step n={needCert ? 2 : 1} icon={<DeviceIcon size={16} />} title={t('install.homeTitle')} done={installed}>
        <p>{ios ? t('install.homeIosWhy') : t('install.homeWhy')}</p>
        {!installed && <Button type="primary" onClick={install}>{t('install.button')}</Button>}
        {guide}
      </Step>

      <Step n={needCert ? 3 : 2} icon={<MegaphoneIcon size={16} />} title={t('set.push')} done={pushOn}>
        <p>{ios && !installed ? t('install.pushIosFirst') : !pushSupported() ? t('set.pushUnsupported') : t('install.pushWhy')}</p>
        <span onClick={() => { void pushEnabled().then(setPushOn) }}><PushSettings /></span>
      </Step>
    </div>
  )
}
