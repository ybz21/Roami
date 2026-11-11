import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Empty, Form, Input, Modal, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { SearchIcon, GearIcon, ChevronRight } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import CapabilityEditor, { capabilityError } from './CapabilityEditor'
import MarketSources, { type MarketSource } from './MarketSources'
import type { ManagedEntry, ManagedKind } from './capability-format'

type Listing = { id: string; name: string; description: string; version: string; url: string; installs?: number }
type Preview = { kind: ManagedKind; options: { label: string; entry: ManagedEntry }[] }

export default function CapabilityMarket() {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const [sources, setSources] = useState<MarketSource[] | null>(null)
  const [source, setSource] = useState('')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<Listing[]>([])
  const [next, setNext] = useState('')
  const [searched, setSearched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [configuring, setConfiguring] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [option, setOption] = useState(0)
  const [editing, setEditing] = useState(false)
  const [retry, setRetry] = useState(0)
  const [previewId, setPreviewId] = useState('')
  const [targets, setTargets] = useState(['local', 'claude', 'opencode', 'roami'])
  const [installError, setInstallError] = useState('')
  const request = useRef<AbortController>()
  const lastQuery = useRef('')
  useEffect(() => {
    const abort = new AbortController()
    void api('GET', '/agent/capability-markets', undefined, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) { setSources(data.sources); setSource(data.sources.find((item: MarketSource) => item.enabled)?.id || ''); setError('') }
    }).catch((caught: Error) => { if (!abort.signal.aborted) setError(capabilityError(caught.message, t)) })
    return () => { abort.abort(); request.current?.abort() }
  }, [retry, t])
  const reset = (id: string) => { request.current?.abort(); setBusy(false); setSource(id); setItems([]); setNext(''); setSearched(false); setError(''); setSuccess(''); setPreview(null) }
  const load = useCallback(async (sourceId: string, submitted: string, cursor = '') => {
    request.current?.abort()
    const abort = new AbortController(); request.current = abort
    setBusy(true); setError(''); setSuccess('')
    try {
      const { data } = await api('GET', '/agent/capability-markets/' + encodeURIComponent(sourceId) + '/search?query=' + encodeURIComponent(submitted) + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''), undefined, { signal: abort.signal })
      if (!abort.signal.aborted) { lastQuery.current = submitted; setItems(rows => cursor ? [...rows, ...data.items.filter((item: Listing) => !rows.some(row => row.id === item.id && row.version === item.version))] : data.items); setNext(data.nextCursor || ''); setSearched(Boolean(submitted)) }
    } catch (caught: any) { if (!abort.signal.aborted) setError(capabilityError(caught.message, t)) } finally { if (!abort.signal.aborted) setBusy(false) }
  }, [t])
  const popular = sources?.find(row => row.id === source)?.provider === 'skills_sh'
  useEffect(() => {
    if (popular) void load(source, '')
    return () => request.current?.abort()
  }, [source, popular, sources, load])
  const search = (cursor = '') => load(source, cursor ? lastQuery.current : query.trim(), cursor)
  const view = async (item: Listing) => {
    request.current?.abort()
    const abort = new AbortController(); request.current = abort
    setBusy(true); setError(''); setSuccess(''); setInstallError(''); setPreviewId('')
    try {
      const { data } = await api('POST', '/agent/capability-markets/preview', { source, id: item.id, version: item.version }, { signal: abort.signal })
      if (data.kind === 'skills' && !abort.signal.aborted) {
        const prepared = await api('POST', '/agent/capability-markets/prepare', { source, id: item.id, version: item.version }, { signal: abort.signal })
        if (!abort.signal.aborted) setPreviewId(prepared.data.previewId)
      }
      if (!abort.signal.aborted) { setPreview(data); setOption(0); setTargets(['local', 'claude', 'opencode', 'roami']) }
    } catch (caught: any) { if (!abort.signal.aborted) setError(capabilityError(caught.message, t)) } finally { if (!abort.signal.aborted) setBusy(false) }
  }
  const install = async () => {
    setBusy(true); setInstallError('')
    try {
      await api('POST', '/agent/capability-markets/install', { previewId, option, targets })
      setPreview(null); setSuccess(t('capabilities.market.installed'))
    } catch (caught: any) { setInstallError(capabilityError(caught.message, t)) } finally { setBusy(false) }
  }
  const selected = preview?.options[option]
  const detail = selected && <div className="tt-market-preview">
    {preview.options.length > 1 && <Form.Item label={t('capabilities.market.variant')}><Select aria-label={t('capabilities.market.variant')} value={option} onChange={setOption} options={preview.options.map((item, value) => ({ value, label: item.label }))} /></Form.Item>}
    {preview.kind !== 'skills' && <p>{t('capabilities.market.reviewHint')}</p>}
    {preview.kind === 'cli' && <Alert type="info" message={t('capabilities.market.cliHint')} />}
    {preview.kind === 'skills' ? <details><summary><ChevronRight />{t('capabilities.instructions')}</summary><pre>{selected.entry.text}</pre></details> : <pre>{JSON.stringify(selected.entry.config || selected.entry.argv, null, 2)}</pre>}
    {selected.entry.files && <p>{t('capabilities.market.fileCount', { count: Object.keys(selected.entry.files).length })}</p>}
    {preview.kind === 'skills' && <Form.Item label={t('capabilities.market.installTargets')}><Checkbox.Group className="tt-market-targets" value={targets} disabled={busy} onChange={setTargets} options={['local', 'claude', 'opencode', 'roami'].map(value => ({ value, label: t('capabilities.market.target.' + value) }))} /><p>{t('capabilities.market.installHint')}</p></Form.Item>}
    {installError && <Alert type="error" message={installError} />}
    <div className="tt-capability-actions"><a href={selected.entry.origin?.url} target="_blank" rel="noreferrer">{t('capabilities.market.upstream')}</a>{preview.kind === 'skills' ? <Button type="primary" loading={busy} disabled={!previewId || !targets.length} onClick={() => { void install() }}>{t('capabilities.market.install')}</Button> : <Button type="primary" onClick={() => setEditing(true)}>{t('capabilities.market.reviewImport')}</Button>}</div>
  </div>
  return <section className="tt-capability-catalog tt-market">
    <Form className="tt-capability-toolbar" onFinish={() => { void search() }}>
      <Select aria-label={t('capabilities.market.source')} value={source || undefined} onChange={reset} options={(sources || []).filter(item => item.enabled).map(item => ({ value: item.id, label: item.name }))} />
      <Input prefix={<SearchIcon size={16} />} aria-label={t('capabilities.market.query')} placeholder={t('capabilities.market.query')} value={query} onChange={event => setQuery(event.target.value)} allowClear />
      <Button type="primary" htmlType="submit" loading={busy} disabled={!source || (!query.trim() && !popular)}>{t('capabilities.market.search')}</Button>
      <Button icon={<GearIcon size={16} />} disabled={!sources || busy} onClick={() => setConfiguring(true)}>{t('capabilities.market.sources')}</Button>
    </Form>
    {error && <Alert className="tt-capability-alert" type="error" message={error} action={<Button onClick={() => { if (!sources) setRetry(value => value + 1); else void search() }}>{t('agent.retry')}</Button>} />}
    {success && <Alert className="tt-capability-alert" type="success" message={success} />}
    {popular && <div className="tt-market-heading"><h3>{t(searched ? 'capabilities.market.results' : 'capabilities.market.popular')}</h3>{searched ? <Button onClick={() => { setQuery(''); void load(source, '') }} disabled={busy}>{t('capabilities.market.backPopular')}</Button> : <span>{t('capabilities.market.popularOrder')}</span>}</div>}
    {!sources && !error && <Spin />}
    {busy && !items.length && <Spin />}
    {sources && !items.length && !busy && !error && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t(searched || popular ? 'capabilities.market.empty' : 'capabilities.market.start')} />}
    <div className="tt-capability-list">{items.map(item => <article className="tt-capability-row" key={item.id + ':' + item.version}>
      <button className="tt-capability-open" type="button" disabled={busy} onClick={() => { void view(item) }}><strong>{item.name}</strong></button>
      <p className="tt-capability-description">{item.description}</p>
      <div className="tt-capability-cardfooter"><span className="tt-capability-source">{item.installs === undefined ? item.version || sources?.find(row => row.id === source)?.name : t('capabilities.market.installs', { count: new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(item.installs) })}</span><button type="button" className="tt-act" disabled={busy} onClick={() => { void view(item) }}>{t('capabilities.market.view')}</button></div>
    </article>)}</div>
    {next && <div className="tt-market-more"><Button loading={busy} onClick={() => { void search(next) }}>{t('capabilities.market.more')}</Button></div>}
    {preview && !editing && (phone ? <MobileSubPage title={selected?.entry.name || ''} search={false} onBack={() => { if (!busy) setPreview(null) }}><div className="tt-capability-detail-scroll">{detail}</div></MobileSubPage> : <Modal open title={selected?.entry.name} footer={null} closable={!busy} maskClosable={!busy} keyboard={!busy} onCancel={() => setPreview(null)} className="tt-capability-modal">{detail}</Modal>)}
    {preview && editing && <CapabilityEditor kind={preview.kind} draft={selected?.entry} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); setPreview(null); setSuccess(t('capabilities.market.imported')) }} />}
    {configuring && sources && <MarketSources sources={sources} onClose={() => setConfiguring(false)} onSaved={rows => { setSources(rows); reset(rows.find(row => row.id === source && row.enabled)?.id || rows.find(row => row.enabled)?.id || ''); setConfiguring(false) }} />}
  </section>
}
