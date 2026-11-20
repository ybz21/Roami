import { useEffect, useRef, useState } from 'react'
import { createRoot } from '../../../../frontend/node_modules/react-dom/client'
import { App, Button } from 'antd'
import { I18nProvider, useI18n } from '../../../../frontend/src/i18n'
import { ThemeProvider, useThemeMode } from '../../../../frontend/src/theme'
import { useLayout } from '../../../../frontend/src/layout'
import { WorkspaceStateProvider } from '../../../../frontend/src/view-state'
import { ChevronRight, SunIcon, MoonIcon } from '../../../../frontend/src/icons'
import ModelHub from '../../../../frontend/src/components/capabilities/ModelHub'
import { installFixture, traceCases } from './fixture'
import { RoutingWorkbench } from './RoutingWorkbench'
import { MagpiePluginDesk } from './MagpiePluginDesk'
import { ObservationPage } from './ObservationPage'
import { AgentSelection } from './AgentSelection'
import { SpeechPreview } from './SpeechPreview'
import '../../../../frontend/src/components/capabilities/model-controls.css'
import '../../../../frontend/src/index.css'
import '../../../../frontend/src/mobile-material.css'
import './routing-workbench.css'
import './pool-strategy-observation.css'
import './styles.css'

const routes = ['catalog', 'aggregate', 'usage', 'monitor', 'audit', 'gateway', 'speech']
const documents: Record<string, string> = {
  catalog: 'sources', aggregate: 'aggregation', usage: 'usage', monitor: 'monitor',
  audit: 'audit', gateway: 'gateway', speech: 'speech', agent: 'agent',
}
const aliases: Record<string, string> = {
  '模型源': 'catalog', '聚合': 'aggregate', '概况': 'usage', '监控': 'monitor', '审计': 'audit',
  '本机网关': 'gateway', '语音输入': 'speech', 'directory': 'gateway', 'monitoring': 'monitor', 'overview': 'usage',
}
const currentRoute = () => {
  const encoded = location.hash.slice(1).replace(/^\//, '').replace(/^capabilities\/models\/?/, '')
  try { return aliases[decodeURIComponent(encoded)] || encoded || 'catalog' }
  catch { return 'catalog' }
}
const traceKeys = Object.keys(traceCases)

function ChinesePrototype() {
  const { locale, setLocale } = useI18n()
  useEffect(() => { if (locale !== 'zh-CN') setLocale('zh-CN') }, [locale, setLocale])
  return <Prototype />
}

function Prototype() {
  const { t } = useI18n()
  const theme = useThemeMode()
  const { phone } = useLayout()
  const nav = useRef<HTMLElement>(null)
  const [route, setRoute] = useState(currentRoute)
  const [catalogVersion, setCatalogVersion] = useState(0)
  const [page, query] = route.split('?')
  const [requested, sub, id] = page.split('/')
  const params = new URLSearchParams(query)
  const workbench = page === 'workbench'
  const agent = page === 'agent'
  const trace = requested === 'troubleshoot' || params.get('demo') === 'gateway'
  const example = params.get('case') || 'blocked'
  const sample = traceKeys.includes(example) ? example : 'blocked'
  const access = requested === 'access'
  const tab = trace ? 'audit' : access ? 'gateway' : routes.includes(requested) ? requested : 'catalog'
  const observation = !trace && !params.has('usageView') && (page === 'monitor' || page === 'audit') ? page : undefined
  const account = page === 'catalog/workbuddy-account'
  const fileImport = page === 'catalog/import' && params.get('view') === 'file'
  const pluginDesk = account || sub === 'plugins' && requested === 'catalog' || page === 'catalog/import' && !fileImport
  const [, , pluginId, pluginAction, pluginItem] = page.split('/')
  const fromPlugin = params.get('from') === 'plugins' && requested === 'catalog' && sub === 'source'
  const previousPlugin = params.get('plugin') || ''
  const fromWorkbench = params.get('from') === 'workbench' || /^audit\/request\/[^/]+\/workbench$/.test(page)
  const detail = trace ? '/request/' + sample : page.slice(requested.length)
  const useHub = !workbench && !agent && !pluginDesk && !observation

  useEffect(() => {
    const read = () => setRoute(currentRoute())
    window.addEventListener('hashchange', read)
    return () => window.removeEventListener('hashchange', read)
  }, [])
  useEffect(() => {
    if (phone) nav.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [phone, tab, agent, workbench])
  useEffect(() => {
    const selector = access ? '.tt-gateway-tabs [data-node-key="access"]'
      : page === 'monitor/sources' ? '.tt-monitor-workspace [data-node-key="sources"]'
      : page === 'monitor/requests' ? '.tt-monitor-workspace [data-node-key="requests"]'
      : page.startsWith('aggregate/') && page.endsWith('/members') ? '.tt-aggregate-tabs [data-node-key="members"]'
      : null
    if (!selector) return
    const activate = () => {
      const control = document.querySelector(selector)
      if (!control) return false
      control.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }))
      return true
    }
    if (activate()) return
    const observer = new MutationObserver(() => { if (activate()) observer.disconnect() })
    observer.observe(document.querySelector('.model-prototype-main')!, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [page, access])

  const navigateHub = (path: string) => {
    const next = path.slice('capabilities/models/'.length)
    if (fromPlugin && next === 'catalog') location.hash = '/catalog/plugins/' + encodeURIComponent(previousPlugin) + '/account/' + id
    else if (fromPlugin && next.startsWith('catalog/source/')) location.hash = '/' + next + '?from=plugins&plugin=' + encodeURIComponent(previousPlugin)
    else if (fileImport && next === 'catalog') location.hash = '/catalog/plugins'
    else if (fromWorkbench && next === tab) location.hash = '/workbench'
    else if (fromWorkbench && next.startsWith('catalog/source/') && sub === 'source') location.hash = '/' + next + '?from=workbench'
    else location.hash = '/' + next
  }
  const selected = workbench ? 'workbench' : agent ? 'agent' : tab
  const doc = pluginDesk ? 'plugins' : documents[selected] || 'aggregation'
  return <div className="model-prototype">
    <header className="model-prototype-bar">
      <div><a href="./index.html" className="prototype-crumb">能力</a><ChevronRight /><strong>大模型</strong><small>交互原型</small></div>
      <nav aria-label="原型资料">
        <a href={'./' + doc + '.html'}>本页设计</a>
        <Button type="text" aria-label="切换主题" icon={theme.mode === 'dark' ? <SunIcon /> : <MoonIcon />} onClick={theme.toggle} />
      </nav>
    </header>
    <div className="model-prototype-frame">
      <nav ref={nav} className="prototype-model-nav" aria-label="大模型页面">
        {routes.map(key => <a key={key} href={'#/' + key} aria-current={selected === key ? 'page' : undefined}>{t('hub.tab.' + key)}</a>)}
        <a href="#/workbench" aria-current={workbench ? 'page' : undefined}>调度与排查</a>
        <a href="#/agent" aria-current={agent ? 'page' : undefined}>Agent 选模</a>
      </nav>
      <main className="model-prototype-main">
        {trace && <nav className="model-prototype-scenarios" aria-label="请求演示">
          {traceKeys.filter(key => key !== 'success').map(key => <a key={key} href={'#/troubleshoot?case=' + key} aria-current={key === sample ? 'page' : undefined}>{traceCases[key as keyof typeof traceCases].label[0]}</a>)}
        </nav>}
        <div className="model-prototype-workspace" hidden={!workbench}><RoutingWorkbench showStrategy={workbench && params.get('view') === 'strategy'} /></div>
        {observation && <ObservationPage key={observation} view={observation} />}
        {agent && <AgentSelection />}
        {pluginDesk && <MagpiePluginDesk pluginId={account ? 'workbuddy' : pluginId}
          action={account ? 'account' : pluginAction} itemId={account ? 'workbuddy' : pluginItem}
          syncSources={() => setCatalogVersion(value => value + 1)} />}
        <div className="model-prototype-workspace" hidden={!useHub}>
          {page === 'catalog' && <div className="model-prototype-scenarios"><a href="#/catalog/plugins">插件与账号<ChevronRight /></a></div>}
          {page === 'catalog/source/workbuddy' && <div className="model-prototype-scenarios"><a href="#/catalog/workbuddy-account">查看 WorkBuddy 账号<ChevronRight /></a></div>}
          <div className={'prototype-hub-surface' + (page === 'speech' ? ' prototype-speech-surface' : '')}>
            <ModelHub key={catalogVersion} sub={useHub ? tab + detail : 'catalog'} onNav={navigateHub} />
            {page === 'speech' && <SpeechPreview />}
          </div>
        </div>
      </main>
    </div>
  </div>
}

installFixture()
createRoot(document.getElementById('root')!).render(
  <I18nProvider><ThemeProvider><App><WorkspaceStateProvider><ChinesePrototype /></WorkspaceStateProvider></App></ThemeProvider></I18nProvider>,
)
