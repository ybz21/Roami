import { useEffect, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Popconfirm, Spin, Switch, Tag } from 'antd'
import { api } from '../../api'
import { FileTextIcon, GearIcon, PlusIcon, SearchIcon, UploadIcon, TerminalIcon, PlugIcon, PencilIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import Markdown from '../markdown/Markdown'
import MobileSubPage from '../MobileSubPage'
import CapabilityEditor, { capabilityError } from './CapabilityEditor'
import type { ManagedCatalog, ManagedEntry, ManagedKind } from './capability-format'

type Skill = { name: string; description?: string; text: string; version: string; source: string; enabled: boolean; mutable?: boolean; references?: Record<string, { text: string; version: string }> }
type Tool = { name: string; description: string; schema?: unknown; effect?: string; enabled: boolean; mutable?: boolean; source?: string; skill?: string; commands?: { argv: string[] }[] }
type Server = { name: string; displayName?: string; description?: string; transport: string; state: string; tools: number; toolNames?: string[] }
export type Catalog = { skills: Skill[]; tools: Tool[]; cli?: { name: string; commands: Tool[] }[]; mcp: Server[]; mcpTools?: Tool[]; managed?: ManagedCatalog }
type Entry = { name: string; displayName?: string; description: string; source: string; enabled?: boolean; mutable?: boolean; text?: string; schema?: unknown; references?: Skill['references']; state?: string; tools?: number; toolNames?: string[]; effect?: string; managed?: ManagedEntry; skill?: string; commands?: { argv: string[] }[] }

export function CapabilityCatalog({ kind }: { kind: 'skills' | 'cli' | 'mcp' | 'tools' }) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [version, setVersion] = useState(0)
  const [saving, setSaving] = useState('')
  const [selectedName, setSelectedName] = useState('')
  const [reference, setReference] = useState('')
  const [editor, setEditor] = useState<{ importing?: boolean; entry?: ManagedEntry } | null>(null)
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/capability-settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setCatalog(data) }).catch(() => { if (!abort.signal.aborted) setError(t('capabilities.error.failed')) })
    return () => abort.abort()
  }, [version, t])
  const managed = kind === 'tools' ? {} : catalog?.managed?.[kind] || {}
  const rows: Entry[] = kind === 'skills' ? (catalog?.skills || []).map(skill => ({ ...skill, description: ['roami', 'browser_use'].includes(skill.name) ? t('agent.capabilities.skillDescription.' + skill.name) : skill.description || t('agent.capabilities.skillFallback'), managed: managed[skill.name] }))
    : kind === 'mcp' ? (catalog?.mcp || []).map(server => ({ ...server, source: server.transport, displayName: server.displayName || managed[server.name]?.displayName, description: server.description || managed[server.name]?.description || '', managed: managed[server.name] }))
    : (kind === 'tools' ? catalog?.tools || [] : (catalog?.cli || []).flatMap(group => group.commands).filter(tool => !tool.name.startsWith('mcp_'))).map(tool => ({ ...tool, description: kind === 'tools' && ['read', 'bash', 'edit', 'write', 'tool_list', 'delegate', 'ask_user', 'computer_open', 'computer_observe', 'computer_act'].includes(tool.name) ? t('agent.capabilities.toolDescription.' + tool.name) : ['roami', 'roami chrome'].includes(tool.name) ? t('agent.capabilities.cliDescription.' + tool.name) : tool.description, source: tool.source || 'builtin', managed: managed[tool.name.replace(/^cli_/, '')] }))
  const filtered = rows.filter(row => `${row.displayName || row.name} ${row.name} ${row.description}`.toLowerCase().includes(query.trim().toLowerCase()))
  const selected = rows.find(row => row.name === selectedName)
  const change = async (row: Entry, enabled: boolean) => {
    if (saving) return
    setSaving(row.name); setError('')
    try {
      const { data } = await api('PUT', '/agent/capability-settings', { kind: kind === 'skills' ? 'skills' : 'tools', name: row.name, enabled })
      setCatalog(data)
    } catch (caught: any) { setError(capabilityError(caught.message, t)) }
    finally { setSaving('') }
  }
  const remove = async (row: Entry) => {
    if (!row.managed || saving) return
    setSaving(row.name); setError('')
    try {
      const { data } = await api('DELETE', '/agent/capability-imports/' + kind + '/' + encodeURIComponent(row.managed.name))
      setCatalog(data); setSelectedName('')
    } catch (caught: any) { setError(capabilityError(caught.message, t)) }
    finally { setSaving('') }
  }
  const connect = async (row: Entry) => {
    if (saving) return
    setSaving(row.name); setError('')
    try {
      const { data } = await api('POST', '/agent/capability-imports/mcp/' + encodeURIComponent(row.name) + '/connect')
      setCatalog(data)
    } catch (caught: any) {
      setError(capabilityError(caught.message, t))
      try { const { data } = await api('GET', '/agent/capability-settings'); setCatalog(data) } catch { /* Keep the current catalog during recovery. */ }
    }
    finally { setSaving('') }
  }
  const source = (row: Entry) => kind === 'mcp' ? t('capabilities.transport.' + row.source) : t('capabilities.source.' + (row.managed ? 'managed' : row.source === 'builtin' ? 'builtin' : 'configured'))
  const label = (row: Entry) => row.displayName || row.managed?.displayName || row.managed?.name || row.name
  const actions = (row: Entry) => <div className="tt-capability-actions">
    {kind === 'mcp' && row.state !== 'connected' && <Button loading={saving === row.name} disabled={!!saving} onClick={() => { void connect(row) }}>{t('capabilities.connect')}</Button>}
    {row.managed && <>
      <Button disabled={!!saving} onClick={() => setEditor({ entry: row.managed })}>{t('capabilities.edit')}</Button>
      <Popconfirm title={t('capabilities.removeConfirm', { name: label(row) })} onConfirm={() => remove(row)}><Button danger disabled={!!saving}>{t('capabilities.remove')}</Button></Popconfirm>
    </>}
  </div>
  const detail = selected && <div className="tt-capability-detail">
    <div className="tt-capability-detail-meta"><Tag>{source(selected)}</Tag>{selected.state && <Tag>{t('agent.capabilities.mcp.' + selected.state)}</Tag>}</div>
    {selected.description && <p>{selected.description}</p>}
    {kind === 'mcp' && !!selected.tools && <p>{t('capabilities.toolCount', { count: new Intl.NumberFormat(locale).format(selected.tools) })}</p>}
    {actions(selected)}
    {selected.skill && <details><summary>{t('capabilities.relatedSkill', { name: selected.skill })}</summary><Markdown>{catalog?.skills.find(skill => skill.name === selected.skill)?.text.replace(/^---\n[\s\S]*?\n---\n/, '') || ''}</Markdown></details>}
    {kind === 'mcp' && !!selected.toolNames?.length && <div className="tt-capability-remote-tools">
      <h3>{t('capabilities.serverTools')}</h3>
      {(catalog?.mcpTools || (catalog?.cli || []).flatMap(group => group.commands)).filter(tool => selected.toolNames?.includes(tool.name)).map(tool => <div className="tt-capability-remote-tool" key={tool.name}><span><strong>{tool.name}</strong><small>{tool.description}</small></span><Switch aria-label={t('agent.capabilities.enable', { name: tool.name })} checked={tool.enabled} disabled={!!saving} loading={saving === tool.name} onChange={enabled => { void change({ ...tool, source: 'external' }, enabled) }} /></div>)}
    </div>}
    {error && <Alert type="error" message={error} />}
    {selected.text !== undefined ? <>
      {!!Object.keys(selected.references || {}).length && <div className="tt-capability-references"><Button aria-pressed={!reference} onClick={() => setReference('')}>{t('agent.capabilities.skillOverview')}</Button>{Object.keys(selected.references || {}).map(path => <Button key={path} aria-pressed={reference === path} onClick={() => setReference(path)}>{path.replace('references/', '')}</Button>)}</div>}
      <Markdown>{(reference && selected.references?.[reference]?.text || selected.text).replace(/^---\n[\s\S]*?\n---\n/, '')}</Markdown>
    </> : <pre>{JSON.stringify(selected.managed || selected.schema || { transport: selected.source, state: selected.state, tools: selected.tools }, null, 2)}</pre>}
  </div>
  return <section className="tt-capability-catalog" data-kind={kind}>
    <div className="tt-capability-toolbar">
      <Input prefix={<SearchIcon size={16} />} aria-label={t('agent.capabilities.search')} placeholder={t('agent.capabilities.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear />
      {kind !== 'tools' && <div className="tt-capability-toolbar-actions"><Button icon={<UploadIcon size={16} />} onClick={() => setEditor({ importing: true })}>{t('capabilities.uploadFile')}</Button><Button type="primary" icon={<PlusIcon size={16} />} onClick={() => setEditor({})}>{t('capabilities.createAction.' + kind)}</Button></div>}
    </div>
    {error && <Alert type="error" showIcon message={error} action={<Button onClick={() => setVersion(value => value + 1)}>{t('agent.retry')}</Button>} />}
    {!catalog && !error && <Spin />}
    {catalog && !filtered.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('agent.capabilities.empty')} />}
    <div className="tt-capability-list">{filtered.map(row => <article className="tt-capability-row" key={row.name}>
      <div className="tt-capability-cardhead"><span className="tt-capability-icon">{kind === 'skills' ? <FileTextIcon size={24} /> : kind === 'cli' ? <TerminalIcon size={24} /> : kind === 'mcp' ? <PlugIcon size={24} /> : <GearIcon size={24} />}</span>
        <span className="tt-capability-source">{source(row)}</span>
        <div className="tt-capability-state">{row.mutable ? <Switch aria-label={t('agent.capabilities.enable', { name: row.name })} checked={row.enabled} disabled={!!saving} loading={saving === row.name} onChange={enabled => { void change(row, enabled) }} /> : row.state ? <span className={'tt-capability-connection ' + row.state}><i aria-hidden="true" />{t('agent.capabilities.mcp.' + row.state)}</span> : <span className="tt-capability-fixed">{t('capabilities.fixed')}</span>}</div>
      </div>
      <button type="button" className="tt-capability-open" onClick={() => { setSelectedName(row.name); setReference('') }}><strong>{label(row)}</strong></button>
      {row.description && <p className="tt-capability-description">{row.description}</p>}
      <div className="tt-capability-cardfooter"><button type="button" className="tt-act" onClick={() => { setSelectedName(row.name); setReference('') }}>{t(kind === 'skills' ? 'agent.capabilities.content' : kind === 'mcp' ? 'agent.capabilities.connectionDetails' : row.commands ? 'capabilities.commands' : 'agent.capabilities.parameters')}</button>
        <div>{kind === 'mcp' && row.state !== 'connected' && <button type="button" className="tt-act" disabled={!!saving} onClick={() => { void connect(row) }}>{t(saving === row.name ? 'capabilities.connecting' : 'capabilities.connect')}</button>}{row.managed && <button type="button" className="tt-act" disabled={!!saving} onClick={() => setEditor({ entry: row.managed })}><PencilIcon size={14} />{t('capabilities.edit')}</button>}</div>
      </div>
    </article>)}</div>
    {selected && (phone ? <MobileSubPage title={label(selected)} onBack={() => setSelectedName('')}><div className="tt-capability-detail-scroll">{detail}</div></MobileSubPage>
      : <Modal open title={label(selected)} footer={null} onCancel={() => setSelectedName('')} width="min(var(--content-form), calc(100vw - var(--sp-5) * 2))" className="tt-capability-modal">{detail}</Modal>)}
    {editor && kind !== 'tools' && <CapabilityEditor kind={kind as ManagedKind} {...editor} onClose={() => setEditor(null)} onSaved={data => { setCatalog(data); setEditor(null); setError('') }} />}
  </section>
}
