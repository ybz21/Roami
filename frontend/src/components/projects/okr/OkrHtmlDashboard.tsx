import { usePageActive, usePageEffect } from '../../../page-activity'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Spin } from 'antd'
import { api } from '../../../api'
import { nodeApi } from '../../cluster/node-url'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { useThemeMode } from '../../../theme'
import { dashboardDatasets } from './dashboard-datasets'
import type { Workspace } from './okr-workspace'
import './okr-html-dashboard.css'

type DocumentDefinition = { projectId: string; revision: number; digest: string; metricIds: string[]; libraries: string[] }
type LoadedDocument = { scope: string; definition: DocumentDefinition; libraries: string[] }
const tokens = [
  '--bg-base', '--bg-container', '--bg-elevated', '--text-bright', '--text-dim', '--text-dimmer', '--border', '--border-subtle',
  '--accent', '--accent-solid', '--accent-soft', '--accent-border', '--ok', '--ok-solid', '--ok-soft', '--ok-border', '--warn', '--danger',
  '--fs-micro', '--fs-meta', '--fs-sm', '--fs-body', '--fs-lg', '--fs-title', '--sp-1', '--sp-2', '--sp-3', '--sp-4', '--sp-5',
  '--r-xs', '--r-sm', '--r-card', '--r-pill', '--tap',
]
const same = (a: string[], b: string[]) => JSON.stringify(a) === JSON.stringify(b)

export default function OkrHtmlDashboard({ workspace, active, onRefresh }: { workspace: Workspace; active: boolean; onRefresh?: () => void }) {
  const pageActive = usePageActive()
  const [visible, setVisible] = useState(() => !document.hidden)
  const running = active && pageActive && visible
  usePageEffect(() => {
    const update = () => setVisible(!document.hidden)
    update()
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  const { t, locale } = useI18n(), layout = useLayout(), theme = useThemeMode()
  const root = '/projects/' + encodeURIComponent(workspace.projectId) + '/okr/dashboard'
  const digest = workspace.projectFiles?.dashboardDigest || ''
  const scope = nodeApi(root) + ':' + digest
  const [loaded, setLoaded] = useState<LoadedDocument | null>(null), [error, setError] = useState(''), [ready, setReady] = useState(false), [retry, setRetry] = useState(0)
  const [css, setCSS] = useState<Record<string, string>>({})
  const iframe = useRef<HTMLIFrameElement>(null), channel = useRef<MessageChannel | null>(null), latestScope = useRef(scope), loads = useRef(0)
  latestScope.current = scope
  const latestWorkspace = useRef(workspace); latestWorkspace.current = workspace
  const refresh = useRef(onRefresh); refresh.current = onRefresh
  const nonce = useMemo(() => crypto.randomUUID().replace(/-/g, ''), [scope, running, retry])
  const html = workspace.dashboard?.html
  const requestScope = useRef(scope); requestScope.current = scope
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const style = getComputedStyle(document.documentElement)
      setCSS(Object.fromEntries(tokens.map(token => [token, style.getPropertyValue(token).trim()])))
    })
    return () => cancelAnimationFrame(frame)
  }, [theme.mode, layout.size])
  useEffect(() => {
    if (!running || !html) { setLoaded(null); return }
    let stopped = false
    const controller = new AbortController()
    setError(''); setReady(false)
    void api('GET', root, undefined, { signal: controller.signal }).then(async response => {
      const definition: DocumentDefinition = response.data
      if (stopped || requestScope.current !== scope) return
      const current = latestWorkspace.current.dashboard?.html
      if (definition.projectId !== latestWorkspace.current.projectId || definition.digest !== digest || !/^[a-f0-9]{64}$/.test(definition.digest) || !current || !same(definition.metricIds, current.metricIds) || !same(definition.libraries, current.libraries || [])) throw new Error('DASHBOARD_CHANGED')
      const libraries = definition.libraries.includes('echarts') ? [(await import('echarts/dist/echarts.min.js?raw')).default] : []
      if (!stopped && requestScope.current === scope) setLoaded({ scope, definition, libraries })
    }).catch(() => { if (!stopped && requestScope.current === scope) setError(scope) })
    return () => { stopped = true; controller.abort() }
  }, [scope, root, digest, running, retry])
  const loadedDocument = loaded?.scope === scope ? loaded : null
  const datasets = useMemo(() => dashboardDatasets(workspace, html?.metricIds || []), [workspace, html?.metricIds])
  const context = { locale, theme: theme.mode, size: layout.size, pointer: layout.coarse ? 'coarse' : 'fine', revision: workspace.revision, tokens: css }
  const snapshot = JSON.stringify({ type: 'okr:snapshot', digest, context, datasets })
  const latestSnapshot = useRef(snapshot); latestSnapshot.current = snapshot
  useEffect(() => {
    setReady(false); loads.current = 0
    return () => { channel.current?.port1.close(); channel.current?.port2.close(); channel.current = null }
  }, [scope, running, nonce])
  useEffect(() => { if (running && ready) channel.current?.port1.postMessage(JSON.parse(snapshot)) }, [snapshot, running, ready])
  useEffect(() => {
    if (!running || !loadedDocument || ready || error === scope) return
    const timer = setTimeout(() => { setError(scope); channel.current?.port1.close() }, 15000)
    return () => clearTimeout(timer)
  }, [running, loadedDocument, ready, error, scope, nonce])
  const initialize = () => {
    if (!loadedDocument || !iframe.current?.contentWindow || latestScope.current !== scope || nodeApi(root) + ':' + digest !== scope) return
    if (++loads.current > 1) { channel.current?.port1.close(); setError(scope); return }
    channel.current?.port1.close()
    const connection = new MessageChannel(); channel.current = connection
    connection.port1.onmessage = event => {
      if (latestScope.current !== scope || channel.current !== connection || event.data?.digest !== digest) return
      if (event.data.type === 'okr:ready') setReady(true)
      if (event.data.type === 'okr:error') { setError(scope); connection.port1.close() }
    }
    connection.port1.start()
    iframe.current.contentWindow.postMessage({ type: 'okr:init', nonce, digest }, '*', [connection.port2])
    connection.port1.postMessage({ ...JSON.parse(latestSnapshot.current), libraries: loadedDocument.libraries })
  }
  if (!running) return null
  const failed = error === scope
  return <section className="okr-html-dashboard" aria-label={t('okr.tab.dashboard')} data-ready={ready}>
    {failed ? <div className="okr-html-status" role="alert"><p>{t('okr.html.loadFailed')}</p><button type="button" className="tt-act" onClick={() => { refresh.current?.(); setError(''); setLoaded(null); setRetry(value => value + 1) }}>{t('agent.retry')}</button></div> : <>
      {!ready && <div className="okr-html-status"><Spin /></div>}
      {loadedDocument && <iframe key={scope + ':' + nonce} ref={iframe} title={t('okr.tab.dashboard')} sandbox="allow-scripts" referrerPolicy="no-referrer" allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'" src={nodeApi(root + '/document?digest=' + digest + '&nonce=' + nonce)} onLoad={initialize} />}
    </>}
  </section>
}
