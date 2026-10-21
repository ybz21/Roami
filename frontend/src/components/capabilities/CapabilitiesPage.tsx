import { lazy, Suspense } from 'react'
import { Spin, Tabs } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { useCurrentNodeId } from '../cluster/node-url'
import { type AgentKind } from '../../agent-kind'
import { AgentCatalog } from './AgentCatalog'
import { CapabilityCatalog } from './CapabilityCatalog'
import './capabilities.css'

const PluginsPanel = lazy(() => import('../plugins/PluginsPanel'))
const kinds = ['agents', 'plugins', 'skills', 'mcp', 'cli', 'tools'] as const
export type CapabilityKind = typeof kinds[number]

export default function CapabilitiesPage({ sub = '', onNav, onLaunchAgent }: { sub?: string; onNav: (route: string) => void; onLaunchAgent?: (kind: AgentKind) => Promise<void> }) {
  const { t } = useI18n()
  const { phone } = useLayout()
  const node = useCurrentNodeId()
  const [requested, ...rest] = sub.split('/')
  const active = kinds.includes(requested as CapabilityKind) ? requested as CapabilityKind : 'agents'
  return <div className="tt-capabilities" key={node || 'local'}>
    {!phone && <div className="tt-pagehead"><div className="ttl"><h2>{t('nav.capabilities')}</h2></div></div>}
    <Tabs className="tt-capability-tabs" activeKey={active} onChange={kind => onNav('capabilities/' + kind)} destroyInactiveTabPane
      items={kinds.map(kind => ({ key: kind, label: t('capabilities.tab.' + kind), children: kind === 'agents' ? <AgentCatalog initialKind={rest[0]} onSelect={id => onNav('capabilities/agents' + (id ? '/' + id : ''))} onLaunch={onLaunchAgent} /> : kind === 'plugins'
        ? <Suspense fallback={<Spin />}><PluginsPanel initialId={rest.join('/') || undefined} onSelect={id => onNav('capabilities/plugins' + (id ? '/' + id : ''))} /></Suspense>
        : <CapabilityCatalog kind={kind} /> }))} />
  </div>
}
