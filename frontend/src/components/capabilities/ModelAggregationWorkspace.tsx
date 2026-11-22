import AggregationPoolCard from './AggregationPoolCard'
import AggregationEditor, { type AggregationSection } from './AggregationEditor'
import { MAX_AGGREGATE_MEMBERS } from './routing-preview'
import { useState } from 'react'
import { App } from 'antd'
import { Alert, Button, Input, Spin } from './model-controls'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { PlusIcon, SearchIcon } from '../../icons'
import BackButton from '../BackButton'
import MobileSubPage from '../MobileSubPage'
import type { CatalogModel, ModelCatalog, ModelCandidate } from './model-hub-api'
import './model-routing.css'
const identity = (candidate: ModelCandidate) => candidate.sourceId + '/' + candidate.model
const draftKey = (pool: string | null) => pool === null ? '@new' : 'pool:' + pool
const emptyPool = (): CatalogModel => ({ id: globalThis.crypto?.randomUUID?.() || 'pool-' + Date.now().toString(36), name: '', aggregate: true, enabled: true, protocol: 'openai-completions', strategy: 'smart', candidates: [], cooldownSeconds: 60, onLimit: true, onExhausted: true, minContext: 0, weights: {} })
export default function ModelAggregationWorkspace({ active, catalog, busy, error, save, retry, onSource, onRequest, onRequestLimits, requestedPool, requestedSection, requestedRequest, onOpenRequested, onCloseRequested }: {
  active: boolean; catalog: ModelCatalog | null; busy: boolean; error: string; save: (value: ModelCatalog) => Promise<boolean>; retry: () => void
  onSource: (source: string) => void; onRequest: (id: string, pool: string) => void; onRequestLimits: () => void
  requestedPool?: string; requestedSection?: string; requestedRequest?: string
  onOpenRequested: (pool: string, section?: AggregationSection, requestId?: string) => void; onCloseRequested: () => void
}) {
  const { t } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const [drafts, setDrafts] = useState<Record<string, CatalogModel>>({}), [creating, setCreating] = useState(false), [query,setQuery]=useState('')
  const pools = catalog?.models.filter(model => model.aggregate) || []
  const savedPool = pools.find(pool => pool.id === requestedPool)
  const original = savedPool?.id ?? null
  const key = draftKey(original), draft = drafts[key] ?? savedPool
  const newPoolOpen = !requestedPool && creating
  const section = requestedSection === 'members' || requestedSection === 'monitor' || requestedSection === 'requests' ? requestedSection : 'routing'
  const requestId = section === 'requests' ? requestedRequest : undefined
  const openSection = (section: AggregationSection, id?: string) => { if (original) onOpenRequested(original, section, id) }
  const create = () => {
    setDrafts(previous => previous['@new'] ? previous : { ...previous, '@new': emptyPool() })
    setCreating(true)
  }
  const closeEditor = () => {
    if (original) onCloseRequested()
    else setCreating(false)
  }
  const cancel = () => { setDrafts(previous => { const next = { ...previous }; delete next[key]; return next }); closeEditor() }
  const patch = (value: Partial<CatalogModel>) => {
    if (draft) setDrafts(previous => ({ ...previous, [key]: { ...(previous[key] ?? draft), ...value } }))
  }
  const sources = catalog?.sources || []
  const valid = !!draft && !!draft.name.trim() && draft.id !== 'roami-default' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/.test(draft.id) && draft.candidates.length > 0 && draft.candidates.length <= MAX_AGGREGATE_MEMBERS && (draft.aliases?.length || 0) + (original && draft.id !== original && !draft.aliases?.includes(draft.id) ? 1 : 0) <= 32 && draft.candidates.every(candidate => candidate.model && (candidate.sourceId === '@group' || sources.some(source => source.id === candidate.sourceId)) && Number.isInteger(draft.weights?.[identity(candidate)] ?? 1) && (draft.weights?.[identity(candidate)] ?? 1) >= 1 && (draft.weights?.[identity(candidate)] ?? 1) <= 1000) && !catalog?.models.some(model => (model.id === draft.id || model.aliases?.includes(draft.id)) && model.id !== original)
  const submit = async () => { if (!catalog || !draft || !valid || busy) return; const next = { ...draft, name: draft.name.trim(), aliases: [...new Set([...(draft.aliases || []), ...(original && original !== draft.id ? [original] : [])])].filter(id => id !== draft.id) }; if (await save({ ...catalog, models: original ? catalog.models.map(model => model.id === original ? next : model) : [...catalog.models, next] })) { cancel(); message.success(t('pool.saved')) } }
  const card = (model: CatalogModel) => {
    const savedDraft = drafts[draftKey(model.id)]
    return <AggregationPoolCard key={model.id} model={model} disabled={busy} unsaved={!!savedDraft && JSON.stringify(savedDraft) !== JSON.stringify(model)} onOpen={() => onOpenRequested(model.id)} />
  }
  const remove = async () => { if (!catalog || !original || busy) return false; const saved = await save({ ...catalog, models: catalog.models.filter(row => row.id !== original) }); if (saved) cancel(); return saved }
  const editor = draft && catalog && <AggregationEditor key={key} model={draft} original={original} catalog={catalog} active={active} busy={busy} valid={valid} error={error} retry={retry} section={original ? section : undefined} requestId={requestId} onSection={openSection} onChange={patch} onSave={() => void submit()} onCancel={cancel} onDelete={remove} onSource={onSource} onRequest={id => { if (original) onRequest(id, original) }} onTrace={id => openSection('requests', id)} onRequestLimits={onRequestLimits} />
  const title = savedPool?.name || t('pool.create')
  if ((savedPool || newPoolOpen) && draft) return <section className="tt-routing-workspace tt-model-catalog-detail tt-aggregate-detail" hidden={!active} aria-label={t('hub.tab.aggregate')}>
    {phone ? active && <MobileSubPage title={title} search={false} onBack={requestId ? () => openSection('requests') : closeEditor} manageHistory={newPoolOpen}>{editor}</MobileSubPage> : <><header className="tt-pagehead"><BackButton onClick={closeEditor} /><h2>{title}</h2></header>{editor}</>}
  </section>
  return <section className="tt-routing-workspace" hidden={!active} aria-label={t('hub.tab.aggregate')}>
    <div className="tt-routing-main">
      <header className="tt-pagehead"><h2>{t('hub.tab.aggregate')}</h2></header><div className="tt-model-hub-actions"><Input prefix={<SearchIcon />} aria-label={t('modelInteraction.poolSearch')} placeholder={t('modelInteraction.poolSearch')} value={query} onChange={event=>setQuery(event.target.value)} /><Button type="primary" icon={<PlusIcon />} disabled={!catalog || busy} onClick={create}>{t(drafts['@new'] ? 'pool.resumeCreate' : 'pool.create')}</Button></div>
      {active && error && <Alert role="alert" type="error" message={t(error)} action={<Button onClick={retry}>{t('agent.retry')}</Button>} />}
      {!catalog ? <Spin /> : !pools.length ? <p className="agent-settings-hint">{t('pool.empty')}</p> : <div className="tt-model-connections">
        {pools.filter(model=>(model.name+' '+model.id).toLowerCase().includes(query.trim().toLowerCase())).map(model => card(model))}
      </div>}{!!pools.length && !pools.some(model=>(model.name+' '+model.id).toLowerCase().includes(query.trim().toLowerCase())) && <p className="agent-settings-hint">{t('hub.directory.noMatches')}</p>}
    </div>
  </section>
}
