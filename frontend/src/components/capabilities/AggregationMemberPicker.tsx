import { useMemo, useState } from 'react'
import { Alert, Button, Checkbox, Input, Pagination, Select } from './model-controls'
import { SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCatalog, ModelCandidate } from './model-hub-api'
import { configuredSourceModelIds } from './configured-source-models'
import { candidateIdentity, MAX_AGGREGATE_MEMBERS } from './routing-preview'
export default function AggregationMemberPicker({ model, original, catalog, disabled, onChange, onSource }: {
  model: CatalogModel; original: string | null; catalog: ModelCatalog; disabled: boolean
  onChange: (patch: Partial<CatalogModel>) => void; onSource: (source: string) => void
}) {
  const { t, locale } = useI18n()
  const [source, setSource] = useState(model.candidates[0]?.sourceId || (catalog.sources.length === 1 ? catalog.sources[0].id : '')), [query, setQuery] = useState(''), [page, setPage] = useState(1)
  const grouped = source === '@group', selectedView = source === '@selected'
  const configured = useMemo(() => new Map(catalog.sources.map(row => [row.id, new Set(configuredSourceModelIds(catalog.models, row.id))])), [catalog.sources, catalog.models])
  const missing = model.candidates.filter(row => row.sourceId !== '@group' && !configured.get(row.sourceId)?.has(row.model))
  const pools = catalog.models.filter(row => row.aggregate && row.id !== model.id && row.id !== original)
  const rows = selectedView ? model.candidates.map(row => ({ id: row.model, sourceId: row.sourceId, name: '' })) : grouped ? pools.map(row => ({ id: row.id, sourceId: source, name: row.name })) : [...(configured.get(source) || [])].map(id => ({ id, sourceId: source, name: '' }))
  const selected = new Set(model.candidates.map(candidateIdentity))
  const key = (row: { id: string; sourceId: string }) => candidateIdentity({ sourceId: row.sourceId, model: row.id })
  const visible = rows.filter(row => (row.id + ' ' + (row.name || '')).toLowerCase().includes(query.toLowerCase()))
  const additions = visible.filter(row => !selected.has(key(row))), all = !!visible.length && !additions.length
  const overLimit = model.candidates.length + additions.length > MAX_AGGREGATE_MEMBERS
  const currentPage = Math.min(page, Math.max(1, Math.ceil(visible.length / 30)))
  const select = (values: ModelCandidate[], enabled: boolean) => {
    if (disabled) return
    const keys = new Set(values.map(candidateIdentity))
    const candidates = enabled ? [...model.candidates, ...values.filter(row => !selected.has(candidateIdentity(row)))] : model.candidates.filter(row => !keys.has(candidateIdentity(row)))
    if (candidates.length > MAX_AGGREGATE_MEMBERS) return
    const remaining = new Set(candidates.map(candidateIdentity))
    onChange({ candidates, weights: Object.fromEntries(Object.entries(model.weights || {}).filter(([key]) => remaining.has(key))),
      ...(!model.candidates.length && candidates.length ? { protocol: catalog.sources.find(row => row.id === candidates[0].sourceId)?.protocol || pools.find(row => row.id === candidates[0].model)?.protocol || model.protocol } : {}),
    })
  }
  const count = (value: number) => new Intl.NumberFormat(locale).format(value)
  return <section className="tt-aggregate-members" aria-label={t('pool.candidateMembers')}>
    {!!missing.length && <Alert type="warning" message={t('orchestration.unconfiguredMembers', { count: count(missing.length) })} />}
    <div className="tt-member-source-toolbar"><label className="agent-settings-field tt-aggregate-source">{t('hub.source')}<Select aria-label={t('pool.source')} placeholder={t('pool.selectSource')} value={source || undefined} disabled={disabled} options={[...catalog.sources.map(row => ({ value: row.id, label: row.name })), ...(pools.length ? [{ value: '@group', label: t('pool.groups') }] : []), ...(selectedView ? [{ value: '@selected', label: t('orchestration.allSelected', { count: count(model.candidates.length) }) }] : [])]} onChange={value => { setSource(value); setQuery(''); setPage(1) }} /></label>{!!model.candidates.length && !selectedView && <Button onClick={() => { setSource('@selected'); setQuery(''); setPage(1) }}>{t('orchestration.reviewSelected')}</Button>}</div>
    {!!source && <div className="tt-model-directory">
      <div className="tt-model-directory-heading"><h3>{t(selectedView ? 'orchestration.reviewSelected' : 'pool.model')}</h3>{!selectedView && <span role="status">{t('pool.sourceCount', { count: count(model.candidates.filter(row => row.sourceId === source && configured.get(source)?.has(row.model)).length) })}</span>}</div>
      <Input aria-label={t('hub.directory.search')} placeholder={t('hub.directory.search')} prefix={<SearchIcon />} onPressEnter={event => event.preventDefault()} value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} />
      <div className="tt-aggregate-model-filters"><Checkbox disabled={disabled || !visible.length || (!all && overLimit)} checked={all} indeterminate={!all && visible.some(row => selected.has(key(row)))} onChange={event => select(visible.map(row => ({ sourceId: row.sourceId, model: row.id })), event.target.checked)}>{t(query ? 'hub.directory.selectMatches' : selectedView ? 'orchestration.selectAllMembers' : 'pool.selectAll')}</Checkbox>
      </div>
      {overLimit && <p className="agent-settings-hint">{t('pool.bulkLimit', { count: MAX_AGGREGATE_MEMBERS })}</p>}
      <div className="tt-model-directory-list">{visible.slice((currentPage - 1) * 30, currentPage * 30).map(row => <div className="tt-model-directory-row" key={key(row)}><Checkbox checked={selected.has(key(row))} disabled={disabled || (!selected.has(key(row)) && model.candidates.length >= MAX_AGGREGATE_MEMBERS)} onChange={event => select([{ sourceId: row.sourceId, model: row.id }], event.target.checked)}><span>{row.id}</span>{selectedView ? <><small>{catalog.sources.find(source => source.id === row.sourceId)?.name || t('pool.groups')}</small>{row.sourceId !== '@group' && !configured.get(row.sourceId)?.has(row.id) && <small className="tt-model-source-warning">{t('orchestration.sourceNotEnabled')}</small>}</> : row.name && row.name !== row.id && <small>{row.name}</small>}</Checkbox></div>)}</div>
      {!visible.length && <p className="agent-settings-hint">{t(selectedView ? 'pool.previewEmpty' : rows.length ? 'hub.directory.noMatches' : 'orchestration.noConfiguredModels')}{!rows.length && !grouped && !selectedView && <> <button type="button" className="tt-act" onClick={() => onSource(source)}>{t('hub.configure')}</button></>}</p>}
      {visible.length > 30 && <Pagination current={currentPage} total={visible.length} pageSize={30} onChange={setPage} />}
    </div>}
  </section>
}
