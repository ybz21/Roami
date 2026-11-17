import { useEffect, useRef, useState } from 'react'
import { App, Tabs } from 'antd'
import { Alert, Button, Input, Pagination, Select, Spin } from './model-controls'
import { CopyIcon, ChevronRight, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { ModelCatalog, ModelDirectoryEntry } from './model-hub-api'
import { configuredGatewayModels, freeGatewayModel, prioritizeGatewayModels, useGatewayModelCatalog } from './gateway-model-catalog'
import ModelCapabilities from './ModelCapabilities'
import GatewayInspector from './GatewayInspector'
import './gateway-model-directory.css'

type Entry = ModelDirectoryEntry & { sourceName: string; sourceId?: string; unavailable?: boolean }
const rowKey = (row: ModelDirectoryEntry) => (row.configured ? 'configured' : row.candidates?.[0]?.sourceId) + ':' + row.id
const kindOf = (row: ModelDirectoryEntry) => row.configured ? row.kind === 'aggregate' ? 'pool' : 'native' : 'upstream'
const stateOf = (row: ModelDirectoryEntry) => !row.configured ? 'gatewayWorkspace.upstream' : row.enabled ? 'modelInteraction.configured' : 'hub.gateway.disabled'
function ModelRow({ row, users, onSelect }: { row: Entry; users: string[]; onSelect: (row: Entry, opener: HTMLElement) => void }) {
  const { t } = useI18n(), { message } = App.useApp()
  const callable = row.configured && row.enabled && !row.unavailable
  return <article className="tt-gateway-model">
    <button type="button" className="tt-directory-model-name" onClick={event => onSelect(row, event.currentTarget)}><strong>{row.name || row.id}</strong><code>{t(row.configured ? 'modelIdentity.callId' : 'modelIdentity.upstreamId', { model: row.id })}</code><small className={'tt-gateway-status' + (callable ? ' is-enabled' : '')}>{t(stateOf(row))}</small>{!!users.length && <small>{t('gatewayOptions.usedBy')}: {[...new Set(users)].join(', ')}</small>}</button>
    <span className="tt-directory-model-source">{t('hub.source')}: {row.sourceName}</span>
    <ModelCapabilities model={row} />
    <Button type="text" icon={callable ? <CopyIcon /> : <ChevronRight />} aria-label={t(callable ? 'gatewayWorkspace.copyModel' : 'gatewayWorkspace.modelDetails', { model: row.id })} onClick={async event => { if (!callable) { onSelect(row, event.currentTarget); return } try { await navigator.clipboard.writeText(row.id); message.success(t('common.copied')) } catch { message.error(t('gatewayWorkspace.copyFailed')) } }} />
  </article>
}
function ModelGroup({ rows, title, users, onSelect, action }: { rows: Entry[]; title: string; users: (row: Entry) => string[]; onSelect: (row: Entry, opener: HTMLElement) => void; action?: React.ReactNode }) {
  const { t } = useI18n(), [page, setPage] = useState(1)
  if (!rows.length) return null
  const current = Math.min(page, Math.max(1, Math.ceil(rows.length / 30)))
  return <section className="tt-gateway-directory-source" aria-label={title}><div className="tt-directory-source-head"><h3>{title}</h3><span>{t('directory.count', { count: rows.length })}</span>{action}</div><div className="tt-gateway-model-list">{rows.slice((current - 1) * 30, current * 30).map(row => <ModelRow key={rowKey(row)} row={row} users={users(row)} onSelect={onSelect} />)}</div>{rows.length > 30 && <Pagination size="small" current={current} total={rows.length} pageSize={30} showSizeChanger={false} onChange={setPage} />}</section>
}
export default function GatewayModelDirectory({ active = true, catalog, onSource, onPool }: { active?: boolean; catalog: ModelCatalog; onSource: (id: string) => void; onPool?: (id: string) => void }) {
  const { t, locale } = useI18n(), { message } = App.useApp(), directory = useGatewayModelCatalog(catalog.revision, active)
  const [source, setSource] = useState(''), [query, setQuery] = useState(''), [capability, setCapability] = useState(''), [price, setPrice] = useState(''), [kind, setKind] = useState('configured'), [selectedKey, setSelectedKey] = useState('')
  const opener = useRef<HTMLElement | null>(null)
  const metadata = directory.value?.revision === catalog.revision ? directory.value.models : []
  const configured = configuredGatewayModels(catalog, directory.value)
  const allRows: Entry[] = prioritizeGatewayModels([...configured, ...metadata.filter(row => !row.configured)]).map(row => {
    const sourceId = row.kind === 'aggregate' ? undefined : row.candidates?.[0]?.sourceId
    return { ...row, sourceId, unavailable: catalog.sources.find(source => source.id === sourceId)?.pluginDesktopUnavailable, sourceName: sourceId ? catalog.sources.find(source => source.id === sourceId)?.name || sourceId : t('gatewayWorkspace.kind.pool') }
  })
  const rows = allRows.filter(row => (kind === 'configured' ? row.configured : kindOf(row) === kind) && (!source || row.candidates?.some(candidate => candidate.sourceId === source)) && (!query.trim() || [row.name, row.id, row.sourceName, ...(row.candidates || []).map(candidate => candidate.model)].some(value => value.toLowerCase().includes(query.trim().toLowerCase()))) && (!capability || row.capabilities?.[capability]?.support === 'supported') && (!price || (price === 'free' ? freeGatewayModel(row) : row.pricing === price)))
  const selected = allRows.find(row => rowKey(row) === selectedKey), gateway = catalog.models.find(model => selected?.configured && model.id === selected.id)
  const canCopy = !!selected?.configured && selected.enabled && !selected.unavailable
  useEffect(() => { if (!active) setSelectedKey('') }, [active])
  const close = () => { setSelectedKey(''); setTimeout(() => opener.current?.focus({ preventScroll: true }), 0) }
  const select = (row: Entry, element: HTMLElement) => { opener.current = element; setSelectedKey(rowKey(row)) }
  const users = (row: Entry) => row.configured ? catalog.uses[row.id] || [] : []
  const filterKey = [kind, source, query, capability, price].join('\0')
  const pools = rows.filter(row => row.kind === 'aggregate')
  return <div className="tt-gateway-layout"><section className="tt-gateway-scroll tt-gateway-directory" aria-label={t('directory.title')}>
    <Tabs className="tt-directory-tabs" activeKey={kind} onChange={setKind} items={['configured', 'pool', 'native', 'upstream'].map(key => ({ key, label: t('gatewayWorkspace.kind.' + key) }))} />
    <div className="tt-directory-filters"><Input prefix={<SearchIcon />} aria-label={t('directory.search')} placeholder={t('directory.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear /><Select<string> aria-label={t('hub.source')} value={source} options={[{ value: '', label: t('monitor.allSources') }, ...catalog.sources.map(row => ({ value: row.id, label: row.name }))]} onChange={setSource} /><Select<string> aria-label={t('directory.capability')} value={capability} options={['', 'image', 'audio', 'video', 'tools', 'reasoning', 'structuredOutput', 'streaming'].map(value => ({ value, label: t(value ? 'modelSelection.capability.' + value : 'directory.allCapabilities') }))} onChange={setCapability} /><Select<string> aria-label={t('gatewayOptions.priceFilter')} value={price} options={['', 'free', 'metered', 'advertised-zero', 'unknown'].map(value => ({ value, label: t('gatewayOptions.filter.' + (value || 'all')) }))} onChange={setPrice} /></div>
    {(directory.failed || !!directory.value?.refreshFailures?.length) && <Alert type="warning" message={t('directory.loadFailed')} action={<Button onClick={directory.refresh}>{t('agent.retry')}</Button>} />}
    {directory.loading && <Spin size="small" />}
    <ModelGroup key={'pools/' + filterKey} rows={pools} title={t('gatewayWorkspace.kind.pool')} users={users} onSelect={select} />
    {catalog.sources.map(source => <ModelGroup key={source.id + '/' + filterKey} rows={rows.filter(row => row.kind !== 'aggregate' && row.sourceId === source.id)} title={t('hub.source') + ': ' + source.name} users={users} onSelect={select} action={<Button type="text" onClick={() => onSource(source.id)}>{t('gatewayWorkspace.viewSource')}</Button>} />)}
    {!rows.length && !directory.loading && <p className="tt-gateway-empty">{t(catalog.sources.length || catalog.models.length ? 'directory.noMatches' : 'hub.empty.connections')}</p>}
  </section>{active && selected && <GatewayInspector title={t('gatewayWorkspace.modelDetails', { model: selected.id })} onClose={close}><div className="tt-gateway-editor-scroll"><h3 className="tt-gateway-model-title">{selected.name || selected.id}</h3><span className={'tt-gateway-status' + (canCopy ? ' is-enabled' : '')}>{t(stateOf(selected))}</span><ModelCapabilities model={selected} /><dl className="tt-gateway-model-facts"><div><dt>{t('hub.source')}</dt><dd>{selected.sourceName}</dd></div><div><dt>{t('gatewayWorkspace.kind')}</dt><dd>{t('gatewayWorkspace.kind.' + kindOf(selected))}</dd></div>{selected.configured && <div><dt>{t('gatewayWorkspace.gatewayName')}</dt><dd><code>{selected.id}</code></dd></div>}{!!users(selected).length && <div><dt>{t('gatewayOptions.usedBy')}</dt><dd>{[...new Set(users(selected))].join(', ')}</dd></div>}{gateway?.aggregate ? <><div><dt>{t('pool.strategy')}</dt><dd>{t('pool.strategy.' + gateway.strategy)}</dd></div><div><dt>{t('pool.members')}</dt><dd>{t('pool.memberCount', { count: gateway.candidates.length })}</dd></div></> : <div><dt>{t('gatewayWorkspace.upstreamId')}</dt><dd><code>{selected.candidates?.[0]?.model || selected.id}</code></dd></div>}<div><dt>{t('directory.context')}</dt><dd>{selected.contextWindow ? new Intl.NumberFormat(locale).format(selected.contextWindow) : t('directory.unknown')}</dd></div><div><dt>{t('directory.output')}</dt><dd>{selected.maxOutputTokens ? new Intl.NumberFormat(locale).format(selected.maxOutputTokens) : t('directory.unknown')}</dd></div></dl>{selected.kind !== 'aggregate' && <details className="tt-gateway-published-price"><summary>{t('gatewayWorkspace.publishedPrice')}</summary><p>{t('gatewayWorkspace.publishedPriceHint')}</p><dl className="tt-gateway-model-facts"><div><dt>{t('directory.price')}</dt><dd>{selected.inputPrice === undefined ? t('directory.unknown') : new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(selected.inputPrice)} / {selected.outputPrice === undefined ? t('directory.unknown') : new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(selected.outputPrice)}</dd></div></dl></details>}{!selected.configured && <p className="tt-gateway-notice">{t('gatewayWorkspace.upstreamHint')}</p>}</div><footer className="tt-gateway-editor-footer">{(selected.sourceId || onPool) && <Button onClick={() => { close(); if (selected.sourceId) onSource(selected.sourceId); else onPool?.(selected.id) }}>{t(selected.sourceId ? 'gatewayWorkspace.viewSource' : 'gatewayWorkspace.viewPool')}</Button>}{canCopy && <Button type="primary" icon={<CopyIcon />} onClick={async () => { try { await navigator.clipboard.writeText(selected.id); message.success(t('common.copied')) } catch { message.error(t('gatewayWorkspace.copyFailed')) } }}>{t('gatewayWorkspace.copyModel', { model: selected.id })}</Button>}</footer></GatewayInspector>}</div>
}
