import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Tabs } from 'antd'
import { Alert, Button, Input, Pagination, Select, Spin } from './model-controls'
import { configuredSourceModels } from './configured-source-models'
import { CopyIcon, ChevronRight, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCatalog, ModelSource } from './model-hub-api'
import { advertisedFree, useSourceDirectory, type SourceModelDetail } from './source-model-directory'
import GatewayInspector from './GatewayInspector'
import './gateway-model-directory.css'

type DirectoryEntry = { id: string; name: string; kind: string; sourceId?: string; sourceName: string; detail: SourceModelDetail; gateway?: CatalogModel; unavailable?: boolean }
const entryState = (row: DirectoryEntry) => !row.gateway ? 'gatewayWorkspace.upstream' : row.gateway.enabled === false || row.unavailable ? 'hub.gateway.disabled' : 'modelInteraction.configured'
function Capabilities({ detail }: { detail: SourceModelDetail }) {
  const { t } = useI18n()
  const keys = [['tools', detail.tools], ['reasoning', detail.reasoning], ['structuredOutput', detail.structuredOutput], ...['image', 'audio', 'video'].map(key => [key, detail.inputModalities?.includes(key)])].filter(([, supported]) => supported).map(([key]) => String(key))
  return <div className="tt-directory-capabilities">{keys.map(key => <span className="tt-gateway-pill" key={key}>{t('directory.' + key)}</span>)}{advertisedFree(detail) && <span className="tt-gateway-pill">{t('directory.free')}</span>}{!keys.length && !advertisedFree(detail) && <small>{t('directory.unknownCapabilities')}</small>}</div>
}
function ModelRow({ row, onSelect }: { row: DirectoryEntry; onSelect: (row: DirectoryEntry, opener: HTMLElement) => void }) {
  const { t, locale } = useI18n(), { message } = App.useApp()
  const callable = !!row.gateway && row.gateway.enabled !== false && !row.unavailable
  return <article className="tt-gateway-model"><button type="button" className="tt-directory-model-name" onClick={event => onSelect(row, event.currentTarget)}><strong>{row.name || row.id}</strong><code>{t(row.gateway ? 'modelIdentity.callId' : 'modelIdentity.upstreamId', { model: row.id })}</code><small className={'tt-gateway-status' + (callable ? ' is-enabled' : '')}>{t(entryState(row))}</small></button><span className="tt-directory-model-source">{row.sourceName}</span><span className="tt-directory-model-context">{row.detail.context ? new Intl.NumberFormat(locale).format(row.detail.context) : t('directory.unknown')}</span><Capabilities detail={row.detail} /><Button type="text" icon={callable ? <CopyIcon /> : <ChevronRight />} aria-label={t(callable ? 'gatewayWorkspace.copyModel' : 'gatewayWorkspace.modelDetails', { model: row.id })} onClick={async event => { if (!callable) { onSelect(row, event.currentTarget); return } try { await navigator.clipboard.writeText(row.id); message.success(t('common.copied')) } catch { message.error(t('gatewayWorkspace.copyFailed')) } }} /></article>
}
function SourceModels({ active, catalog, source, query, capability, kind, onSource, onSelect, onCount }: { active: boolean; catalog: ModelCatalog; source: ModelSource; query: string; capability: string; kind: string; onSource: (id: string) => void; onSelect: (row: DirectoryEntry, opener: HTMLElement) => void; onCount: (id: string, count: number) => void }) {
  const { t } = useI18n(), directory = useSourceDirectory(catalog, source.id, active)
  const [page, setPage] = useState({ key: '', number: 1 })
  const saved = configuredSourceModels(catalog.models, source.id)
  const metadata = new Map((directory.value?.models || []).map(row => [row.id, row]))
  const rows: DirectoryEntry[] = [
    ...saved.map(model => ({ id: model.id, name: model.name, kind: 'native', sourceId: source.id, sourceName: source.name, gateway: model, unavailable: source.pluginDesktopUnavailable, detail: metadata.get(model.candidates[0].model) || { id: model.candidates[0].model } })),
    ...(directory.value?.models || []).filter(row => !saved.some(model => model.candidates[0].model === row.id)).map(detail => ({ id: detail.id, name: detail.name || detail.id, kind: 'upstream', sourceId: source.id, sourceName: source.name, detail })),
  ].filter(row => {
    const detail = row.detail
    return (!query || [row.id, row.name, source.name, detail.id].some(value => value.toLowerCase().includes(query.toLowerCase()))) && (kind === 'all' || kind === row.kind) && (!capability || (capability === 'free' ? advertisedFree(detail) : capability === 'tools' ? detail.tools === true : capability === 'reasoning' ? detail.reasoning === true : capability === 'structuredOutput' ? detail.structuredOutput === true : detail.inputModalities?.includes(capability)))
  })
  useEffect(() => { if (!directory.loading) onCount(source.id, rows.length) }, [source.id, directory.loading, rows.length, onCount])
  const key = query + '/' + capability + '/' + kind, current = Math.min(page.key === key ? page.number : 1, Math.max(1, Math.ceil(rows.length / 30)))
  if (!rows.length && !directory.loading && !directory.value?.error) return null
  return <section className="tt-gateway-directory-source" aria-label={source.name}><div className="tt-directory-source-head"><h3>{source.name}</h3>{!!rows.length && <span>{t('directory.count', { count: rows.length })}</span>}<Button type="text" onClick={() => onSource(source.id)}>{t('gatewayWorkspace.viewSource')}</Button></div>
    {directory.loading && <Spin size="small" />}
    {directory.value?.error && <Alert type="warning" message={t('directory.loadFailed')} action={<Button onClick={directory.retry}>{t('agent.retry')}</Button>} />}
    <div className="tt-gateway-model-list">{rows.slice((current - 1) * 30, current * 30).map(row => <ModelRow key={row.kind + ':' + row.id} row={row} onSelect={onSelect} />)}</div>
    {rows.length > 30 && <Pagination size="small" current={current} total={rows.length} pageSize={30} showSizeChanger={false} onChange={number => setPage({ key, number })} />}
  </section>
}
export default function GatewayModelDirectory({ active = true, catalog, onSource, onPool }: { active?: boolean; catalog: ModelCatalog; onSource: (id: string) => void; onPool?: (id: string) => void }) {
  const { t, locale } = useI18n(), { message } = App.useApp()
  const [source, setSource] = useState(''), [query, setQuery] = useState(''), [capability, setCapability] = useState(''), [kind, setKind] = useState('native'), [selected, setSelected] = useState<DirectoryEntry | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  const filterKey = [catalog.revision, source, query, capability, kind].join('\0')
  const [counts, setCounts] = useState<{ key: string; sources: Record<string, number> }>({ key: '', sources: {} })
  const count = useCallback((id: string, value: number) => setCounts(previous => previous.key === filterKey && previous.sources[id] === value ? previous : { key: filterKey, sources: { ...(previous.key === filterKey ? previous.sources : {}), [id]: value } }), [filterKey])
  useEffect(() => { if (!active) setSelected(null) }, [active])
  useEffect(() => { if (selected && (selected.sourceId && !catalog.sources.some(row => row.id === selected.sourceId) || selected.gateway && !catalog.models.some(row => row.id === selected.gateway!.id))) setSelected(null) }, [catalog, selected])
  const close = () => { setSelected(null); setTimeout(() => opener.current?.focus({ preventScroll: true }), 0) }
  const select = (row: DirectoryEntry, element: HTMLElement) => { opener.current = element; setSelected(row) }
  const sources = catalog.sources.filter(row => !source || row.id === source)
  const pools = source || capability || kind !== 'all' && kind !== 'pool' ? [] : catalog.models.filter(row => row.aggregate && (!query || (row.name + ' ' + row.id).toLowerCase().includes(query.toLowerCase())))
  const ready = kind === 'pool' || counts.key === filterKey && sources.every(row => counts.sources[row.id] !== undefined)
  const hasRows = pools.length > 0 || kind !== 'pool' && counts.key === filterKey && Object.values(counts.sources).some(value => value > 0)
  const number = (value?: number) => value ? new Intl.NumberFormat(locale).format(value) : t('directory.unknown')
  const price = (value?: number) => value === undefined ? t('directory.unknown') : new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(value)
  const selectedGateway = selected?.gateway ? catalog.models.find(row => row.id === selected.gateway!.id) : undefined
  const canCopy = !!selectedGateway && selectedGateway.enabled !== false && !selected?.unavailable
  return <div className="tt-gateway-layout"><section className="tt-gateway-scroll tt-gateway-directory" aria-label={t('directory.title')}>
    <Tabs className="tt-directory-tabs" activeKey={kind} onChange={setKind} items={['native', 'pool', 'upstream'].map(key => ({ key, label: t('gatewayWorkspace.kind.' + key) }))} />
    <div className="tt-directory-filters"><Input prefix={<SearchIcon />} aria-label={t('directory.search')} placeholder={t('directory.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear /><Select<string> aria-label={t('hub.source')} value={source} options={[{ value: '', label: t('monitor.allSources') }, ...catalog.sources.map(row => ({ value: row.id, label: row.name }))]} onChange={setSource} /><Select<string> aria-label={t('directory.capability')} value={capability} options={['', 'free', 'tools', 'reasoning', 'structuredOutput', 'image', 'audio', 'video'].map(value => ({ value, label: t(value ? 'directory.' + value : 'directory.allCapabilities') }))} onChange={setCapability} /></div>
    {!!pools.length && <section className="tt-directory-groups"><div className="tt-directory-source-head"><h3>{t('pool.groups')}</h3></div>{pools.map(gateway => <ModelRow key={gateway.id} row={{ id: gateway.id, name: gateway.name, gateway, kind: 'pool', sourceName: t('gatewayWorkspace.kind.pool'), detail: { id: gateway.id } }} onSelect={select} />)}</section>}
    {kind !== 'pool' && sources.map(row => <SourceModels key={row.id} active={active} catalog={catalog} source={row} query={query} capability={capability} kind={kind} onSource={onSource} onSelect={select} onCount={count} />)}
    {ready && !hasRows && <p className="tt-gateway-empty">{t(catalog.sources.length || catalog.models.length ? 'directory.noMatches' : 'hub.empty.connections')}</p>}
  </section>{active && selected && <GatewayInspector title={t('gatewayWorkspace.modelDetails', { model: selected.id })} onClose={close}><div className="tt-gateway-editor-scroll"><h3 className="tt-gateway-model-title">{selected.name || selected.id}</h3><span className={'tt-gateway-status' + (canCopy ? ' is-enabled' : '')}>{t(entryState({ ...selected, gateway: selectedGateway }))}</span><dl className="tt-gateway-model-facts"><div><dt>{t('hub.source')}</dt><dd>{selected.sourceName}</dd></div><div><dt>{t('gatewayWorkspace.kind')}</dt><dd>{t('gatewayWorkspace.kind.' + selected.kind)}</dd></div>{selectedGateway && <div><dt>{t('gatewayWorkspace.gatewayName')}</dt><dd><code>{selectedGateway.id}</code></dd></div>}{selected.kind === 'pool' && selectedGateway ? <><div><dt>{t('pool.strategy')}</dt><dd>{t('pool.strategy.' + selectedGateway.strategy)}</dd></div><div><dt>{t('pool.members')}</dt><dd>{t('pool.memberCount', { count: selectedGateway.candidates.length })}</dd></div></> : <div><dt>{t('gatewayWorkspace.upstreamId')}</dt><dd><code>{selected.detail.id}</code></dd></div>}<div><dt>{t('directory.context')}</dt><dd>{number(selected.detail.context)}</dd></div><div><dt>{t('directory.output')}</dt><dd>{number(selected.detail.output)}</dd></div></dl><Capabilities detail={selected.detail} />{selected.kind === 'upstream' && <p className="tt-gateway-notice">{t('gatewayWorkspace.upstreamHint')}</p>}{selected.kind !== 'pool' && <details className="tt-gateway-published-price"><summary>{t('gatewayWorkspace.publishedPrice')}</summary><p>{t('gatewayWorkspace.publishedPriceHint')}</p><dl className="tt-gateway-model-facts"><div><dt>{t('directory.price')}</dt><dd>{price(selected.detail.inputPrice)} / {price(selected.detail.outputPrice)}</dd></div></dl></details>}</div><footer className="tt-gateway-editor-footer">{(selected.sourceId || onPool) && <Button onClick={() => { close(); if (selected.sourceId) onSource(selected.sourceId); else onPool?.(selected.id) }}>{t(selected.sourceId ? 'gatewayWorkspace.viewSource' : 'gatewayWorkspace.viewPool')}</Button>}{canCopy && <Button type="primary" icon={<CopyIcon />} onClick={async () => { try { await navigator.clipboard.writeText(selected.id); message.success(t('common.copied')) } catch { message.error(t('gatewayWorkspace.copyFailed')) } }}>{t('gatewayWorkspace.copyModel', { model: selected.id })}</Button>}</footer></GatewayInspector>}</div>
}
