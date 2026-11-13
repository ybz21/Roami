import { usePageEffect } from '../../page-activity'
// PWA「添加到桌面 / 主屏幕」：手机 / 平板，兼顾 Android 与 iOS（桌面浏览器也兼容）。
// 设计：只要尚未以独立应用运行，就始终提供「安装」按钮。点击时——
//  - 能拿到 beforeinstallprompt（Android / 桌面 Chromium 且满足条件）→ 触发系统原生安装；
//  - 否则按平台弹出图文引导（iOS Safari 分享 / Android Chrome 菜单 / 桌面地址栏安装）。
import { useCallback, useState, type ReactNode } from 'react'
import { Modal } from 'antd'
import { useI18n } from '../../i18n'

// beforeinstallprompt 可能在 React 挂载前就触发，模块级提前捕获，避免错过。
let deferred: any = null
let captured = false
function ensureCapture() {
  if (captured || typeof window === 'undefined') return
  captured = true
  window.addEventListener('beforeinstallprompt', (e: any) => {
    e.preventDefault()
    deferred = e
    window.dispatchEvent(new Event('tt-pwa-installable'))
  })
  window.addEventListener('appinstalled', () => {
    deferred = null
    window.dispatchEvent(new Event('tt-pwa-installed'))
  })
}
ensureCapture()

// 已作为独立应用(添加到桌面后)运行
function standalone(): boolean {
  try {
    return window.matchMedia('(display-mode: standalone)').matches
      || window.matchMedia('(display-mode: fullscreen)').matches
      || window.matchMedia('(display-mode: minimal-ui)').matches
      || (navigator as any).standalone === true
  } catch { return false }
}

function isIOS(): boolean {
  const ua = navigator.userAgent || ''
  if (/iphone|ipad|ipod/i.test(ua)) return true
  // iPadOS 13+ 默认请求桌面站点、UA 伪装成 Mac，用触摸点数辅助判断
  return navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1
}
function platform(): 'ios' | 'android' | 'desktop' {
  if (isIOS()) return 'ios'
  if (/android/i.test(navigator.userAgent || '')) return 'android'
  return 'desktop'
}

// installed: 是否已安装(standalone)；install(): 触发安装/引导；guide: 需渲染一次的引导弹窗。
export function usePwaInstall() {
  const { t } = useI18n()
  const [installed, setInstalled] = useState(standalone())
  const [, force] = useState(0)
  const [guideOpen, setGuideOpen] = useState(false)

  usePageEffect(() => {
    if (standalone()) { setInstalled(true); return }
    const sync = () => force((n) => n + 1) // deferred 变化时刷新（按钮文案/行为可能切换）
    const onInstalled = () => { setInstalled(true); setGuideOpen(false) }
    window.addEventListener('tt-pwa-installable', sync)
    window.addEventListener('tt-pwa-installed', onInstalled)
    return () => {
      window.removeEventListener('tt-pwa-installable', sync)
      window.removeEventListener('tt-pwa-installed', onInstalled)
    }
  }, [])

  const install = useCallback(async () => {
    if (deferred) {
      try { deferred.prompt(); await deferred.userChoice } catch {}
      deferred = null
      return
    }
    setGuideOpen(true) // 无原生提示：弹平台引导
  }, [])

  const plat = platform()
  const steps: string[] = plat === 'ios'
    ? [t('install.iosStep1'), t('install.iosStep2'), t('install.iosStep3')]
    : plat === 'android'
      ? [t('install.androidStep1'), t('install.androidStep2'), t('install.androidStep3')]
      : [t('install.desktopStep1'), t('install.desktopStep2')]
  const title = plat === 'ios' ? t('install.iosTitle') : plat === 'android' ? t('install.androidTitle') : t('install.desktopTitle')
  const note = plat === 'ios' ? t('install.iosNote') : plat === 'android' ? t('install.androidNote') : t('install.desktopNote')

  const guide: ReactNode = (
    <Modal open={guideOpen} onCancel={() => setGuideOpen(false)} footer={null} title={title} width={380} centered>
      <ol style={{ paddingLeft: 18, margin: '4px 0 0', lineHeight: 2, color: 'var(--text-bright)' }}>
        {steps.map((s, i) => <li key={i}>{s}</li>)}
      </ol>
      <div style={{ marginTop: 12, color: 'var(--text-dim)', fontSize: 12 }}>{note}</div>
    </Modal>
  )

  // 未安装即可显示按钮：能原生安装更好，否则点了弹引导
  return { installable: !installed, installed, install, guide }
}
