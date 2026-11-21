import { useEffect, useState } from 'react'
import { App } from 'antd'
import { Button, Select, TabBar } from './model-controls'
import { CopyIcon, LinkIcon, ChevronDown, ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import type { ModelCatalog } from './model-hub-api'
import { gatewayCallableModels, gatewayCallExample, gatewayLoopback } from './gateway-call-example'
import GatewayAccessKeys from './GatewayAccessKeys'
import GatewayModelDirectory from './GatewayModelDirectory'
import './gateway-workspace.css'

export default function ModelGatewayWorkspace({ active, catalog, onChanged, onSource, onPool }: { active: boolean; catalog: ModelCatalog; onChanged: () => void; onSource: (id: string) => void; onPool?: (id: string) => void }) {
  const { t } = useI18n(), { message } = App.useApp(), { phone } = useLayout()
  const [tab, setTab] = useState('access'), [keyDraft, setKeyDraft] = useState(''), [modelId, setModelId] = useState(''), [language, setLanguage] = useState('curl'), [sampleOpen, setSampleOpen] = useState(false)
  const [visited, setVisited] = useState(active), [directoryVisited, setDirectoryVisited] = useState(false)
  useEffect(() => { if (active) setVisited(true) }, [active])
  const endpoint = catalog.baseUrl ? catalog.baseUrl.replace(/\/+$/, '') + '/v1' : ''
  const models = gatewayCallableModels(catalog), selected = models.find(model => model.id === modelId) || models[0]
  const code = selected && endpoint ? gatewayCallExample(endpoint, selected.id, language) : ''
  const copy = async (value: string) => { try { await navigator.clipboard.writeText(value); message.success(t('common.copied')) } catch { message.error(t('gatewayWorkspace.copyFailed')) } }
  const selectTab = (value: string) => {
    setTab(value)
    if (value === 'directory') setDirectoryVisited(true)
  }
  const access = <div className="tt-gateway-access-grid">
    <section className="tt-gateway-connection" aria-label={t('agent.models.baseUrl')}><div className="tt-gateway-section-head"><h3><LinkIcon />{t('agent.models.baseUrl')}</h3>{gatewayLoopback(endpoint) && <span className="tt-gateway-pill">{t('gatewayWorkspace.hostOnly')}</span>}</div><div className="tt-gateway-copy-field"><code>{endpoint || t('directory.unknown')}</code><Button type="text" icon={<CopyIcon />} aria-label={t('gatewayWorkspace.copyEndpoint')} disabled={!endpoint} onClick={() => void copy(endpoint)} /></div><p className="agent-settings-hint">{t(gatewayLoopback(endpoint) ? 'gatewayWorkspace.hostHint' : 'hub.entryHint')}</p><Button type="link" icon={<ChevronRight />} onClick={() => selectTab('directory')}>{t('gatewayWorkspace.chooseModel')}</Button></section>
    <section className="tt-gateway-sample" aria-label={t('gatewayWorkspace.sample')}><div className="tt-gateway-section-head"><h3>{phone ? <Button type="text" icon={<ChevronDown />} aria-expanded={sampleOpen} onClick={() => setSampleOpen(previous => !previous)}>{t('gatewayWorkspace.sample')}</Button> : t('gatewayWorkspace.sample')}</h3>{(!phone || sampleOpen) && <><TabBar className="tt-gateway-example-tabs" label={t('gatewayWorkspace.language')} activeKey={language} onChange={setLanguage} items={[{ key: 'curl', label: 'curl' }, { key: 'python', label: 'Python' }]} /><Button type="text" icon={<CopyIcon />} disabled={!code} aria-label={t('gatewayWorkspace.copyExample')} onClick={() => void copy(code)} /></>}</div>
      {(!phone || sampleOpen) && (models.length ? <><label className="agent-settings-field tt-gateway-sample-model"><span>{t('gatewayWorkspace.sampleModel')}</span><Select<string> aria-label={t('gatewayWorkspace.sampleModel')} value={selected?.id} options={models.map(model => ({ value: model.id, label: model.name === model.id ? model.id : model.name + ' · ' + model.id }))} onChange={setModelId} /></label><pre tabIndex={0}>{code}</pre><p className="agent-settings-hint">{t('gatewayWorkspace.environmentHint')}</p></> : <p className="tt-gateway-empty">{t('gatewayWorkspace.noCallable')}</p>)}
    </section>
  </div>
  return <section className="tt-model-gateway" hidden={!active} aria-label={t('hub.tab.gateway')}>
    {!phone && <header className="tt-pagehead"><h2>{t('hub.tab.gateway')}</h2><span className="tt-gateway-protocol">{t('gatewayWorkspace.compatible')}</span></header>}
    <TabBar className="tt-gateway-tabs" activeKey={tab} onChange={selectTab} items={['access', 'directory'].map(key => ({ key, label: t('modelInteraction.gateway.' + key) }))} />
    {visited && <div className="tt-gateway-tab" hidden={tab !== 'access'}><GatewayAccessKeys active={active && tab === 'access'} onChanged={onChanged} value={keyDraft} onChange={setKeyDraft}>{access}</GatewayAccessKeys></div>}
    {directoryVisited && <div className="tt-gateway-tab" hidden={tab !== 'directory'}><GatewayModelDirectory active={active && tab === 'directory'} catalog={catalog} onSource={onSource} onPool={onPool} /></div>}
  </section>
}
