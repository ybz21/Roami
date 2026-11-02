import { lazy, Suspense } from 'react'
import { Select, Spin, Tabs } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { useCurrentNodeId } from '../cluster/node-url'
import { type AgentKind } from '../../agent-kind'
import { AgentCatalog } from './AgentCatalog'
import { CapabilityCatalog } from './CapabilityCatalog'
import './capabilities.css'

const PluginsPanel = lazy(() => import('../plugins/PluginsPanel'))
const CapabilityMarket = lazy(() => import('./CapabilityMarket'))
const ModelHub = lazy(() => import('./ModelHub'))
const kinds = ['models', 'agents', 'plugins', 'skills', 'mcp', 'cli', 'tools', 'markets'] as const
export type CapabilityKind = typeof kinds[number]

export default function CapabilitiesPage({ sub = '', onNav, onLaunchAgent }: { sub?: string; onNav: (route: string) => void; onLaunchAgent?: (kind: AgentKind) => Promise<void> }) {
  const { t } = useI18n()
  const { phone } = useLayout()
  const node = useCurrentNodeId()
  const [requested, ...rest] = sub.split('/')
  const active = kinds.includes(requested as CapabilityKind) ? requested as CapabilityKind : 'agents'
  const content = (kind: CapabilityKind) => kind === 'models' ? <Suspense fallback={<Spin />}><ModelHub sub={rest.join('/')} onNav={onNav} /></Suspense> : kind === 'agents' ? <AgentCatalog initialKind={rest[0]} initialSection={rest[1]} onSelect={id => onNav('capabilities/agents' + (id ? '/' + id : ''))} onLaunch={onLaunchAgent} /> : kind === 'plugins'
    ? <Suspense fallback={<Spin />}><PluginsPanel initialId={rest.join('/') || undefined} onSelect={id => onNav('capabilities/plugins' + (id ? '/' + id : ''))} /></Suspense>
    : kind === 'markets' ? <Suspense fallback={<Spin />}><CapabilityMarket /></Suspense> : <CapabilityCatalog kind={kind} />
  return <div className="tt-capabilities" key={node || 'local'}>
    {!phone && <div className="tt-pagehead"><div className="ttl"><h2>{t('nav.capabilities')}</h2></div></div>}
    {phone ? <><div className="tt-capability-mobile-category"><Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('nav.capabilities')} value={active} options={kinds.map(kind => ({ value: kind, label: t('capabilities.tab.' + kind) }))} onChange={kind => onNav('capabilities/' + kind)} /></div><div className="tt-capability-mobile-content">{content(active)}</div></> : <Tabs className="tt-capability-tabs" activeKey={active} onChange={kind => onNav('capabilities/' + kind)} destroyInactiveTabPane items={kinds.map(kind => ({ key: kind, label: t('capabilities.tab.' + kind), children: content(kind) }))} />}
  </div>
}
