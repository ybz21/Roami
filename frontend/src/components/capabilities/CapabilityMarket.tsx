import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Form, Input, Modal, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { SearchIcon, GearIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import CapabilityEditor, { capabilityError } from './CapabilityEditor'
import MarketSources, { type MarketSource } from './MarketSources'
import type { ManagedEntry, ManagedKind } from './capability-format'

type Listing = { id: string; name: string; description: string; version: string; url: string }
type Preview = { kind: ManagedKind; options: { label: string; entry: ManagedEntry }[] }

export default function CapabilityMarket() {
  const { t } = useI18n()
  const { phone } = useLayout()
  const [sources, setSources] = useState<MarketSource[] | null>(null)
  const [source, setSource] = useState('')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<Listing[]>([])
  const [next, setNext] = useState('')
  const [searched, setSearched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [configuring, setConfiguring] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [option, setOption] = useState(0)
  const [editing, setEditing] = useState(false)
  const [retry, setRetry] = useState(0)
  const request = useRef<AbortController>()
  const lastQuery = useRef('')
  useEffect(() => {
    const abort = new AbortController()
    void api('GET', '/agent/capability-markets', undefined, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) { setSources(data.sources); setSource(data.sources.find((item: MarketSource) => item.enabled)?.id || ''); setError('') }
    }).catch((caught: Error) => { if (!abort.signal.aborted) setError(capabilityError(caught.message, t)) })
    return () => { abort.abort(); request.current?.abort() }
  }, [retry, t])
  const reset = (id: string) => { request.current?.abort(); setBusy(false); setSource(id); setItems([]); setNext(''); setSearched(false); setError(''); setSuccess(false); setPreview(null) }
  const search = async (cursor = '') => {
    request.current?.abort()
    const abort = new AbortController(); request.current = abort
    setBusy(true); setError(''); setSuccess(false)
    const submitted = cursor ? lastQuery.current : query.trim()
    try {
      const { data } = await api('GET', '/agent/capability-markets/' + encodeURIComponent(source) + '/search?query=' + encodeURIComponent(submitted) + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''), undefined, { signal: abort.signal })
      if (!abort.signal.aborted) { lastQuery.current = submitted; setItems(rows => cursor ? [...rows, ...data.items.filter((item: Listing) => !rows.some(row => row.id === item.id && row.version === item.version))] : data.items); setNext(data.nextCursor || ''); setSearched(true) }
    } catch (caught: any) { if (!abort.signal.aborted) setError(capabilityError(caught.message, t)) } finally { if (!abort.signal.aborted) setBusy(false) }
  }
  const view = async (item: Listing) => {
    request.current?.abort()
    const abort = new AbortController(); request.current = abort
    setBusy(true); setError(''); setSuccess(false)
    try {
      const { data } = await api('POST', '/agent/capability-markets/preview', { source, id: item.id, version: item.version }, { signal: abort.signal })
      if (!abort.signal.aborted) { setPreview(data); setOption(0) }
    } catch (caught: any) { if (!abort.signal.aborted) setError(capabilityError(caught.message, t)) } finally { if (!abort.signal.aborted) setBusy(false) }
  }
  const selected = preview?.options[option]
  const detail = selected && <div className="tt-market-preview">
    {preview.options.length > 1 && <Form.Item label={t('capabilities.market.variant')}><Select aria-label={t('capabilities.market.variant')} value={option} onChange={setOption} options={preview.options.map((item, value) => ({ value, label: item.label }))} /></Form.Item>}
    <p>{t('capabilities.market.reviewHint')}</p>
    {preview.kind === 'cli' && <Alert type="info" message={t('capabilities.market.cliHint')} />}
    <pre>{preview.kind === 'skills' ? selected.entry.text : JSON.stringify(selected.entry.config || selected.entry.argv, null, 2)}</pre>
    {selected.entry.files && <p>{t('capabilities.market.fileCount', { count: Object.keys(selected.entry.files).length })}</p>}
    <div className="tt-capability-actions"><a href={selected.entry.origin?.url} target="_blank" rel="noreferrer">{t('capabilities.market.upstream')}</a><Button type="primary" onClick={() => setEditing(true)}>{t('capabilities.market.reviewImport')}</Button></div>
  </div>
  return <section className="tt-capability-catalog tt-market">
    <Form className="tt-capability-toolbar" onFinish={() => { void search() }}>
      <Select aria-label={t('capabilities.market.source')} value={source || undefined} onChange={reset} options={(sources || []).filter(item => item.enabled).map(item => ({ value: item.id, label: item.name }))} />
      <Input prefix={<SearchIcon size={16} />} aria-label={t('capabilities.market.query')} placeholder={t('capabilities.market.query')} value={query} onChange={event => setQuery(event.target.value)} allowClear />
      <Button type="primary" htmlType="submit" loading={busy} disabled={!source || !query.trim()}>{t('capabilities.market.search')}</Button>
      <Button icon={<GearIcon size={16} />} disabled={!sources || busy} onClick={() => setConfiguring(true)}>{t('capabilities.market.sources')}</Button>
    </Form>
    {error && <Alert className="tt-capability-alert" type="error" message={error} action={<Button onClick={() => { if (!sources) setRetry(value => value + 1); else void search() }}>{t('agent.retry')}</Button>} />}
    {success && <Alert className="tt-capability-alert" type="success" message={t('capabilities.market.imported')} />}
    {!sources && !error && <Spin />}
    {sources && !items.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t(searched ? 'capabilities.market.empty' : 'capabilities.market.start')} />}
    <div className="tt-capability-list">{items.map(item => <article className="tt-capability-row" key={item.id + ':' + item.version}>
      <button className="tt-capability-open" type="button" disabled={busy} onClick={() => { void view(item) }}><strong>{item.name}</strong></button>
      <p className="tt-capability-description">{item.description}</p>
      <div className="tt-capability-cardfooter"><span className="tt-capability-source">{item.version || sources?.find(row => row.id === source)?.name}</span><button type="button" className="tt-act" disabled={busy} onClick={() => { void view(item) }}>{t('capabilities.market.view')}</button></div>
    </article>)}</div>
    {next && <div className="tt-market-more"><Button loading={busy} onClick={() => { void search(next) }}>{t('capabilities.market.more')}</Button></div>}
    {preview && !editing && (phone ? <MobileSubPage title={selected?.entry.name || ''} search={false} onBack={() => setPreview(null)}><div className="tt-capability-detail-scroll">{detail}</div></MobileSubPage> : <Modal open title={selected?.entry.name} footer={null} onCancel={() => setPreview(null)} className="tt-capability-modal">{detail}</Modal>)}
    {preview && editing && <CapabilityEditor kind={preview.kind} draft={selected?.entry} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); setPreview(null); setSuccess(true) }} />}
    {configuring && sources && <MarketSources sources={sources} onClose={() => setConfiguring(false)} onSaved={rows => { setSources(rows); reset(rows.find(row => row.id === source && row.enabled)?.id || rows.find(row => row.enabled)?.id || ''); setConfiguring(false) }} />}
  </section>
}
