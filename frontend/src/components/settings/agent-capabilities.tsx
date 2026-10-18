import { useEffect, useState } from 'react'
import { Button, Input, Modal, Spin, Switch, Tag } from 'antd'
import { api } from '../../api'
import { FileTextIcon, GearIcon, PlusIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useCurrentNodeId } from '../cluster/node-url'
import './agent-settings.css'

type Skill = { name: string; text: string; version: string; source: string; enabled: boolean; description?: string }
type Tool = { name: string; description: string; schema: unknown; effect: string; main: boolean; enabled: boolean }
type Server = { name: string; transport: string; state: string; tools: number }
type Catalog = { skills: Skill[]; tools: Tool[]; mcp: Server[] }
export function AgentCapabilities({ kind }: { kind: 'skills' | 'tools' }) {
  const node = useCurrentNodeId()
  return <CapabilityList key={`${node || 'local'}:${kind}`} kind={kind} />
}
function CapabilityList({ kind }: { kind: 'skills' | 'tools' }) {
  const { t } = useI18n()
  const [catalog, setCatalog] = useState<Catalog | null>(null), [error, setError] = useState(''), [query, setQuery] = useState(''), [saving, setSaving] = useState(''), [version, setVersion] = useState(0), [selected, setSelected] = useState<Skill | Tool | null>(null), [importOpen, setImportOpen] = useState(false), [selectedServer, setSelectedServer] = useState<Server | null>(null)
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/capability-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setCatalog(data) }).catch(() => { if (!abort.signal.aborted) setError(t('agent.capabilities.failed')) })
    return () => abort.abort()
  }, [version, t])
  const change = async (name: string, enabled: boolean) => {
    if (saving) return
    setSaving(name); setError('')
    try { const { data } = await api('PUT', '/agent/capability-settings', { kind, name, enabled }); setCatalog(data) }
    catch { setError(t('agent.capabilities.failed')) }
    finally { setSaving('') }
  }
  if (!catalog && !error) return <Spin />
  const items = (catalog?.[kind] || []).filter(item => `${item.name} ${'description' in item ? item.description : ''}`.toLowerCase().includes(query.trim().toLowerCase()))
  return <section className="agent-capabilities">
    <div className="agent-capability-toolbar"><Input aria-label={t('agent.capabilities.search')} placeholder={t('agent.capabilities.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear /><Button icon={<PlusIcon size={16} />} onClick={() => setImportOpen(true)}>{t(`agent.capabilities.import.${kind}`)}</Button></div>
    <details className="agent-capability-help"><summary>{t('agent.capabilities.help')}</summary><p className="agent-settings-hint">{t(`agent.capabilities.${kind}Hint`)}</p><p className="agent-settings-hint">{t('agent.capabilities.effectHint')}</p></details>
    {error && <div className="agent-settings-error" role="alert">{error}<Button onClick={() => setVersion(v => v + 1)}>{t('agent.retry')}</Button></div>}
    {catalog && <p className="agent-settings-hint">{t('agent.capabilities.count', { count: items.length })}</p>}
    {catalog && !items.length && <p className="agent-settings-hint">{t('agent.capabilities.empty')}</p>}
    <div className="agent-capability-grid">{items.map(item => <article className="agent-capability-card" key={item.name}>
      <div className="agent-capability-cardtop"><span className="agent-capability-icon">{'text' in item ? <FileTextIcon size={24} /> : <GearIcon size={24} />}</span><div className="agent-capability-heading"><strong>{item.name}</strong><span className="agent-settings-hint">{t('source' in item ? `agent.capabilities.source.${item.source}` : item.main ? 'agent.capabilities.mainWorker' : 'agent.capabilities.workerOnly')}</span></div><Switch aria-label={t('agent.capabilities.enable', { name: item.name })} checked={item.enabled} loading={saving === item.name} disabled={!!saving} onChange={enabled => { void change(item.name, enabled) }} /></div>
      <p className="agent-capability-description">{item.description || t('agent.capabilities.skillFallback')}</p>
      <div className="agent-capability-footer"><div className="agent-capability-tags"><Tag>{t(item.enabled ? 'agent.capabilities.enabled' : 'agent.capabilities.disabled')}</Tag>{'effect' in item && <Tag>{t(item.effect === 'read' ? 'agent.capabilities.read' : 'agent.capabilities.write')}</Tag>}</div><button type="button" className="tt-act" onClick={() => setSelected(item)}>{t('text' in item ? 'agent.capabilities.content' : 'agent.capabilities.parameters')}</button></div>
    </article>)}</div>
    <Modal open={!!selected} centered title={selected?.name} footer={null} onCancel={() => setSelected(null)} className="agent-capability-dialog"><p className="agent-settings-hint">{selected?.description}</p><pre>{selected ? 'text' in selected ? selected.text : JSON.stringify(selected.schema, null, 2) : ''}</pre>{selected && 'version' in selected && <p className="agent-settings-hint">{t('agent.capabilities.version', { version: selected.version.slice(0, 12) })}</p>}</Modal>
    <Modal open={importOpen} centered title={t(`agent.capabilities.import.${kind}`)} footer={null} onCancel={() => setImportOpen(false)}><p>{t('agent.capabilities.importReserved')}</p><p className="agent-settings-hint">{t(`agent.capabilities.importFormat.${kind}`)}</p><details className="agent-capability-help"><summary>{t('agent.capabilities.importContract')}</summary><pre>POST /api/agent/capability-imports/{kind}</pre><p className="agent-settings-hint">{t('agent.capabilities.importNotActive')}</p></details></Modal>
    <Modal open={!!selectedServer} centered title={selectedServer?.name} footer={null} onCancel={() => setSelectedServer(null)}><p>{selectedServer?.transport} · {selectedServer && t(`agent.capabilities.mcp.${selectedServer.state}`)}</p><p className="agent-settings-hint">{t('agent.capabilities.mcpHint')}</p></Modal>
    {kind === 'tools' && catalog && <section className="agent-capability-servers"><h3>{t('agent.capabilities.mcp')}</h3><p className="agent-settings-hint">{t('agent.capabilities.mcpHint')}</p>{!catalog.mcp.length && <p className="agent-settings-hint">{t('agent.capabilities.noMcp')}</p>}<div className="agent-capability-grid">{catalog.mcp.map(server => <article key={server.name} className="agent-capability-card"><div className="agent-capability-cardtop"><span className="agent-capability-icon"><GearIcon size={24} /></span><div className="agent-capability-heading"><strong>{server.name}</strong><span className="agent-settings-hint">{server.transport}</span></div><Tag>{t(`agent.capabilities.mcp.${server.state}`)}</Tag></div><p className="agent-capability-description">{t('agent.capabilities.count', { count: server.tools })}</p><div className="agent-capability-footer"><span className="agent-settings-hint">{t('agent.capabilities.mcpObserved')}</span><button type="button" className="tt-act" onClick={() => setSelectedServer(server)}>{t('agent.capabilities.connectionDetails')}</button></div></article>)}</div></section>}
  </section>
}
