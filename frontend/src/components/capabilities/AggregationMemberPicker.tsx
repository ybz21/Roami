import { useState } from 'react'
import { Alert, Button, Checkbox, Input, Pagination, Select, Spin } from 'antd'
import { SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCatalog } from './model-hub-api'
import { advertisedFree, useSourceDirectory } from './source-model-directory'
import { candidateIdentity, MAX_AGGREGATE_MEMBERS } from './routing-preview'

export default function AggregationMemberPicker({ model, original, catalog, active, disabled, onChange, onSource }: {
  model: CatalogModel; original: string | null; catalog: ModelCatalog; active: boolean; disabled: boolean
  onChange: (patch: Partial<CatalogModel>) => void; onSource: (source: string) => void
}) {
  const { t, locale } = useI18n()
  const [source, setSource] = useState(model.candidates[0]?.sourceId || ''), [query, setQuery] = useState(''), [onlyFree, setOnlyFree] = useState(false), [selectedOnly, setSelectedOnly] = useState(false), [page, setPage] = useState(1)
  const directory = useSourceDirectory(catalog, source, active && source !== '@group')
  const pools = catalog.models.filter(row => row.aggregate && row.id !== model.id && row.id !== original)
  const rows = source === '@group' ? pools.map(row => ({ id: row.id, name: row.name })) : [...new Set([
    ...catalog.models.filter(row => !row.aggregate).flatMap(row => row.candidates.filter(row => row.sourceId === source).map(row => row.model)),
    ...model.candidates.filter(row => row.sourceId === source).map(row => row.model),
    ...(directory.value?.models || []).map(row => row.id),
  ])].map(id => directory.value?.models.find(row => row.id === id) || { id })
  const selected = new Set(model.candidates.filter(row => row.sourceId === source).map(row => row.model))
  const visible = rows.filter(row => (!onlyFree || advertisedFree(row)) && (!selectedOnly || selected.has(row.id)) && (row.id + ' ' + (row.name || '')).toLowerCase().includes(query.toLowerCase()))
  const additions = visible.filter(row => !selected.has(row.id)), all = !!visible.length && !additions.length
  const overLimit = model.candidates.length + additions.length > MAX_AGGREGATE_MEMBERS
  const currentPage = Math.min(page, Math.max(1, Math.ceil(visible.length / 30)))
  const select = (ids: string[], enabled: boolean) => {
    if (disabled) return
    const candidates = enabled ? [...model.candidates, ...ids.filter(id => !selected.has(id)).map(model => ({ sourceId: source, model }))] : model.candidates.filter(row => row.sourceId !== source || !ids.includes(row.model))
    if (candidates.length > MAX_AGGREGATE_MEMBERS) return
    const keys = new Set(candidates.map(candidateIdentity))
    onChange({ candidates, weights: Object.fromEntries(Object.entries(model.weights || {}).filter(([key]) => keys.has(key))),
      ...(!model.candidates.length && candidates.length ? { protocol: catalog.sources.find(row => row.id === source)?.protocol || pools.find(row => row.id === candidates[0].model)?.protocol || model.protocol } : {}),
    })
  }
  const count = (value: number) => new Intl.NumberFormat(locale).format(value)
  return <section className="tt-aggregate-members" aria-label={t('pool.candidateMembers')}>
    <label className="agent-settings-field tt-aggregate-source">{t('hub.source')}<Select aria-label={t('pool.source')} virtual={false} placeholder={t('pool.selectSource')} value={source || undefined} disabled={disabled} options={[...catalog.sources.map(row => ({ value: row.id, label: row.name })), ...(pools.length ? [{ value: '@group', label: t('pool.groups') }] : [])]} onChange={value => { setSource(value); setQuery(''); setOnlyFree(false); setSelectedOnly(false); setPage(1) }} /></label>
    {!source ? <p className="agent-settings-hint">{t('pool.selectSource')}</p> : <div className="tt-model-directory">
      <div className="tt-model-directory-heading"><h3>{t('pool.model')}</h3><span role="status">{t('pool.sourceCount', { count: count(selected.size) })}</span></div>
      <Input aria-label={t('hub.directory.search')} placeholder={t('hub.directory.search')} prefix={<SearchIcon />} onPressEnter={event => event.preventDefault()} allowClear value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} />
      <div className="tt-aggregate-model-filters"><Checkbox disabled={disabled || !visible.length || (!all && overLimit)} checked={all} indeterminate={!all && visible.some(row => selected.has(row.id))} onChange={event => select(visible.map(row => row.id), event.target.checked)}>{t(query || onlyFree || selectedOnly ? 'hub.directory.selectMatches' : 'pool.selectAll')}</Checkbox>
        {source !== '@group' && <Checkbox checked={onlyFree} onChange={event => { setOnlyFree(event.target.checked); setPage(1) }}>{t('directory.free')}</Checkbox>}
        <Checkbox checked={selectedOnly} onChange={event => { setSelectedOnly(event.target.checked); setPage(1) }}>{t('pool.selectedOnly')}</Checkbox>
      </div>
      {overLimit && <p className="agent-settings-hint">{t('pool.bulkLimit', { count: MAX_AGGREGATE_MEMBERS })}</p>}
      {directory.loading && <Spin size="small" />}
      {source !== '@group' && directory.value?.error && <Alert type="warning" message={t('directory.loadFailed')} action={<Button onClick={directory.retry}>{t('agent.retry')}</Button>} />}
      <div className="tt-model-directory-list">{visible.slice((currentPage - 1) * 30, currentPage * 30).map(row => <div className="tt-model-directory-row" key={row.id}><Checkbox checked={selected.has(row.id)} disabled={disabled || (!selected.has(row.id) && model.candidates.length >= MAX_AGGREGATE_MEMBERS)} onChange={event => select([row.id], event.target.checked)}><span>{row.id}</span>{row.name && row.name !== row.id && <small>{row.name}</small>}</Checkbox></div>)}</div>
      {!directory.loading && !visible.length && <p className="agent-settings-hint">{t(rows.length ? 'hub.directory.noMatches' : 'hub.directory.empty')}{!rows.length && source !== '@group' && <> <button type="button" className="tt-act" onClick={() => onSource(source)}>{t('hub.configure')}</button></>}</p>}
      {visible.length > 30 && <Pagination size="small" current={currentPage} total={visible.length} pageSize={30} showSizeChanger={false} onChange={setPage} />}
      {onlyFree && <p className="agent-settings-hint">{t('pool.freeFilterHint')}</p>}
    </div>}
  </section>
}
