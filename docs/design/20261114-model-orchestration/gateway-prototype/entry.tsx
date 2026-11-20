import { useEffect, useState } from 'react'
import { createRoot } from '../../../../frontend/node_modules/react-dom/client'
import { App, Button } from 'antd'
import { I18nProvider, useI18n } from '../../../../frontend/src/i18n'
import { ThemeProvider, useThemeMode } from '../../../../frontend/src/theme'
import { useLayout } from '../../../../frontend/src/layout'
import { WorkspaceStateProvider } from '../../../../frontend/src/view-state'
import ModelHub from '../../../../frontend/src/components/capabilities/ModelHub'
import { BackLink } from '../../../../frontend/src/components/BackButton'
import { SunIcon, MoonIcon } from '../../../../frontend/src/icons'
import { installFixture, traceCases } from './fixture'
import '../../../../frontend/src/components/capabilities/model-controls.css'
import '../../../../frontend/src/index.css'
import '../../../../frontend/src/mobile-material.css'
import './styles.css'

const paths: Record<string, string> = { overview: 'usage', monitoring: 'monitor' }
const route = () => location.hash.slice(1)
const cases = Object.keys(traceCases)
const docPages: Record<string, string> = { catalog: 'sources', aggregate: 'aggregation', usage: 'usage', monitor: 'monitoring', audit: 'audit', gateway: 'gateway', speech: 'speech' }

function WorkBuddyDemo({ zh, claimed, claim }: { zh: boolean; claimed: boolean; claim: () => void }) {
  const copy = zh
    ? ['WorkBuddy · 账号', '方案演示', '周期积分', '已用 120 / 500 · 11 天后重置', '额外积分', '立即签到', '今日未签', '今日已签 · 领取 20 积分', '返回模型源']
    : ['WorkBuddy account', 'Design preview', 'Cycle credits', '120 / 500 used · resets in 11 days', 'Bonus credits', 'Check in', 'Not checked in today', 'Checked in · 20 credits claimed', 'Back to model sources']
  return <section className="model-prototype-account">
    <header className="tt-pagehead"><BackLink href="#/catalog/source/workbuddy" label={copy[8]} /><h2>{copy[0]}</h2><small>{copy[1]}</small></header>
    <dl><div><dt>{copy[2]}</dt><dd>{copy[3]}</dd></div><div><dt>{copy[4]}</dt><dd>{claimed ? 60 : 40}</dd></div></dl>
    <div className="model-prototype-account-actions"><Button type="primary" disabled={claimed} onClick={claim}>{copy[5]}</Button><span role="status">{copy[claimed ? 7 : 6]}</span></div>
  </section>
}

function Prototype() {
  const { locale, setLocale } = useI18n()
  const zh = locale === 'zh-CN'
  const theme = useThemeMode()
  useLayout()
  const [hash, setHash] = useState(route)
  const [claimed, setClaimed] = useState(false)
  const [page, query] = hash.replace(/^\//, '').replace(/^capabilities\/models\/?/, '').split('?')
  const [requested] = page.split('/')
  const params = new URLSearchParams(query)
  const trace = requested === 'troubleshoot' || params.get('demo') === 'gateway'
  const example = params.get('case') || 'blocked'
  const sample = cases.includes(example) ? example : 'blocked'
  const tab = trace ? 'audit' : paths[requested] || (requested === 'access' || requested === 'directory' ? 'gateway' : requested) || 'catalog'
  const pool = params.get('demo') === 'route'
  const account = page === 'catalog/workbuddy-account'
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
      <div><strong>{zh ? 'Roami 大模型工作台' : 'Roami Model Workspace'}</strong><small>{zh ? '离线演示' : 'Offline demo'}</small></div>
      <nav aria-label={zh ? '设计文档' : 'Design documents'}>
        <a href="./latest-design.html">{zh ? '设计总览' : 'Design overview'}</a>
        <a href={'./model-' + (docPages[tab] || 'gateway') + '.html'}>{zh ? '本页设计' : 'Page design'}</a>
        <Button type="text" aria-label={zh ? '切换主题' : 'Switch theme'} icon={theme.mode === 'dark' ? <SunIcon /> : <MoonIcon />} onClick={theme.toggle} />
        <Button type="text" aria-label={zh ? 'Switch to English' : '切换为中文'} onClick={() => setLocale(zh ? 'en-US' : 'zh-CN')}>{zh ? 'EN' : '中文'}</Button>
      </nav>
    </div>
    {trace && <div className="model-prototype-scenarios" aria-label={zh ? '网关请求演示' : 'Request scenarios'}>
      {cases.filter(key => key !== 'success').map(key => <a key={key} href={'#/troubleshoot?case=' + key} aria-current={key === sample ? 'page' : undefined}>{traceCases[key as keyof typeof traceCases].label[zh ? 0 : 1]}</a>)}
    </div>}
    {!account && page.startsWith('catalog/source/workbuddy') && <div className="model-prototype-scenarios"><a href="#/catalog/workbuddy-account">{zh ? '查看 WorkBuddy 签到方案' : 'Preview WorkBuddy check-in'}</a></div>}
    <main className="model-prototype-main">
      {account && <WorkBuddyDemo zh={zh} claimed={claimed} claim={() => setClaimed(true)} />}
      <div className="model-prototype-workspace" hidden={account}><ModelHub sub={account ? 'catalog' : tab + detail} onNav={path => { location.hash = '/' + path.slice('capabilities/models/'.length) }} /></div>
    </main>
  </div>
}

installFixture()
createRoot(document.getElementById('root')!).render(<I18nProvider><ThemeProvider><App><WorkspaceStateProvider><Prototype /></WorkspaceStateProvider></App></ThemeProvider></I18nProvider>)
