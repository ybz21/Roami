import { useEffect, useState } from 'react'
import { App, Switch } from 'antd'
import { Alert, Button, Select, TabBar } from './model-controls'
import { CopyIcon, LinkIcon, ChevronDown, ChevronRight } from '../../icons'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { gatewayModelName, type ModelCatalog } from './model-hub-api'
import { gatewayBaseURL, gatewayCallableModels, gatewayCallExample, type GatewayProtocol } from './gateway-call-example'
import GatewayAccessKeys from './GatewayAccessKeys'
import GatewayModelDirectory from './GatewayModelDirectory'
import './gateway-workspace.css'

export default function ModelGatewayWorkspace({ active, catalog, onChanged, onSource, onPool, onConfigure }: { active: boolean; catalog: ModelCatalog; onChanged: () => void; onSource: (id: string) => void; onPool?: (id: string) => void; onConfigure?: (id: string) => void }) {
  const { t } = useI18n(), { message } = App.useApp(), { phone } = useLayout()
  const [tab, setTab] = useState('access'), [keyDraft, setKeyDraft] = useState(''), [modelId, setModelId] = useState(''), [language, setLanguage] = useState('curl'), [sampleOpen, setSampleOpen] = useState(false)
  const [visited, setVisited] = useState(active), [directoryVisited, setDirectoryVisited] = useState(false)
  useEffect(() => { if (active) setVisited(true) }, [active])
  const [protocol, setProtocol] = useState<GatewayProtocol>('openai')
  const [network, setNetwork] = useState<{ enabled: boolean; urls: string[] } | null>(null)
  const [networkBusy, setNetworkBusy] = useState(false), [networkError, setNetworkError] = useState('')
  const [networkRetry, setNetworkRetry] = useState(0), [selectedHost, setSelectedHost] = useState('')
  useEffect(() => {
    if (!active) return
    const abort = new AbortController()
    setNetworkError('')
    void api('GET', '/agent/model-gateway/network', undefined, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) setNetwork({ enabled: !!data?.enabled, urls: Array.isArray(data?.urls) ? data.urls : [] })
    }).catch(() => { if (!abort.signal.aborted) setNetworkError('gatewayWorkspace.networkFailed') })
    return () => abort.abort()
  }, [active, networkRetry])
  const setLAN = async (enabled: boolean) => {
    setNetworkBusy(true)
    setNetworkError('')
    try {
      const { data } = await api('PUT', '/agent/model-gateway/network', { enabled })
      setNetwork(data)
      setSelectedHost('')
      onChanged()
    } catch (error: any) {
      setNetworkError(error?.apiError?.code === 'MODEL_GATEWAY_LAN_UNAVAILABLE' ? 'gatewayWorkspace.lanUnavailable' : 'gatewayWorkspace.networkFailed')
    } finally { setNetworkBusy(false) }
  }
  const localHost = (catalog.baseUrl || '').replace(/\/+$/, '')
  const hosts = [localHost, ...(network?.urls || [])].filter(Boolean)
  const host = hosts.includes(selectedHost) ? selectedHost : network?.urls[0] || localHost
  const endpoint = gatewayBaseURL(host, protocol)
  const models = gatewayCallableModels(catalog), selected = models.find(model => model.id === modelId) || models[0]
  const code = selected && endpoint ? gatewayCallExample(endpoint, gatewayModelName(selected, catalog), language, protocol) : ''
  const modelOptions = models.map(model => {
    const name = gatewayModelName(model, catalog)
    return { value: model.id, label: model.name === name ? name : model.name + ' · ' + name }
  })
  const copy = async (value: string) => { try { await navigator.clipboard.writeText(value); message.success(t('common.copied')) } catch { message.error(t('gatewayWorkspace.copyFailed')) } }
  const selectTab = (value: string) => {
    setTab(value)
    if (value === 'directory') setDirectoryVisited(true)
  }
  const access = <div className="tt-gateway-access-grid">
    <section className="tt-gateway-connection" aria-label={t('agent.models.baseUrl')}>
      <div className="tt-gateway-section-head"><h3><LinkIcon />{t('agent.models.baseUrl')}</h3></div>
      <label className="tt-gateway-lan-toggle">
        <span>{t('gatewayWorkspace.allowLAN')}</span>
        <Switch aria-label={t('gatewayWorkspace.allowLAN')} checked={!!network?.enabled} loading={networkBusy} disabled={!network} onChange={enabled => void setLAN(enabled)} />
      </label>
      {networkError && <Alert type="warning" role="alert" message={t(networkError)} action={<Button onClick={() => setNetworkRetry(value => value + 1)}>{t('agent.retry')}</Button>} />}
      {!!network?.enabled && !network.urls.length && !networkError && <p className="agent-settings-hint">{t('gatewayWorkspace.lanUnavailable')}</p>}
      <label className="agent-settings-field"><span>{t('gatewayWorkspace.protocol')}</span><Select<GatewayProtocol> aria-label={t('gatewayWorkspace.protocol')} value={protocol} options={[{ value: 'openai', label: 'OpenAI' }, { value: 'anthropic', label: 'Anthropic' }]} onChange={setProtocol} /></label>
      {hosts.length > 1 && <label className="agent-settings-field"><span>{t('gatewayWorkspace.address')}</span><Select<string> aria-label={t('gatewayWorkspace.address')} value={host} options={hosts.map(value => ({ value, label: t(value === localHost ? 'gatewayWorkspace.hostOnly' : 'gatewayWorkspace.lanAddress') + ' · ' + value }))} onChange={setSelectedHost} /></label>}
      <div className="tt-gateway-copy-field"><code>{endpoint || t('directory.unknown')}</code><Button type="text" icon={<CopyIcon />} aria-label={t('gatewayWorkspace.copyEndpoint')} disabled={!endpoint} onClick={() => void copy(endpoint)} /></div>
      <p className="agent-settings-hint">{t(host !== localHost ? 'gatewayWorkspace.lanKeyHint' : 'gatewayWorkspace.hostHint')}</p>
      <Button type="link" icon={<ChevronRight />} onClick={() => selectTab('directory')}>{t('gatewayWorkspace.chooseModel')}</Button>
    </section>
    <section className="tt-gateway-sample" aria-label={t('gatewayWorkspace.sample')}><div className="tt-gateway-section-head"><h3>{phone ? <Button type="text" icon={<ChevronDown />} aria-expanded={sampleOpen} onClick={() => setSampleOpen(previous => !previous)}>{t('gatewayWorkspace.sample')}</Button> : t('gatewayWorkspace.sample')}</h3>{(!phone || sampleOpen) && <><TabBar className="tt-gateway-example-tabs" label={t('gatewayWorkspace.language')} activeKey={language} onChange={setLanguage} items={[{ key: 'curl', label: 'curl' }, { key: 'python', label: 'Python' }]} /><Button type="text" icon={<CopyIcon />} disabled={!code} aria-label={t('gatewayWorkspace.copyExample')} onClick={() => void copy(code)} /></>}</div>
      {(!phone || sampleOpen) && (models.length ? <><label className="agent-settings-field tt-gateway-sample-model"><span>{t('gatewayWorkspace.sampleModel')}</span><Select<string> aria-label={t('gatewayWorkspace.sampleModel')} value={selected?.id} options={modelOptions} onChange={setModelId} /></label>{selected && onConfigure && <Button type="link" onClick={() => onConfigure(selected.id)}>{t('gatewayWorkspace.configureModel')}</Button>}<pre tabIndex={0}>{code}</pre><p className="agent-settings-hint">{t('gatewayWorkspace.environmentHint')}</p></> : <p className="tt-gateway-empty">{t('gatewayWorkspace.noCallable')}</p>)}
    </section>
  </div>
  return <section className="tt-model-gateway" hidden={!active} aria-label={t('hub.tab.gateway')}>
    {!phone && <header className="tt-pagehead"><h2>{t('hub.tab.gateway')}</h2><span className="tt-gateway-protocol">{t('gatewayWorkspace.compatible')}</span></header>}
    <TabBar className="tt-gateway-tabs" activeKey={tab} onChange={selectTab} items={['access', 'directory'].map(key => ({ key, label: t('modelInteraction.gateway.' + key) }))} />
    {visited && <div className="tt-gateway-tab" hidden={tab !== 'access'}><GatewayAccessKeys active={active && tab === 'access'} onChanged={onChanged} value={keyDraft} onChange={setKeyDraft}>{access}</GatewayAccessKeys></div>}
    {directoryVisited && <div className="tt-gateway-tab" hidden={tab !== 'directory'}><GatewayModelDirectory active={active && tab === 'directory'} catalog={catalog} onSource={onSource} onPool={onPool} onConfigure={onConfigure} /></div>}
  </section>
}
