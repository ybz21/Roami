import { useEffect, useState } from 'react'
import { createRoot } from '../../../../frontend/node_modules/react-dom/client'
import { App, Button } from 'antd'
import { I18nProvider, useI18n } from '../../../../frontend/src/i18n'
import { ThemeProvider, useThemeMode } from '../../../../frontend/src/theme'
import { useLayout } from '../../../../frontend/src/layout'
import { WorkspaceStateProvider } from '../../../../frontend/src/view-state'
import ModelHub from '../../../../frontend/src/components/capabilities/ModelHub'
import { ChevronRight, SunIcon, MoonIcon } from '../../../../frontend/src/icons'
import { installFixture, traceCases } from './fixture'
import { RoutingWorkbench } from './RoutingWorkbench'
import { MagpiePluginDesk } from './MagpiePluginDesk'
import '../../../../frontend/src/components/capabilities/model-controls.css'
import '../../../../frontend/src/index.css'
import '../../../../frontend/src/mobile-material.css'
import './styles.css'
import './routing-workbench.css'
import './pool-strategy-observation.css'

const paths: Record<string, string> = { overview: 'usage', monitoring: 'monitor' }
const route = () => location.hash.slice(1)
const cases = Object.keys(traceCases)
const docPages: Record<string, string> = { catalog: 'sources', aggregate: 'aggregation', usage: 'usage', monitor: 'monitoring', audit: 'audit', gateway: 'gateway', speech: 'speech' }

