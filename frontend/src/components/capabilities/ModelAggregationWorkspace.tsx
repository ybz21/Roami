import AggregationPoolCard from './AggregationPoolCard'
import AggregationEditor from './AggregationEditor'
import { MAX_AGGREGATE_MEMBERS } from './routing-preview'
import { useState } from 'react'
import { Alert, App, Button, Spin } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { PlusIcon } from '../../icons'
import BackButton from '../BackButton'
import MobileSubPage from '../MobileSubPage'
import type { CatalogModel, ModelCatalog, ModelCandidate } from './model-hub-api'
import './model-routing.css'
const identity = (candidate: ModelCandidate) => candidate.sourceId + '/' + candidate.model
const emptyPool = (): CatalogModel => ({ id: globalThis.crypto?.randomUUID?.() || 'pool-' + Date.now().toString(36), name: '', aggregate: true, enabled: true, freeOnly: true, allowPlan: false, protocol: 'openai-completions', strategy: 'smart', candidates: [], cooldownSeconds: 60, onLimit: true, onExhausted: true, minContext: 0, weights: {} })
export default function ModelAggregationWorkspace({ active, catalog, busy, error, save, retry, onSource }: { active: boolean; catalog: ModelCatalog | null; busy: boolean; error: string; save: (value: ModelCatalog) => Promise<boolean>; retry: () => void; onSource: (source: string) => void }) {
  const { t } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const [drafts, setDrafts] = useState<Record<string, CatalogModel>>({}), [original, setOriginal] = useState<string | null>(null), [editorOpen, setEditorOpen] = useState(false)
  const key = original || '@new', draft = drafts[key] || null
  const pools = catalog?.models.filter(model => model.aggregate) || []
  const edit = (model: CatalogModel | null) => {
    const id = model?.id || '@new'
    setDrafts(previous => previous[id] ? previous : { ...previous, [id]: model ? { ...model, candidates: model.candidates.map(candidate => ({ ...candidate })), weights: model.weights ? { ...model.weights } : undefined } : emptyPool() })
    setOriginal(model?.id || null)
    setEditorOpen(true)
  }
  const cancel = () => { setDrafts(previous => { const next = { ...previous }; delete next[key]; return next }); setEditorOpen(false) }
  const patch = (value: Partial<CatalogModel>) => setDrafts(previous => previous[key] ? { ...previous, [key]: { ...previous[key], ...value } } : previous)
  const sources = catalog?.sources || []
  const valid = !!draft && !!draft.name.trim() && draft.id !== 'roami-default' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/.test(draft.id) && draft.candidates.length > 0 && draft.candidates.length <= MAX_AGGREGATE_MEMBERS && (draft.aliases?.length || 0) + (original && draft.id !== original && !draft.aliases?.includes(draft.id) ? 1 : 0) <= 32 && draft.candidates.every(candidate => candidate.model && (candidate.sourceId === '@group' || sources.some(source => source.id === candidate.sourceId)) && Number.isInteger(draft.weights?.[identity(candidate)] ?? 1) && (draft.weights?.[identity(candidate)] ?? 1) >= 1 && (draft.weights?.[identity(candidate)] ?? 1) <= 1000) && !catalog?.models.some(model => (model.id === draft.id || model.aliases?.includes(draft.id)) && model.id !== original)
  const submit = async () => { if (!catalog || !draft || !valid || busy) return; const next = { ...draft, name: draft.name.trim(), aliases: [...new Set([...(draft.aliases || []), ...(original && original !== draft.id ? [original] : [])])].filter(id => id !== draft.id) }; if (await save({ ...catalog, models: original ? catalog.models.map(model => model.id === original ? next : model) : [...catalog.models, next] })) { cancel(); message.success(t('pool.saved')) } }
  const card = (model: CatalogModel) => <AggregationPoolCard key={model.id} model={model} disabled={busy} unsaved={!!drafts[model.id] && JSON.stringify(drafts[model.id]) !== JSON.stringify(model)} onOpen={() => edit(model)} />
  const remove = async () => { if (!catalog || !original || busy) return false; const saved = await save({ ...catalog, models: catalog.models.filter(row => row.id !== original) }); if (saved) cancel(); return saved }
  const editor = draft && catalog && <AggregationEditor key={key} model={draft} original={original} catalog={catalog} active={active} busy={busy} valid={valid} error={error} retry={retry} onChange={patch} onSave={() => void submit()} onCancel={cancel} onDelete={remove} onSource={onSource} />
  const title = original ? pools.find(row => row.id === original)?.name || t('pool.edit') : t('pool.create')
  if (editorOpen && draft) return <section className="tt-routing-workspace tt-model-catalog-detail tt-aggregate-detail" hidden={!active} aria-label={t('hub.tab.aggregate')}>
    {phone ? active && <MobileSubPage title={title} search={false} onBack={() => setEditorOpen(false)}>{editor}</MobileSubPage> : <><header className="tt-pagehead"><BackButton onClick={() => setEditorOpen(false)} /><h2>{title}</h2></header>{editor}</>}
  </section>
  return <section className="tt-routing-workspace" hidden={!active} aria-label={t('hub.tab.aggregate')}>
    <div className="tt-routing-main">
      <div className="tt-model-hub-actions"><p className="agent-settings-hint">{t('pool.entryHint')}</p><Button type="primary" icon={<PlusIcon />} disabled={!catalog || busy} onClick={() => edit(null)}>{t(drafts['@new'] ? 'pool.resumeCreate' : 'pool.create')}</Button></div>
      {active && error && !draft && <Alert role="alert" type="error" message={t(error)} action={<Button onClick={retry}>{t('agent.retry')}</Button>} />}
      {!catalog ? <Spin /> : !pools.length ? <p className="agent-settings-hint">{t('pool.empty')}</p> : <div className="tt-model-connections">
        {pools.map(model => card(model))}
      </div>}
    </div>
  </section>
}
