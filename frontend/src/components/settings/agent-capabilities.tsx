import { useEffect, useState } from 'react'
import { Button, Input, Spin, Switch, Tag } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useCurrentNodeId } from '../cluster/node-url'
import './agent-settings.css'

type Skill = { name: string; text: string; version: string; source: string; enabled: boolean }
type Tool = { name: string; description: string; schema: unknown; effect: string; main: boolean; enabled: boolean }
type Server = { name: string; transport: string; state: string; tools: number }
type Catalog = { skills: Skill[]; tools: Tool[]; mcp: Server[] }
export function AgentCapabilities({ kind }: { kind: 'skills' | 'tools' }) {
  const node = useCurrentNodeId()
  return <CapabilityList key={`${node || 'local'}:${kind}`} kind={kind} />
}
function CapabilityList({ kind }: { kind: 'skills' | 'tools' }) {
  const { t } = useI18n()
  const [catalog, setCatalog] = useState<Catalog | null>(null), [error, setError] = useState(''), [query, setQuery] = useState(''), [saving, setSaving] = useState(''), [version, setVersion] = useState(0)
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
    <p className="agent-settings-hint">{t(`agent.capabilities.${kind}Hint`)}</p>
    <p className="agent-settings-hint">{t('agent.capabilities.effectHint')}</p>
    <Input aria-label={t('agent.capabilities.search')} placeholder={t('agent.capabilities.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear />
    {error && <div className="agent-settings-error" role="alert">{error}<Button onClick={() => setVersion(v => v + 1)}>{t('agent.retry')}</Button></div>}
    {catalog && <p className="agent-settings-hint">{t('agent.capabilities.count', { count: items.length })}</p>}
    {catalog && !items.length && <p className="agent-settings-hint">{t('agent.capabilities.empty')}</p>}
    {items.map(item => <article className="agent-capability-row" key={item.name}>
      <div className="agent-capability-head"><strong>{item.name}</strong><Switch aria-label={t('agent.capabilities.enable', { name: item.name })} checked={item.enabled} loading={saving === item.name} disabled={!!saving} onChange={enabled => { void change(item.name, enabled) }} /></div>
      <div className="agent-capability-tags"><Tag>{t(item.enabled ? 'agent.capabilities.enabled' : 'agent.capabilities.disabled')}</Tag>{'source' in item ? <Tag>{t(`agent.capabilities.source.${item.source}`)}</Tag> : <><Tag>{t(item.main ? 'agent.capabilities.mainWorker' : 'agent.capabilities.workerOnly')}</Tag><Tag>{t(item.effect === 'read' ? 'agent.capabilities.read' : 'agent.capabilities.write')}</Tag></>}</div>
      {'description' in item && <p className="agent-settings-hint">{item.description}</p>}
      <details><summary>{t('text' in item ? 'agent.capabilities.content' : 'agent.capabilities.parameters')}</summary><pre>{'text' in item ? item.text : JSON.stringify(item.schema, null, 2)}</pre>{'version' in item && <p className="agent-settings-hint">{t('agent.capabilities.version', { version: item.version.slice(0, 12) })}</p>}</details>
    </article>)}
    {kind === 'tools' && catalog && <section className="agent-capability-servers"><h3>{t('agent.capabilities.mcp')}</h3><p className="agent-settings-hint">{t('agent.capabilities.mcpHint')}</p>{!catalog.mcp.length && <p className="agent-settings-hint">{t('agent.capabilities.noMcp')}</p>}{catalog.mcp.map(server => <div key={server.name} className="agent-capability-row"><strong>{server.name}</strong><p className="agent-settings-hint">{server.transport} · {t(`agent.capabilities.mcp.${server.state}`)} · {t('agent.capabilities.count', { count: server.tools })}</p></div>)}</section>}
  </section>
}