function Prototype() {
  const { locale, setLocale } = useI18n()
  const zh = locale === 'zh-CN'
  const theme = useThemeMode()
  useLayout()
  const [hash, setHash] = useState(route)
  const [catalogVersion, setCatalogVersion] = useState(0)
  const [page, query] = hash.replace(/^\//, '').replace(/^capabilities\/models\/?/, '').split('?')
  const [requested] = page.split('/')
  const params = new URLSearchParams(query)
  const trace = requested === 'troubleshoot' || params.get('demo') === 'gateway'
  const example = params.get('case') || 'blocked'
  const sample = cases.includes(example) ? example : 'blocked'
  const tab = trace ? 'audit' : paths[requested] || (requested === 'access' || requested === 'directory' ? 'gateway' : requested) || 'catalog'
  const pool = params.get('demo') === 'route'
  const workbench = !page || page === 'workbench'
  const workBuddyAccount = page === 'catalog/workbuddy-account'
  const pluginsPage = page === 'catalog/plugins' || page.startsWith('catalog/plugins/')
  const fileImport = page === 'catalog/import' && params.get('view') === 'file'
  const pluginDesk = workBuddyAccount || pluginsPage || (page === 'catalog/import' && !fileImport)
  const [, , pluginId, pluginAction, pluginItem] = page.split('/')
  const fromPlugin = params.get('from') === 'plugins' && page.startsWith('catalog/source/')
  const previousPlugin = params.get('plugin') || ''
  const fromWorkbench = params.get('from') === 'workbench' || /^audit\/request\/[^/]+\/workbench$/.test(page)
  const detail = trace ? '/request/' + sample : pool ? '/request/fallback/aggregate/free' : page.slice(requested.length)

  useEffect(() => {
    const read = () => setHash(route())
    window.addEventListener('hashchange', read)
    return () => window.removeEventListener('hashchange', read)
  }, [])
  useEffect(() => {
    const target = ['access', 'directory'].includes(requested) ? '.tt-gateway-tabs [data-node-key="' + requested + '"]'
      : page === 'monitor/sources' ? '.tt-monitor-workspace [data-node-key="sources"]'
      : page === 'monitor/requests' ? '.tt-monitor-workspace [data-node-key="requests"]'
      : page.startsWith('aggregate/') && page.endsWith('/members') ? '.tt-aggregate-tabs [data-node-key="members"]'
      : null
    if (!target) return
    const activate = () => {
      const button = document.querySelector(target)
      if (!button) return false
      button.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }))
      return true
    }
    if (activate()) return
    const observer = new MutationObserver(() => { if (activate()) observer.disconnect() })
    observer.observe(document.querySelector('.model-prototype-main')!, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [page, requested])

  return <div className="model-prototype">
    <div className="model-prototype-bar">
      <div><strong>{zh ? 'Roami 大模型工作台' : 'Roami Model Workspace'}</strong><small>{pluginDesk ? (zh ? '操作演示' : 'Action demo') : (zh ? '离线演示' : 'Offline demo')}</small></div>
      <nav aria-label={zh ? '原型导航' : 'Prototype navigation'}>
        {workbench ? <a href="#/catalog">{zh ? '模型管理' : 'Manage models'}</a>
          : <a href="#/workbench">{zh ? '调度与排查' : 'Routing & incidents'}</a>}
        <a href="./latest-design.html">{zh ? '设计总览' : 'Design overview'}</a>
        {!workbench && <a href={'./model-' + (docPages[tab] || 'gateway') + '.html'}>{zh ? '本页设计' : 'Page design'}</a>}
        <Button type="text" aria-label={zh ? '切换主题' : 'Switch theme'} icon={theme.mode === 'dark' ? <SunIcon /> : <MoonIcon />} onClick={theme.toggle} />
        <Button type="text" aria-label={zh ? 'Switch to English' : '切换为中文'} onClick={() => setLocale(zh ? 'en-US' : 'zh-CN')}>{zh ? 'EN' : '中文'}</Button>
      </nav>
    </div>
    {trace && <div className="model-prototype-scenarios" aria-label={zh ? '网关请求演示' : 'Request scenarios'}>
      {cases.filter(key => key !== 'success').map(key => <a key={key} href={'#/troubleshoot?case=' + key} aria-current={key === sample ? 'page' : undefined}>{traceCases[key as keyof typeof traceCases].label[zh ? 0 : 1]}</a>)}
    </div>}
    {page === 'catalog' && <div className="model-prototype-scenarios"><a href="#/catalog/plugins">{zh ? '插件与账号' : 'Plugins and accounts'}<ChevronRight /></a></div>}
    {!pluginDesk && page === 'catalog/source/workbuddy' && <div className="model-prototype-scenarios"><a href="#/catalog/workbuddy-account">{zh ? '查看 WorkBuddy 账号' : 'Open the WorkBuddy account'}<ChevronRight /></a></div>}
    <main className="model-prototype-main">
      <div className="model-prototype-workspace" hidden={!workbench}><RoutingWorkbench showStrategy={workbench && params.get('view') === 'strategy'} /></div>
      {pluginDesk && <MagpiePluginDesk pluginId={workBuddyAccount ? 'workbuddy' : pluginId}
        action={workBuddyAccount ? 'account' : pluginAction} itemId={workBuddyAccount ? 'workbuddy' : pluginItem}
        syncSources={() => setCatalogVersion(value => value + 1)} />}
      <div className="model-prototype-workspace" hidden={pluginDesk || workbench}><ModelHub key={catalogVersion} sub={pluginDesk || workbench ? 'catalog' : tab + detail} onNav={path => {
        const next = path.slice('capabilities/models/'.length)
        if (fromPlugin && next === 'catalog') location.hash = '/catalog/plugins/' + encodeURIComponent(previousPlugin) + '/account/' + page.split('/')[2]
        else if (fromPlugin && next.startsWith('catalog/source/')) location.hash = '/' + next + '?from=plugins&plugin=' + encodeURIComponent(previousPlugin)
        else if (fileImport && next === 'catalog') location.hash = '/catalog/plugins'
        else if (fromWorkbench && next === tab) location.hash = '/workbench'
        else if (fromWorkbench && next.startsWith('catalog/source/') && page.startsWith('catalog/source/')) location.hash = '/' + next + '?from=workbench'
        else location.hash = '/' + next
      }} /></div>
    </main>
  </div>
}

installFixture()
createRoot(document.getElementById('root')!).render(<I18nProvider><ThemeProvider><App><WorkspaceStateProvider><Prototype /></WorkspaceStateProvider></App></ThemeProvider></I18nProvider>)
