import ModelAggregationWorkspace from './ModelAggregationWorkspace'
import ModelMonitoringWorkspace from './ModelMonitoringWorkspace'
import SourcePricingSettings, { sourcePriceDraftChanged, type SourcePriceDraft } from './SourcePricingSettings'
import BackButton from '../BackButton'
import ModelUsageWorkspace from './ModelUsageWorkspace'
import { useState } from 'react'
import { Alert, App, Button, Dropdown, Input, Modal, Popconfirm, Select, Spin, Tabs } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { getHashParams } from '../../route-hash'
import { PlusIcon, LinkIcon, PencilIcon } from '../../icons'
import { useSettingsDraft } from '../settings/settings-draft'
import { SpeechSettings } from '../settings/speech-settings'
import MobileSubPage from '../MobileSubPage'
import LocalModelSources from './LocalModelSources'
import GatewayAccessKey from './GatewayAccessKeys'
import MagpiePluginImport from './MagpiePluginImport'
import MagpieSourceSettings from './MagpieSourceSettings'
import ModelSourceEditor, { initialSourceDraft, type SourceDraft } from './ModelSourceEditor'
import { GatewaySettingsForm, GatewayReconciliation, useGatewaySettings } from '../settings/gateway-settings'
import { useModelCatalog, type ModelSource, type CatalogModel } from './model-hub-api'
import '../settings/agent-settings.css'
import './model-hub.css'

