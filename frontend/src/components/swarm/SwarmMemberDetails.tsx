import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { CloseIcon } from '../../icons'
import { openAgentPage } from '../agent/agent-page-route'
import { nodeApi } from '../cluster/node-url'
import Markdown from '../markdown/Markdown'
import type { SwarmTeamMember } from './swarm-members'
import type { SwarmMember } from './swarm-protocol'

type Round = { id: number; task_id: string; revision: number; request_text: string | null; sourceUnavailable?: boolean; state: string }
type MemberDetail = { member: SwarmMember & { duty: string }; rounds: { items: Round[]; hasMore: boolean; nextBefore: number | null } }

export default function SwarmMemberDetails({ swarmId, member, onClose, compact = false }: { swarmId: string; member: SwarmTeamMember; onClose: () => void; compact?: boolean }) {
  const { t, locale } = useI18n()
  const path = `/agent/swarms/${encodeURIComponent(swarmId)}/members/${encodeURIComponent(member.id)}`
  const scope = nodeApi(path)
  const latestScope = useRef(scope); latestScope.current = scope
  const generation = useRef(0)
  const [detail, setDetail] = useState<MemberDetail | null>(null), [busy, setBusy] = useState(false), [failed, setFailed] = useState(false)
  const load = async (before?: number) => {
    const request = ++generation.current
    setBusy(true); setFailed(false)
    try {
      const response = await api('GET', path + (before ? '?before=' + before : ''))
      const next = response.data as MemberDetail
      if (generation.current !== request || latestScope.current !== scope || nodeApi(path) !== scope) return
      if (next.member.id !== member.id || next.member.swarm_id !== swarmId) throw new Error('MEMBER_BINDING_CHANGED')
      setDetail(prior => before && prior ? { ...next, rounds: { ...next.rounds, items: [...prior.rounds.items, ...next.rounds.items] } } : next)
    } catch { if (generation.current === request && latestScope.current === scope && nodeApi(path) === scope) setFailed(true) }
    finally { if (generation.current === request && latestScope.current === scope && nodeApi(path) === scope) setBusy(false) }
  }
  useEffect(() => {
    setDetail(null); void load()
    return () => { generation.current++ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope])
  return <section className="swarm-member-detail" data-compact={compact} aria-label={t('swarm.member.details')}>
    {!compact && <div className="swarm-panel-head"><h3>{member.name}</h3><button type="button" className="tt-act" aria-label={t('common.close')} onClick={onClose}><CloseIcon /></button></div>}
    <Markdown>{detail?.member.duty || member.duty}</Markdown>
    {member.work?.task_id && <button type="button" className="tt-act" onClick={() => openAgentPage('tasks', member.work!.task_id!)}>{t('swarm.relations.openWork')}</button>}
    {failed && <p role="alert">{t('swarm.member.loadFailed')} <button type="button" className="tt-act" disabled={busy} onClick={() => void load()}>{t('agent.retry')}</button></p>}
    {busy && !detail && <p role="status">{t('common.loading')}</p>}
    {detail && <><h4>{t('swarm.member.rounds')}</h4>{!detail.rounds.items.length && <p className="swarm-note">{t('swarm.member.noRounds')}</p>}
      {detail.rounds.items.map(round => <details key={round.id}><summary>{t('swarm.member.round', { number: new Intl.NumberFormat(locale).format(round.revision) })} · {t(`swarm.managed.state.${round.state}`)}</summary>
        {round.sourceUnavailable ? <p className="swarm-note">{t('swarm.member.sourceUnavailable')}</p> : round.request_text && <Markdown>{round.request_text}</Markdown>}
        {!round.sourceUnavailable && <button type="button" className="tt-act" onClick={() => openAgentPage('tasks', round.task_id)}>{t('swarm.relations.openWork')}</button>}
      </details>)}
      {detail.rounds.hasMore && detail.rounds.nextBefore && <button type="button" className="tt-act" disabled={busy} onClick={() => void load(detail.rounds.nextBefore!)}>{t('swarm.member.earlier')}</button>}
    </>}
  </section>
}
