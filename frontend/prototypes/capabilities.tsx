import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntApp } from 'antd'
import { I18nProvider, useI18n } from '../src/i18n'
import { ThemeProvider, useThemeMode } from '../src/theme'
import { useLayout } from '../src/layout'
import { PlugIcon, AppsIcon } from '../src/icons'
import CapabilitiesPage from '../src/components/capabilities/CapabilitiesPage'
import { loadPreferences } from '../src/preferences'
import { installPrototypeApi } from './capability-catalog'
import '../src/index.css'
import '../src/mobile-material.css'
import './capabilities.css'

installPrototypeApi()
void loadPreferences()
function Prototype() {
  const { t, setLocale } = useI18n()
  const { setMode } = useThemeMode()
  const { phone } = useLayout()
  const [sub, setSub] = useState(() => new URLSearchParams(location.search).get('tab') || 'agents')
  const controls = useRef({ setMode, setLocale })
  controls.current = { setMode, setLocale }
  useEffect(() => {
    const apply = (event: MessageEvent) => {
      if (event.source !== window.parent || event.data?.type !== 'capability-prototype-settings') return
      if (event.data.theme) controls.current.setMode(event.data.theme)
      if (event.data.locale) controls.current.setLocale(event.data.locale)
      if (event.data.tab) setSub(event.data.tab)
    }
    window.addEventListener('message', apply)
    window.parent.postMessage({ type: 'capability-prototype-ready' }, '*')
    return () => window.removeEventListener('message', apply)
  }, [])
  return <div className="prototype-shell">
    {!phone && <aside className="prototype-nav"><strong><AppsIcon size={22} />Roami</strong><small>{t('capabilities.prototype.badge')}</small><button type="button" className="on" onClick={() => setSub('agents')}><PlugIcon size={18} />{t('nav.capabilities')}</button><span className="prototype-note">{t('capabilities.prototype.localHint')}</span></aside>}
    <main>{phone && <header className="prototype-topbar"><AppsIcon size={20} /><strong>{t('nav.capabilities')}</strong><small>{t('capabilities.prototype.badge')}</small></header>}<div className="prototype-canvas"><CapabilitiesPage sub={sub} onNav={route => setSub(route.replace(/^capabilities\//, ''))} /></div></main>
  </div>
}
createRoot(document.getElementById('root')!).render(<I18nProvider><ThemeProvider><AntApp><Prototype /></AntApp></ThemeProvider></I18nProvider>)
