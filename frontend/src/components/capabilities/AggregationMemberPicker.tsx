import { useMemo, useState } from 'react'
import { Button, Checkbox, Input, Pagination, Spin } from './model-controls'
import { CloseIcon, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCatalog, ModelCandidate } from './model-hub-api'
import { configuredSourceModelIds } from './configured-source-models'
import { candidateIdentity, MAX_AGGREGATE_MEMBERS } from './routing-preview'
import { useAgentData } from '../agent/useAgentData'
import type { GatewayModelCatalog } from './gateway-model-catalog'

export default function AggregationMemberPicker({ model, original, catalog, active, disabled, onChange, onSource }: {
  model: CatalogModel; original: string | null; catalog: ModelCatalog; active: boolean; disabled: boolean
  onChange: (patch: Partial<CatalogModel>) => void; onSource: (source: string) => void
}) {
  const { t, locale } = useI18n()
  const pools = catalog.models.filter(row => row.aggregate && row.id !== model.id && row.id !== original)
  const sources = [...catalog.sources.map(row => ({ id: row.id, name: row.name })), ...(pools.length ? [{ id: '@group', name: t('pool.groups') }] : [])]
  const [sourceId, setSource] = useState(model.candidates[0]?.sourceId || sources[0]?.id || '')
  const [query, setQuery] = useState(''), [page, setPage] = useState(1)
  const [freeOnly, setFreeOnly] = useState(false)
  const freeDirectory = useAgentData<GatewayModelCatalog>(freeOnly ? '/agent/model-gateway/models?free=true&revision=' + encodeURIComponent(catalog.revision) : null, 30000, 0, 'GET', active)
  const free = useMemo(() => new Set((freeDirectory.value?.models || [])
    .filter(row => row.configured && row.enabled)
    .flatMap(row => row.kind === 'aggregate' ? ['@group/' + row.id] : (row.candidates || []).slice(0, 1).map(candidateIdentity))), [freeDirectory.value])
  const source = sources.find(row => row.id === sourceId) || sources[0]
  const grouped = source?.id === '@group'
  const configured = useMemo(() => new Map(catalog.sources.map(row => [row.id, new Set(configuredSourceModelIds(catalog.models, row.id))])), [catalog.sources, catalog.models])
  const missing = model.candidates.filter(row => row.sourceId !== '@group' && !configured.get(row.sourceId)?.has(row.model))
  const rows = grouped ? pools.map(row => ({ id: row.id, sourceId: '@group', name: row.name })) : [...(configured.get(source?.id || '') || [])].map(id => ({ id, sourceId: source!.id, name: '' }))
  const selected = new Set(model.candidates.map(candidateIdentity))
  const key = (row: { id: string; sourceId: string }) => candidateIdentity({ sourceId: row.sourceId, model: row.id })
  const visible = rows.filter(row => (!freeOnly || free.has(key(row))) && (row.id + ' ' + row.name).toLowerCase().includes(query.trim().toLowerCase()))
  const additions = visible.filter(row => !selected.has(key(row))), all = !!visible.length && !additions.length
  const overLimit = model.candidates.length + additions.length > MAX_AGGREGATE_MEMBERS
  const currentPage = Math.min(page, Math.max(1, Math.ceil(visible.length / 30)))
  const count = (value: number) => new Intl.NumberFormat(locale).format(value)
  const sourceName = (id: string) => sources.find(row => row.id === id)?.name || id
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
  return <section className="tt-aggregate-members" aria-label={t('pool.candidateMembers')}>
    <div className="tt-member-pool">
      <div className="tt-member-picker-heading"><h3>{t('orchestration.selectedPool')}</h3><span role="status">{count(model.candidates.length)} / {count(MAX_AGGREGATE_MEMBERS)}</span>{!!missing.length && <span className="tt-member-pool-warning" role="status">{t('orchestration.unconfiguredCount', { count: count(missing.length) })}</span>}</div>
      {model.candidates.length ? <ul className="tt-member-pool-list" aria-label={t('orchestration.selectedPool')}>{model.candidates.map(row => {
        const unconfigured = row.sourceId !== '@group' && !configured.get(row.sourceId)?.has(row.model)
        return <li key={candidateIdentity(row)} data-unconfigured={unconfigured || undefined}><span><strong>{row.model}</strong><small>{sourceName(row.sourceId)}{unconfigured && <em>{t('orchestration.sourceNotEnabled')}</em>}</small></span><button type="button" className="tt-act" disabled={disabled} aria-label={t('orchestration.removeMember', { model: row.model, source: sourceName(row.sourceId) })} onClick={() => select([row], false)}><CloseIcon /></button></li>
      })}</ul> : <p className="agent-settings-hint">{t('orchestration.poolEmpty')}</p>}
    </div>
    <div className="tt-member-browser">
      <nav className="tt-member-sources" aria-label={t('pool.source')}>
        <h3>{t('hub.source')}</h3>
        {sources.map(row => {
          const ids = row.id === '@group' ? new Set(pools.map(pool => pool.id)) : configured.get(row.id)
          const selectedCount = model.candidates.filter(candidate => candidate.sourceId === row.id && ids?.has(candidate.model)).length
          return <button type="button" key={row.id} className="tt-member-source-choice" aria-label={row.name} aria-pressed={source?.id === row.id} disabled={disabled} onClick={() => { setSource(row.id); setQuery(''); setPage(1) }}><span>{row.name}</span><small>{count(selectedCount)} / {count(ids?.size || 0)}</small></button>
        })}
        {!sources.length && <p className="agent-settings-hint">{t('pool.selectSource')}</p>}
      </nav>
      <section className="tt-member-models" aria-label={t('pool.model')}>
        {source && <>
          <div className="tt-member-picker-heading"><h3>{source.name}</h3><span role="status">{t('pool.sourceCount', { count: count(rows.filter(row => selected.has(key(row))).length) })}</span></div>
          {(rows.length > 8 || query) && <Input aria-label={t('hub.directory.search')} placeholder={t('hub.directory.search')} prefix={<SearchIcon />} onPressEnter={event => event.preventDefault()} value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} />}
          <div className="tt-member-model-actions">
            <Checkbox disabled={disabled} checked={freeOnly} onChange={event => { setFreeOnly(event.target.checked); setPage(1) }}>{t('pool.filterFree')}</Checkbox>
            {rows.length > 1 && <Checkbox disabled={disabled || !visible.length || (!all && overLimit)} checked={all} indeterminate={!all && visible.some(row => selected.has(key(row)))} onChange={event => select(visible.map(row => ({ sourceId: row.sourceId, model: row.id })), event.target.checked)}>{t(freeOnly ? 'pool.selectFiltered' : query ? 'hub.directory.selectMatches' : 'pool.selectAll')}</Checkbox>}
          </div>
          {overLimit && <p className="agent-settings-hint">{t('pool.bulkLimit', { count: MAX_AGGREGATE_MEMBERS })}</p>}
          <div className="tt-member-model-grid">{visible.slice((currentPage - 1) * 30, currentPage * 30).map(row => <div className="tt-member-model" key={key(row)} data-selected={selected.has(key(row)) || undefined}><Checkbox aria-label={row.id} checked={selected.has(key(row))} disabled={disabled || (!selected.has(key(row)) && model.candidates.length >= MAX_AGGREGATE_MEMBERS)} onChange={event => select([{ sourceId: row.sourceId, model: row.id }], event.target.checked)}><strong>{row.id}</strong>{row.name && row.name !== row.id && <small>{row.name}</small>}</Checkbox></div>)}</div>
          {!visible.length && (freeDirectory.loading ? <Spin size="small" /> : freeDirectory.failed && !freeDirectory.value
            ? <Button onClick={freeDirectory.refresh}>{t('pool.filterFreeRetry')}</Button>
            : <p className="agent-settings-hint">{t(rows.length ? freeOnly && !query ? 'pool.filterFreeEmpty' : 'hub.directory.noMatches' : 'orchestration.noConfiguredModels')}{!rows.length && !grouped && <> <button type="button" className="tt-act" onClick={() => onSource(source.id)}>{t('hub.configure')}</button></>}</p>)}
          {visible.length > 30 && <Pagination current={currentPage} total={visible.length} pageSize={30} onChange={setPage} />}
        </>}
      </section>
    </div>
  </section>
}
