// 关于与安装：Logo / 版本号 / 检查更新（走后端 /update-check，带缓存与降级）/
// 仓库链接 / 装成 PWA / 下载自签证书。装 PWA 与证书是一件事的两半——
// 没有受信任的证书，安卓根本不给「安装应用」。
import { useEffect, useState } from 'react'
import { App as AntApp, Button, Space } from 'antd'
import { CheckIcon, GithubIcon } from '../../icons'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { usePwaInstall } from '../auth/install'
import { CertDownloadButton } from './security-settings'

export function AboutSettings() {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const { installed: pwaInstalled, install: doInstall, guide: installGuide } = usePwaInstall()
  const [info, setInfo] = useState<{ version?: string; repo?: string }>({})
  const [checking, setChecking] = useState(false)
  const [latest, setLatest] = useState<{ tag: string; url: string; newer: boolean; failed?: boolean } | null>(null)
  useEffect(() => { api('GET', '/version').then((d: any) => setInfo(d?.data || {})).catch(() => {}) }, [])
  const repo = info.repo || 'ybz21/Roam'
  const releasesUrl = `https://github.com/${repo}/releases`
  // 走后端 /update-check（带缓存+优雅降级），避免浏览器直连 GitHub API 的限流/跨域/被墙问题
  const checkUpdate = async () => {
    setChecking(true); setLatest(null)
    try {
      const d = (await api('GET', '/update-check'))?.data || {}
      if (d.error || !d.latest) {
        setLatest({ tag: '', url: d.releases || releasesUrl, newer: false, failed: true })
        message.warning(t('about.checkFailed'))
      } else {
        setLatest({ tag: d.latest, url: d.url || d.releases || releasesUrl, newer: !!d.newer, failed: false })
      }
    } catch {
      setLatest({ tag: '', url: releasesUrl, newer: false, failed: true })
      message.error(t('about.checkFailed'))
    } finally { setChecking(false) }
  }
  return (
    <Space direction="vertical" size={18} align="center" style={{ width: '100%', padding: 'var(--sp-3) 0' }}>
        <img src="/logo-mark.svg" width={72} height={72} alt="Roami" />
        <div style={{
          fontWeight: 800, fontSize: 28, letterSpacing: 0.5,
          background: 'var(--brand-grad)', WebkitBackgroundClip: 'text', backgroundClip: 'text', WebkitTextFillColor: 'transparent',
        }}>Roami</div>
        <p style={{ color: 'var(--text-dim)', fontSize: 13, lineHeight: 1.7, margin: 0, textAlign: 'left', maxWidth: 420 }}>
          {t('about.intro')}
        </p>
        <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
          {t('settings.version')} <code>{info.version || '—'}</code>
        </div>
        <Space wrap style={{ justifyContent: 'center' }}>
          <Button loading={checking} onClick={checkUpdate}>{t('about.checkUpdate')}</Button>
          {latest?.failed && (
            <a href={latest.url} target="_blank" rel="noreferrer">
              <Button>{t('about.goReleases')}</Button>
            </a>
          )}
          {latest && !latest.failed && (latest.newer
            ? <a href={latest.url} target="_blank" rel="noreferrer">
                <Button type="primary">{t('about.newVersion', { tag: latest.tag })}</Button>
              </a>
            : <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>{t('about.upToDate')}</span>)}
        </Space>
        <a href={`https://github.com/${repo}`} target="_blank" rel="noreferrer"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: 'var(--text-bright)', fontSize: 14 }}>
          <GithubIcon size={18} /><span>github.com/{repo}</span>
        </a>
      <Space wrap style={{ justifyContent: 'center' }}>
        {pwaInstalled
          ? <span style={{ color: 'var(--text-bright)', display: 'inline-flex', alignItems: 'center', gap: 5 }}><CheckIcon size={13} />{t('install.installed')}</span>
          : <Button type="primary" onClick={doInstall}>{t('install.button')}</Button>}
        <CertDownloadButton />
      </Space>
      <span style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-meta)' }}>{t('install.settingsHelp')}</span>
      {installGuide}
      {/* 证书与推送（24 稿 §7）：连通性和证书都是部署者的事，这里只把话说清楚、给链接 */}
      <div style={{ marginTop: 'var(--sp-3)', padding: 'var(--sp-3)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--r-sm)', background: 'var(--bg-base)', fontSize: 'var(--fs-meta)', color: 'var(--text-dim)', lineHeight: 1.7 }}>
        <div style={{ color: 'var(--text-bright)', fontWeight: 600, marginBottom: 2 }}>{t('about.certTitle')}</div>
        <div>{t('about.certAndroid')}</div>
        <div>{t('about.certIphone')} <a href="/cert.crt" target="_blank" rel="noreferrer">{t('about.certDownload')}</a></div>
        <div>{t('about.certOwn')}</div>
      </div>
    </Space>
  )
}