const tabs = ['catalog', 'aggregate', 'usage', 'monitor', 'audit', 'gateway', 'speech']
const newID = () => globalThis.crypto?.randomUUID?.() || Date.now().toString(36)
export default function ModelHub({ sub = '', onNav, embedded = false }: { sub?: string; onNav: (path: string) => void; embedded?: boolean }) {
  const { t, locale } = useI18n(), { message, modal } = App.useApp(), layout = useLayout()
  const controller = useModelCatalog(), loaded = controller.value
  const value = loaded || { revision: '', sources: [], models: [], drafts: [], baseUrl: '', uses: {} }
  const [requested, rawDetail, id, section] = sub.split('/')
  const legacy = getHashParams().get('modelTab')
  const detail = requested === 'prices' || (!requested && legacy === 'prices') ? 'pricing' : rawDetail
  const tab = requested === 'prices' ? 'catalog' : requested === 'sources' ? 'catalog' : tabs.includes(requested) ? requested : legacy === 'prices' ? 'catalog' : legacy === 'proxy' ? 'usage' : 'catalog'
  const billing = useGatewaySettings(tab === 'usage' || tab === 'audit' || tab === 'catalog')
  const [newSourceId, setNewSourceId] = useState(newID), [newModelId, setNewModelId] = useState(newID)
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, SourceDraft>>({}), [modelDrafts, setModelDrafts] = useState<Record<string, CatalogModel>>({})
  const [sourcePrices, setSourcePrices] = useState<Record<string, SourcePriceDraft>>({})
  const [returnSource, setReturnSource] = useState('')
  const [priceReturn, setPriceReturn] = useState('catalog')
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null)
  const [gatewayKeyDraft, setGatewayKeyDraft] = useState('')
  const draftNotice = useSettingsDraft('onboarding-model-hub', { sourceDrafts, modelDrafts }, { sourceDrafts: {}, modelDrafts: {} }, draft => { setSourceDrafts(draft.sourceDrafts); setModelDrafts(draft.modelDrafts) }, embedded)
  const navigate = (path: string) => onNav('capabilities/models/' + path)
  const back = () => { navigate(detail === 'pricing' ? priceReturn : detail === 'model' && returnSource ? 'catalog/source/' + returnSource : tab); setReturnSource('') }
  const error = controller.error && <Alert type="error" role="alert" message={t(controller.error)} action={<Button onClick={controller.retry}>{t('capabilities.models.reread')}</Button>} />
  const models = value?.models || [], sources = value?.sources || []
  const priceModels = [...new Set(models.flatMap(model => model.candidates.map(candidate => candidate.model)).concat(models.flatMap(model => [model.id, ...model.candidates.map(candidate => candidate.sourceId + "/" + candidate.model)])))]
  if (!loaded && tab === 'catalog' && detail && detail !== 'pricing') return <div className="tt-model-hub-scroll">{error || <Spin />}</div>
  const sourceBase: ModelSource = sources.find(source => source.id === id) || { id: newSourceId, name: '', baseUrl: '', protocol: 'openai-completions', authMode: 'api_key', apiKey: '' }
  const sourceDraft = sourceDrafts[id] || initialSourceDraft(sourceBase, id !== 'new')
  const modelBase: CatalogModel = models.find(model => model.id === id) || value.drafts.find(model => model.id === id) || { id: newModelId, name: '', protocol: sources[0]?.protocol || 'openai-completions', strategy: 'fixed', candidates: [{ sourceId: sources[0]?.id || '', model: '' }] }
  const model = modelDrafts[id] || modelBase
  const updateModel = (patch: Partial<CatalogModel>) => setModelDrafts(previous => ({ ...previous, [id]: { ...model, ...patch } }))
  const validModel = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/.test(model.id) && model.candidates.length > 0 && (model.strategy !== 'failover' || model.candidates.length > 1) && model.candidates.every(candidate => candidate.model.trim() && sources.some(source => source.id === candidate.sourceId)) && !models.some(row => row.id === model.id && row.id !== id)
  const saveModel = async () => {
    const next = { ...model, name: model.name.trim() || model.candidates[0].model.trim(), candidates: model.strategy === 'fixed' ? model.candidates.slice(0, 1) : model.candidates }
    if (await controller.save({ ...value, models: [...models.filter(row => row.id !== next.id), next], drafts: value.drafts.filter(row => row.id !== next.id) })) {
      setModelDrafts(previous => { const n = { ...previous }; delete n[id]; return n }); if (id === 'new') setNewModelId(newID()); message.success(t('hub.modelSaved')); back()
    }
  }
  const submitModel = () => {
    if (!validModel || controller.busy) return
    const users = [...new Set(value.uses[model.id] || [])]
    if (users.length) modal.confirm({ className: 'tt-model-connection-confirm', title: t('agent.models.save'), content: t('hub.modelImpact', { users: users.join(', ') }), onOk: saveModel })
    else void saveModel()
  }
  const selectSource = (sourceId: string, index: number) => {
    const protocol = sources.find(source => source.id === sourceId)?.protocol || model.protocol
    updateModel({ ...(index === 0 ? { protocol } : {}), candidates: model.candidates.map((row, i) => i === index ? { ...row, sourceId } : row) })
  }
  const candidateFields = (index: number) => <>
    <label className="agent-settings-field">{t('hub.source')}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.source')} value={model.candidates[index].sourceId || undefined} options={sources.map(source => ({ value: source.id, label: source.name }))} onChange={sourceId => selectSource(sourceId, index)} /></label>
    <label className="agent-settings-field">{t('hub.upstreamModel')}<Input aria-label={t('hub.upstreamModel')} value={model.candidates[index].model} onChange={event => updateModel({ candidates: model.candidates.map((row, i) => i === index ? { ...row, model: event.target.value } : row) })} /></label>
  </>
  const connectionEditor = <>{sourceBase.pluginSourceId && <MagpieSourceSettings key={sourceBase.id} sourceId={sourceBase.pluginSourceId} onChanged={controller.retry} />}<ModelSourceEditor key={sourceBase.id} draft={sourceDraft} onChange={draft => setSourceDrafts(previous => ({ ...previous, [id]: draft }))} catalog={value} busy={controller.busy} error={controller.error} retry={controller.retry} onBack={back} onEditModel={modelID => { setReturnSource(id); navigate('catalog/model/' + modelID) }} onSave={async next => {
    const saved = await controller.save(next)
    if (saved) {
      setSourceDrafts(previous => { const next = { ...previous }; delete next[id]; return next })
      if (id === 'new') setNewSourceId(newID())
    }
    return saved
  }} /></>
  const sourceEditor = id === 'new' ? connectionEditor : <div className="tt-source-workspace">
    <Tabs activeKey={section || 'connection'} onChange={key => navigate('catalog/source/' + id + '/' + key)} items={['prices','connection','routing'].map(key => ({key,label:t('pricing.section.'+key)}))}/>
    {(section === 'prices' || section === 'routing') ? <SourcePricingSettings key={sourceBase.id} sourceId={sourceBase.id} view={section} models={[...new Set(models.flatMap(model=>model.candidates.filter(candidate=>candidate.sourceId===sourceBase.id).map(candidate=>candidate.model)))]} draft={sourcePrices[sourceBase.id]} onChange={draft=>setSourcePrices(previous=>({...previous,[sourceBase.id]:draft}))} onSaved={billing.setSourcePolicy} onGlobal={()=>{setPriceReturn('catalog/source/'+id+'/prices');navigate('catalog/pricing')}} onAddModels={()=>{setSourceDrafts(previous=>({...previous,[id]:{...(previous[id]||initialSourceDraft(sourceBase,true)),fetchRequested:true}}));navigate('catalog/source/'+id+'/connection')}}/> : connectionEditor}
  </div>
  const modelEditor = <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); submitModel() }}>
    <label className="agent-settings-field">{t('hub.displayName')}<Input aria-label={t('hub.displayName')} value={model.name} maxLength={100} onChange={event => updateModel({ name: event.target.value })} /></label>
    {candidateFields(0)}
    {!sources.length && <Button icon={<PlusIcon />} onClick={() => navigate('catalog/source/new')}>{t('hub.addSource')}</Button>}
    <details><summary>{t('hub.strategy')}</summary>
      <label className="agent-settings-field">{t('hub.strategy')}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.strategy')} value={model.strategy} options={['fixed', 'failover'].map(value => ({ value, label: t('hub.strategy.' + value) }))} onChange={strategy => updateModel({ strategy, candidates: model.candidates.slice(0, 1) })} /></label>
      {model.candidates.slice(1).map((_, offset) => <fieldset key={offset}><legend>{t('hub.backup', { index: offset + 1 })}</legend>
        {candidateFields(offset + 1)}
        <Button onClick={() => updateModel({ candidates: model.candidates.filter((_, i) => i !== offset + 1) })}>{t('agent.proxy.remove')}</Button>
      </fieldset>)}
      {model.strategy === 'failover' && <Button disabled={model.candidates.length >= 8} icon={<PlusIcon />} onClick={() => updateModel({ candidates: [...model.candidates, { sourceId: '', model: '' }] })}>{t('hub.addBackup')}</Button>}
      <p className="agent-settings-hint">{t('hub.failoverHint')}</p>
    </details>
    <p className="agent-settings-hint">{t('hub.availableHint')}</p>
    <div className="agent-settings-save"><BackButton onClick={back} /><Button type="primary" htmlType="submit" disabled={!validModel || controller.busy} loading={controller.busy}>{t('agent.models.save')}</Button></div>
  </form>
  const editor = detail === 'pricing' ? <div className="tt-model-hub-scroll">{error}<GatewaySettingsForm controller={billing} mode="prices" active models={priceModels} /></div> : detail === 'import' ? <MagpiePluginImport onRetry={controller.retry} revision={value.revision} onImported={() => { controller.retry(); back() }} /> : detail === 'local' ? <LocalModelSources onImported={() => { controller.retry(); back() }} /> : detail === 'source' ? sourceEditor : <div className="tt-model-hub-scroll">{error}{modelEditor}</div>
  const editorTitle = detail === 'source' && id !== 'new' ? sourceBase.name : t(detail === 'pricing' ? 'agent.gateway.defaultPrice' : detail === 'import' ? 'hub.plugin.import' : detail === 'local' ? 'hub.local.title' : detail === 'source' ? id === 'new' ? 'hub.addSource' : 'hub.editSource' : 'hub.editModel')
  const fullDetail = detail === 'source' || detail === 'pricing'
  const rows = sources.map(source => {
    const attached = models.filter(model => !model.aggregate && model.candidates[0].sourceId === source.id)
    const backupUsed = models.some(model => (model.aggregate || model.candidates[0].sourceId !== source.id) && model.candidates.some(candidate => candidate.sourceId === source.id))
    const preview = new Intl.ListFormat(locale, { style: 'short', type: 'conjunction' }).format(attached.slice(0, 3).map(model => model.name))
    let label = source.name
    try { if (!label || label === source.baseUrl) label = new URL(source.baseUrl).host } catch { /* Keep the saved source name. */ }
    return <section className="tt-model-connection" key={source.id} aria-label={source.name}>
      <div className="tt-model-connection-head"><span className="tt-model-connection-icon"><LinkIcon size={24} /></span><div><div className="tt-model-connection-title"><strong>{label}</strong><button type="button" className="tt-act tt-model-source-rename" disabled={controller.busy} aria-label={t('hub.renameSource')} onClick={() => setRenaming({ id: source.id, name: source.name })}><PencilIcon /></button></div><small>{source.pluginSourceId ? t('hub.plugin.source') : source.baseUrl}</small></div>
        <Button onClick={() => { setSourceDrafts(previous => ({ ...previous, [source.id]: { ...(previous[source.id] || initialSourceDraft(source, true)), editing: true } })); navigate('catalog/source/' + source.id) }}>{t('hub.directory.configureSource')}</Button>
      </div>
      {<dl className="tt-model-connection-settings">
        <div><dt>{t('capabilities.models.protocol')}</dt><dd>{t('capabilities.models.protocol.' + source.protocol)}</dd></div>
        <div><dt>{t('capabilities.models.authMode')}</dt><dd>{t('capabilities.models.auth.' + source.authMode)}</dd></div>
      </dl>}
      {<div className="tt-model-connection-preview"><span>{t(attached.length ? 'hub.directory.total' : 'hub.empty.catalog', { count: new Intl.NumberFormat(locale).format(attached.length) })}</span>{!!attached.length && <p>{preview}</p>}</div>}
      {source.pluginDesktopUnavailable && <p className="agent-settings-hint">{t('hub.plugin.desktopOnly')}</p>}
      {backupUsed && <p className="agent-settings-hint">{t('hub.connectionBackupUsed')}</p>}
      <div className="tt-model-connection-pricing"><span>{t('pricing.default')}</span><strong>{t('pricing.'+(billing.saved?.pricing.sources?.[source.id]?.default?.mode || 'inherit'))}</strong>{sourcePriceDraftChanged(sourcePrices[source.id],billing.saved?.pricing.sources?.[source.id]) && <small>{t('pricing.draftKept')}</small>}</div>
      <div className="tt-model-connection-footer"><Button type="primary" aria-label={t('pricing.openSource',{name:source.name})} onClick={()=>navigate('catalog/source/'+source.id+'/prices')}>{t('pricing.action')}</Button><Button onClick={()=>navigate('catalog/source/'+source.id+'/routing')}>{t('pricing.section.routing')}</Button>
        <Button disabled={controller.busy} onClick={() => { setSourceDrafts(previous => ({ ...previous, [source.id]: { ...(previous[source.id] || initialSourceDraft(source, true)), fetchRequested: true } })); navigate('catalog/source/' + source.id) }}>{t('hub.directory.updateModels')}</Button>
        <Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t('hub.deleteConnection')} description={source.pluginDesktop ? t('hub.plugin.deleteDesktopHint') : undefined} onConfirm={() => controller.save({ ...value, sources: sources.filter(row => row.id !== source.id), models: models.filter(model => model.candidates[0].sourceId !== source.id) })}><button type="button" className="tt-act danger" disabled={backupUsed}>{t('capabilities.models.deleteAction')}</button></Popconfirm>
      </div>
    </section>
  })
  const saveSourceName = async () => {
    if (!renaming || controller.busy || !renaming.name.trim() || renaming.name.trim() === sources.find(source => source.id === renaming.id)?.name) return
    const name = renaming.name.trim(), sourceId = renaming.id
    if (await controller.save({ ...value, sources: sources.map(source => source.id === sourceId ? { ...source, name } : source) })) {
      setSourceDrafts(previous => previous[sourceId] ? { ...previous, [sourceId]: { ...previous[sourceId], source: { ...previous[sourceId].source, name }, original: { ...previous[sourceId].original, name } } } : previous)
      setRenaming(null)
    }
  }
  const consumers = Object.entries(value.uses).filter(([, users]) => users.length)
  if (embedded && detail) return <div className="onboarding-model-editor">{draftNotice}{editor}</div>
  return <div className={embedded ? 'tt-model-hub onboarding-model-hub' : 'tt-model-hub'}>
    {draftNotice}
    <Modal className="tt-model-source-name-dialog" title={t('hub.renameSource')} open={!!renaming} destroyOnHidden onCancel={() => { if (!controller.busy) setRenaming(null) }} onOk={() => void saveSourceName()} confirmLoading={controller.busy} okText={t('agent.models.save')} cancelText={t('common.cancel')} okButtonProps={{ disabled: !renaming?.name.trim() || renaming.name.trim() === sources.find(source => source.id === renaming.id)?.name }}>
      {controller.error && <Alert type="error" message={t(controller.error)} action={<Button onClick={controller.retry}>{t('capabilities.models.reread')}</Button>} />}
      <label className="agent-settings-field">{t('hub.directory.sourceName')}<Input aria-label={t('hub.name')} autoFocus value={renaming?.name || ''} maxLength={100} disabled={controller.busy} onChange={event => setRenaming(previous => previous && { ...previous, name: event.target.value })} onPressEnter={() => void saveSourceName()} /></label>
    </Modal>
    {<div className="tt-model-hub-main" hidden={!!detail && layout.phone}>
      <Tabs tabPosition={layout.phone ? 'top' : 'left'} className="tt-model-hub-tabs" activeKey={tab} onChange={key => navigate(key)} items={tabs.map(key => ({ key, label: t('hub.tab.' + key + (layout.phone ? '.compact' : '')) }))} />
      <div className="tt-model-catalog-detail" hidden={!fullDetail || layout.phone}><header className="tt-pagehead"><BackButton onClick={back}/><h2>{editorTitle}</h2></header>{fullDetail && !layout.phone && editor}</div>
      <ModelUsageWorkspace active={tab === 'usage' || tab === 'audit'} mode={tab === 'audit' ? 'audit' : 'overview'} controller={billing} sources={sources} onAudit={() => navigate('audit')} onOverview={()=>navigate('usage')} />
      <ModelAggregationWorkspace active={tab==='aggregate'} catalog={loaded} busy={controller.busy} error={controller.error} save={controller.save} retry={controller.retry} onSource={source=>navigate('catalog/source/'+source)}/>
      <ModelMonitoringWorkspace active={tab==='monitor'} catalog={loaded}/>
      {tab==='aggregate'||tab==='monitor'?null:fullDetail ? null : tab === 'usage' || tab === 'audit' ? <GatewayReconciliation controller={billing} /> : <div className="tt-model-hub-scroll">
      {tab !== 'speech' && error}
      {tab === 'speech' ? <section className="tt-model-hub-speech" aria-label={t('hub.speechTitle')}><SpeechSettings /></section> : tab === 'gateway' ? <section className="tt-model-hub-entry" aria-label={t('hub.tab.gateway')}><p>{t('hub.entryHint')}</p>{value.baseUrl && <div className="agent-settings-field"><span>{t('agent.models.baseUrl')}</span><code>{value.baseUrl + '/v1'}</code></div>}<p>{t('hub.continuationHint')}</p><GatewayAccessKey onChanged={controller.retry} value={gatewayKeyDraft} onChange={setGatewayKeyDraft} /></section>
        : <>{loaded ? <><div className="tt-model-hub-actions"><Button onClick={()=>{setPriceReturn('catalog');navigate('catalog/pricing')}}>{t('agent.gateway.defaultPrice')}</Button><Dropdown trigger={['click']} menu={{ items: [{ key: 'source/new', label: t('hub.addSource') }, { key: 'import', label: t('hub.plugin.import') }, { key: 'local', label: t('hub.local.title') }], onClick: ({ key }) => navigate('catalog/' + key) }}><Button type="primary" icon={<PlusIcon />}>{t('common.create')}</Button></Dropdown></div>{rows.length ? <div className="tt-model-connections">{rows}</div> : <p>{t('hub.empty.connections')}</p>}
        {!!consumers.length && <section className="tt-model-hub-consumers"><div className="tt-model-hub-actions"><h3>{t('hub.consumers')}</h3></div>{consumers.map(([model, users]) => <div className="tt-model-hub-row" key={model}><div><strong>{models.find(row => row.id === model)?.name || model}</strong><small>{[...new Set(users)].join(', ')}</small></div><Button onClick={() => onNav('capabilities/agents/' + users[0] + '/models')}>{t('hub.configure')}</Button></div>)}</section>}</> : !error && <Spin />}
        </>}
    </div>}</div>}
    {detail && (layout.phone ? <MobileSubPage title={editorTitle} search={false} onBack={back} manageHistory={false}>{editor}</MobileSubPage> : !fullDetail && <aside className="tt-model-hub-detail"><div className="tt-model-hub-detail-head"><BackButton onClick={back} /><h3>{editorTitle}</h3></div>{editor}</aside>)}
  </div>
}
