import { useState } from 'react'
import { Alert, Button, Input, Pagination, Select, Spin } from 'antd'
import { SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { ModelCatalog, ModelSource } from './model-hub-api'
import { advertisedFree, useSourceDirectory, type SourceModelDetail } from './source-model-directory'
import './gateway-model-directory.css'

function SourceModels({ catalog, source, query, capability, onSource }: { catalog: ModelCatalog; source: ModelSource; query: string; capability: string; onSource: (id: string) => void }) {
  const { t, locale } = useI18n(), directory = useSourceDirectory(catalog, source.id, true)
  const [page, setPage] = useState({ key: '', number: 1 })
  const saved = catalog.models.filter(row => !row.aggregate).flatMap(row => row.candidates.filter(c => c.sourceId === source.id).map(c => ({ id: c.model, gatewayId: row.id })))
  const models = [...new Map<string, SourceModelDetail>([...saved.map(row => ({ id: row.id })), ...(directory.value?.models || [])].map(row => [row.id, row])).values()]
  const rows = models.filter(row => {
    const matchesQuery = !query || [row.id, row.name].some(value => value?.toLowerCase().includes(query.toLowerCase()))
    const matchesCapability = !capability || (capability === 'free' ? advertisedFree(row) : capability === 'tools' ? row.tools === true : capability === 'reasoning' ? row.reasoning === true : row.inputModalities?.includes(capability))
    return matchesQuery && matchesCapability
  })
  const key = query + '/' + capability, current = Math.min(page.key === key ? page.number : 1, Math.max(1, Math.ceil(rows.length / 30)))
  const count = (value?: number) => value ? new Intl.NumberFormat(locale).format(value) : t('directory.unknown')
  const price = (value?: number) => value === undefined ? t('directory.unknown') : new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(value)
  return <section className="tt-gateway-directory-source" aria-label={source.name}>
    <div className="tt-directory-source-head"><h3>{source.name}</h3>{!!rows.length && <span>{t('directory.count', { count: rows.length })}</span>}<button type="button" className="tt-act" onClick={() => onSource(source.id)}>{t('hub.configure')}</button></div>
    {directory.loading && <Spin size="small" />}
    {directory.value?.error && <Alert type="warning" message={t('directory.loadFailed')} action={<Button onClick={directory.retry}>{t('agent.retry')}</Button>} />}
    {!rows.length && !directory.loading && !directory.value?.error && <p className="agent-settings-hint">{t('directory.noMatches')}</p>}
    <div className="tt-gateway-model-list">{rows.slice((current - 1) * 30, current * 30).map(row => <article className="tt-gateway-model" key={row.id}>
      <div className="tt-directory-model-name"><strong>{row.name || row.id}</strong><code>{row.id}</code>{(row.inputModalities?.length || row.outputModalities?.length) ? <small>{t('directory.inputs')}: {row.inputModalities?.map(value => t('directory.modality.' + value)).join(', ') || t('directory.unknown')} · {t('directory.outputs')}: {row.outputModalities?.map(value => t('directory.modality.' + value)).join(', ') || t('directory.unknown')}</small> : null}<small>{saved.filter(m => m.id === row.id).map(m => m.gatewayId).join(', ') || t('directory.upstreamOnly')}</small></div>
      <div className="tt-directory-capabilities">{[['tools', row.tools], ['reasoning', row.reasoning], ...['image', 'audio', 'video'].map(value => [value, row.inputModalities?.includes(value)])].filter(([, supported]) => supported).map(([value]) => <span key={String(value)}>{t('directory.' + value)}</span>)}{advertisedFree(row) && <span>{t('directory.free')}</span>}{row.tools === undefined && !row.context && !row.inputModalities?.length && <small>{t('directory.unknownCapabilities')}</small>}</div>
      <dl><div><dt>{t('directory.context')}</dt><dd>{count(row.context)}</dd></div><div><dt>{t('directory.output')}</dt><dd>{count(row.output)}</dd></div><div><dt>{t('directory.price')}</dt><dd>{price(row.inputPrice)} / {price(row.outputPrice)}</dd></div></dl>
    </article>)}</div>
    {rows.length > 30 && <Pagination size="small" current={current} total={rows.length} pageSize={30} showSizeChanger={false} onChange={number => setPage({ key, number })} />}
  </section>
}

export default function GatewayModelDirectory({ catalog, onSource }: { catalog: ModelCatalog; onSource: (id: string) => void }) {
  const { t } = useI18n(), [source, setSource] = useState(''), [query, setQuery] = useState(''), [capability, setCapability] = useState('')
  return <section className="tt-gateway-directory" aria-label={t('directory.title')}><h3>{t('directory.title')}</h3><p className="agent-settings-hint">{t('directory.hint')}</p>
    <div className="tt-directory-filters"><Input prefix={<SearchIcon />} aria-label={t('directory.search')} placeholder={t('directory.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear /><Select aria-label={t('hub.source')} value={source} options={[{ value: '', label: t('monitor.allSources') }, ...catalog.sources.map(row => ({ value: row.id, label: row.name }))]} onChange={setSource} /><Select aria-label={t('directory.capability')} value={capability} options={['', 'free', 'tools', 'reasoning', 'image', 'audio', 'video'].map(value => ({ value, label: t(value ? 'directory.' + value : 'directory.allCapabilities') }))} onChange={setCapability} /></div>
    {catalog.models.some(row => row.aggregate) && !source && !capability && <section className="tt-directory-groups"><h3>{t('pool.groups')}</h3>{catalog.models.filter(row => row.aggregate && (!query || (row.name + ' ' + row.id).toLowerCase().includes(query.toLowerCase()))).map(row => <div key={row.id}><strong>{row.name}</strong><code>{row.id}</code><span>{t('pool.strategy.' + row.strategy)}</span><small>{t('pool.memberCount', { count: row.candidates.length })}</small></div>)}</section>}
    {catalog.sources.filter(row => !source || row.id === source).map(row => <SourceModels key={row.id} catalog={catalog} source={row} query={query} capability={capability} onSource={onSource} />)}
    {!catalog.sources.length && <p className="agent-settings-hint">{t('hub.empty.connections')}</p>}
  </section>
}
