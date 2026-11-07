import { useEffect, useState, type ReactNode } from 'react'
import { Button, Select, Spin } from 'antd'
import { loadSwarmDirectory } from './swarm-directory'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { PlusIcon } from '../../icons'
import { pollWhileVisible } from '../../visible-poll'
import { nodeApi } from '../cluster/node-url'
import ManagedSwarm from './ManagedSwarm'
import type { SwarmRoleBinding } from './swarm-members'
import LegacySwarmHistory from './LegacySwarmHistory'
import { NewSwarmModal } from './NewSwarmModal'
import { swarmStateToken, type SwarmSnapshot } from './swarm-protocol'
import './swarm.css'
export { NewSwarmModal } from './NewSwarmModal'

export default function Swarm({ openTerm, initialSwarm, onNav, embedded = false, projectId, onManage, renderMain, mainRequest, onRecipientChange, roles }: { openTerm: (id: string) => void; initialSwarm?: string; onNav?: (id: string | null) => void; embedded?: boolean; projectId?: string; onManage?: () => void; renderMain?: (id: string) => ReactNode; mainRequest?: string; onRecipientChange?: (recipient: string) => void; roles?: SwarmRoleBinding[] }) {
  const { t } = useI18n(), { phone } = useLayout()
  const [list, setList] = useState<SwarmSnapshot[] | null>(null), [error, setError] = useState(false), [creating, setCreating] = useState(false), [archived, setArchived] = useState(false)
  const scope = nodeApi('/agent/swarms')
  useEffect(() => {
    if (initialSwarm) return
    setList(null)
    return pollWhileVisible(async signal => {
      try {
        const value = await loadSwarmDirectory()
        if (!signal.aborted) { setList(prior => JSON.stringify(prior) === JSON.stringify(value) ? prior : value); setError(false) }
      } catch (cause) { if (!signal.aborted) setError(true); throw cause }
    }, 10000).stop
  }, [initialSwarm, scope])
  if (initialSwarm && projectId && !/^sw-[a-f0-9]{32}$/.test(initialSwarm)) return <LegacySwarmHistory projectId={projectId} onManage={onManage || (() => onNav?.(null))} />
  if (initialSwarm) return <ManagedSwarm key={scope + initialSwarm} id={initialSwarm} onBack={() => onNav?.(null)} openTerm={openTerm} embedded={embedded} projectId={projectId} onManage={onManage} renderMain={renderMain} mainRequest={mainRequest} onRecipientChange={onRecipientChange} roles={roles} />
  const shown = list?.filter(item => item.archived === archived)
  return <div className="swarm-directory">
    <header className="tt-pagehead">{!phone && <h2>{t('nav.swarm')}</h2>}<div className="acts"><Select aria-label={t('swarm.managed.filter')} value={archived ? 'archived' : 'active'} onChange={value => setArchived(value === 'archived')} options={[{ value: 'active', label: t('swarm.active') }, { value: 'archived', label: t('swarm.status.archived') }]} /><Button type="primary" icon={<PlusIcon />} onClick={() => setCreating(true)}>{t('swarm.new')}</Button></div></header>
    {error && <p role="alert" className="swarm-stream-error">{t('swarm.managed.reconnecting')}</p>}
    {!list ? <Spin /> : !shown?.length ? <p className="swarm-note">{t('swarm.empty')}</p> : <div className="swarm-directory-list">{shown.map(item => <button type="button" className="swarm-directory-card" key={item.id} onClick={() => onNav?.(item.id)}><strong>{item.name}</strong><span style={{ color: `var(${swarmStateToken(item.state)})` }}>{t(`swarm.managed.state.${item.state}`)}</span><p>{item.goal}</p>{item.work.length > 0 && <small>{t('swarm.memberSummary', { total: item.work.length, alive: item.work.filter(work => ['running', 'preparing'].includes(work.state)).length })}</small>}</button>)}</div>}
    <NewSwarmModal open={creating} onClose={() => setCreating(false)} onDone={id => { if (id) onNav?.(id) }} />
  </div>
}
