import { useEffect, useState } from 'react'
import { Button, Input, Modal, Spin, Switch, Tabs, Tag } from 'antd'
import { api } from '../../api'
import { FileTextIcon, GearIcon, PlusIcon } from '../../icons'
import { useI18n } from '../../i18n'
import Markdown from '../markdown/Markdown'
import { useCurrentNodeId } from '../cluster/node-url'
import './agent-settings.css'

type Skill = { name: string; text: string; version: string; source: string; enabled: boolean; mutable?: boolean; description?: string; references?: Record<string, { text: string; version: string }> }
type Tool = { name: string; description: string; schema: unknown; effect: string; main: boolean; enabled: boolean; roles?: string[]; source?: string; mutable?: boolean }
type Server = { name: string; transport: string; state: string; tools: number }
type CliGroup = { name: string; commands: { name: string; description: string; enabled: boolean; mutable?: boolean; source?: string }[] }
type CapabilityTab = 'tools' | 'mcp' | 'skills' | 'cli'
const capabilityTabs: CapabilityTab[] = ['tools', 'mcp', 'skills', 'cli']
type Catalog = { skills: Skill[]; tools: Tool[]; mcp: Server[]; cli?: CliGroup[] }
const foundations = new Set(['read', 'bash', 'edit', 'write', 'tool_search', 'delegate', 'ask_user'])
export function AgentCapabilities({ kind }: { kind?: CapabilityTab }) {
  const node = useCurrentNodeId()
  return <CapabilityManager key={node || 'local'} initialTab={kind} />
}
function CapabilityManager({ initialTab }: { initialTab?: CapabilityTab }) {
  const { t } = useI18n()
  const legacyTab = location.hash.split('/').pop() as CapabilityTab
  const requested = initialTab || (capabilityTabs.includes(legacyTab) ? legacyTab : 'tools')
  const [active, setActive] = useState<CapabilityTab>(requested)
  useEffect(() => setActive(requested), [requested])
  return <div className="agent-capability-manager"><Tabs activeKey={active} onChange={key => setActive(key as CapabilityTab)} destroyInactiveTabPane items={capabilityTabs.map(tab => ({ key: tab, label: t(`agent.capabilities.tab.${tab}`), children: <CapabilityList kind={tab} /> }))} /></div>
}
function CapabilityList({ kind }: { kind: CapabilityTab }) {
  const { t } = useI18n()
  const [catalog, setCatalog] = useState<Catalog | null>(null), [error, setError] = useState(''), [query, setQuery] = useState(''), [saving, setSaving] = useState(''), [version, setVersion] = useState(0), [selected, setSelected] = useState<Skill | Tool | null>(null), [importOpen, setImportOpen] = useState(false), [selectedServer, setSelectedServer] = useState<Server | null>(null), [reference, setReference] = useState('')
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/capability-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setCatalog(data) }).catch(() => { if (!abort.signal.aborted) setError(t('agent.capabilities.failed')) })
    return () => abort.abort()
  }, [version, t])
  const change = async (name: string, enabled: boolean) => {
    if (saving) return
    setSaving(name); setError('')
    try { const { data } = await api('PUT', '/agent/capability-settings', { kind: kind === 'skills' ? 'skills' : 'tools', name, enabled }); setCatalog(data) }
    catch { setError(t('agent.capabilities.failed')) }
    finally { setSaving('') }
  }
  if (!catalog && !error) return <Spin />
  const items = ((kind === 'skills' || kind === 'tools' ? catalog?.[kind] : []) || []).filter(item => `${item.name} ${'description' in item ? item.description : ''}`.toLowerCase().includes(query.trim().toLowerCase()))
  return <section className="agent-capabilities">
    <div className="agent-capability-toolbar"><Input aria-label={t('agent.capabilities.search')} placeholder={t('agent.capabilities.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear />{(kind === 'tools' || kind === 'skills') && <Button icon={<PlusIcon size={16} />} onClick={() => setImportOpen(true)}>{t(`agent.capabilities.import.${kind}`)}</Button>}</div>
    <details className="agent-capability-help"><summary>{t('agent.capabilities.help')}</summary><p className="agent-settings-hint">{t(kind === 'cli' ? 'agent.capabilities.cliHint' : kind === 'mcp' ? 'agent.capabilities.mcpHint' : `agent.capabilities.${kind}Hint`)}</p><p className="agent-settings-hint">{t('agent.capabilities.effectHint')}</p></details>
    {error && <div className="agent-settings-error" role="alert">{error}<Button onClick={() => setVersion(v => v + 1)}>{t('agent.retry')}</Button></div>}
    {catalog && (kind === 'tools' || kind === 'skills') && <p className="agent-settings-hint">{kind === 'tools' ? t('agent.capabilities.foundationSummary', { count: catalog.tools.filter(tool => tool.enabled).length, total: catalog.tools.length }) : t('agent.capabilities.count', { count: items.length })}</p>}
    {catalog && (kind === 'tools' || kind === 'skills') && !items.length && <p className="agent-settings-hint">{t('agent.capabilities.empty')}</p>}
    <div className="agent-capability-grid">{items.map(item => <article className="agent-capability-card" key={item.name}>
      <div className="agent-capability-cardtop"><span className="agent-capability-icon">{'text' in item ? <FileTextIcon size={24} /> : <GearIcon size={24} />}</span><div className="agent-capability-heading"><strong>{item.name}</strong><span className="agent-settings-hint">{t('source' in item ? `agent.capabilities.source.${item.source}` : item.roles?.length === 1 && item.roles[0] === 'main' ? 'agent.capabilities.mainOnly' : item.main ? 'agent.capabilities.mainWorker' : 'agent.capabilities.workerOnly')}</span></div>{item.mutable === true ? <Switch aria-label={t('agent.capabilities.enable', { name: item.name })} checked={item.enabled} loading={saving === item.name} disabled={!!saving} onChange={enabled => { void change(item.name, enabled) }} /> : <Tag>{t('agent.capabilities.builtinFixed')}</Tag>}</div>
      <p className="agent-capability-description">{'text' in item && ['roami-dispatch', 'web-research'].includes(item.name) ? t(`agent.capabilities.skillDescription.${item.name}`) : 'effect' in item && foundations.has(item.name) ? t(`agent.capabilities.toolDescription.${item.name}`) : item.description || t('agent.capabilities.skillFallback')}</p>
      <div className="agent-capability-footer"><div className="agent-capability-tags"><Tag>{t(item.enabled ? 'agent.capabilities.enabled' : 'agent.capabilities.disabled')}</Tag>{'effect' in item && <Tag>{t(item.name === 'bash' ? 'agent.capabilities.dynamic' : item.effect === 'read' ? 'agent.capabilities.read' : 'agent.capabilities.write')}</Tag>}</div><button type="button" className="tt-act" onClick={() => { setReference(''); setSelected(item) }}>{t('text' in item ? 'agent.capabilities.content' : 'agent.capabilities.parameters')}</button></div>
    </article>)}</div>
    <Modal open={!!selected} centered width="min(var(--content-form), calc(100vw - var(--sp-4) - var(--sp-4)))" title={selected?.name} footer={null} onCancel={() => setSelected(null)} className="agent-capability-dialog"><p className="agent-settings-hint">{selected?.description}</p>{selected && 'text' in selected ? <><div className="agent-capability-reference-nav">{!!Object.keys(selected.references || {}).length && <><Button onClick={() => setReference('')} aria-pressed={!reference}>{t('agent.capabilities.skillOverview')}</Button>{Object.keys(selected.references || {}).map(path => <Button key={path} aria-pressed={reference === path} onClick={() => setReference(path)}>{path.replace('references/', '')}</Button>)}</>}</div><Markdown>{(reference && selected.references?.[reference]?.text || selected.text).replace(/^---\n[\s\S]*?\n---\n/, '')}</Markdown></> : <pre>{selected && 'schema' in selected ? JSON.stringify(selected.schema, null, 2) : ''}</pre>}{selected && 'version' in selected && <p className="agent-settings-hint">{t('agent.capabilities.version', { version: selected.version.slice(0, 12) })}</p>}</Modal>
    <Modal open={importOpen} centered title={t(`agent.capabilities.import.${kind}`)} footer={null} onCancel={() => setImportOpen(false)}><p>{t('agent.capabilities.importReserved')}</p><p className="agent-settings-hint">{t(`agent.capabilities.importFormat.${kind}`)}</p><details className="agent-capability-help"><summary>{t('agent.capabilities.importContract')}</summary><pre>POST /api/agent/capability-imports/{kind}</pre><p className="agent-settings-hint">{t('agent.capabilities.importNotActive')}</p></details></Modal>
    <Modal open={!!selectedServer} centered title={selectedServer?.name} footer={null} onCancel={() => setSelectedServer(null)}><p>{selectedServer?.transport} · {selectedServer && t(`agent.capabilities.mcp.${selectedServer.state}`)}</p><p className="agent-settings-hint">{t('agent.capabilities.mcpHint')}</p></Modal>
    {kind === 'cli' && !!catalog?.cli?.length && <section className="agent-capability-cli"><p className="agent-settings-hint">{t('agent.capabilities.cli', { count: catalog.cli.length })}</p><p className="agent-settings-hint">{t('agent.capabilities.cliHint')}</p><div className="agent-capability-grid">{catalog.cli.filter(group => `${group.name} ${group.commands.map(command => command.name).join(' ')}`.toLowerCase().includes(query.trim().toLowerCase())).map(group => <article className="agent-capability-card" key={group.name}><strong>{t(`agent.capabilities.cliGroup.${group.name}`)}</strong><p className="agent-settings-hint">{t('agent.capabilities.cliCount', { count: group.commands.length })}</p><details className="agent-capability-help"><summary>{t('agent.capabilities.cliCommands')}</summary>{group.commands.map(command => <p key={command.name}><code>{command.name}</code>{command.mutable === true ? <Switch aria-label={t('agent.capabilities.enable', { name: command.name })} checked={command.enabled} disabled={!!saving} loading={saving === command.name} onChange={enabled => { void change(command.name, enabled) }} /> : <Tag>{t('agent.capabilities.builtinFixed')}</Tag>}</p>)}</details></article>)}</div></section>}
    {kind === 'mcp' && catalog && <section className="agent-capability-servers"><h3>{t('agent.capabilities.mcp')}</h3><p className="agent-settings-hint">{t('agent.capabilities.mcpHint')}</p>{!catalog.mcp.length && <p className="agent-settings-hint">{t('agent.capabilities.noMcp')}</p>}<div className="agent-capability-grid">{catalog.mcp.filter(server => `${server.name} ${server.transport}`.toLowerCase().includes(query.trim().toLowerCase())).map(server => <article key={server.name} className="agent-capability-card"><div className="agent-capability-cardtop"><span className="agent-capability-icon"><GearIcon size={24} /></span><div className="agent-capability-heading"><strong>{server.name}</strong><span className="agent-settings-hint">{server.transport}</span></div><Tag>{t(`agent.capabilities.mcp.${server.state}`)}</Tag></div><p className="agent-capability-description">{t('agent.capabilities.count', { count: server.tools })}</p><div className="agent-capability-footer"><span className="agent-settings-hint">{t('agent.capabilities.mcpObserved')}</span><button type="button" className="tt-act" onClick={() => setSelectedServer(server)}>{t('agent.capabilities.connectionDetails')}</button></div></article>)}</div></section>}
  </section>
}
