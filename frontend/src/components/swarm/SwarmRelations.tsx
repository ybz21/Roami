import { useI18n } from '../../i18n'
import { swarmMembers } from './swarm-members'
import { swarmStateToken, type SwarmSnapshot, type SwarmWork } from './swarm-protocol'

export default function SwarmRelations({ data, selected, onSelect, onMain, onWork, onChat, onMember }: {
  data: SwarmSnapshot; selected: string; onSelect: (id: string) => void; onMain: () => void; onWork: (item: SwarmWork) => void; onChat: (id: string) => void; onMember?: (id: string) => void
}) {
  const { t } = useI18n()
  const members = swarmMembers(data)
  const byWork = new Map(members.filter(member => member.work).map(member => [member.work!.id, member]))
  const byId = new Map(data.work.map(item => [item.id, item]))
  return <section className="swarm-relations" aria-label={t('swarm.relations.title')}>

    {data.mainConversationId ? <div className="swarm-relations-main" data-members={Boolean(members.length)}>
      <button type="button" className="swarm-relation-main" aria-pressed={selected === 'main'} onClick={onMain}>
        <strong>Roami Main</strong><span>{t('swarm.relations.coordinates')}</span>
      </button>
    </div> : <p className="swarm-note">{t('swarm.relations.mainUnavailable')}</p>}
    {!members.length ? <p className="swarm-note">{t(data.memberProtocol === 1 && !data.members || data.memberProtocol !== undefined && ![0, 1].includes(data.memberProtocol) ? 'swarm.member.registryUnavailable' : 'swarm.managed.planning')}</p> : <div className="swarm-relations-members" data-coordinated={Boolean(data.mainConversationId)}>
      {members.map(member => {
        const item = member.work
        const upstream = (item?.dependencies || []).map(dep => ({ id: dep.upstreamId, work: byId.get(dep.upstreamId) }))
        const downstream = data.work.filter(other => other.dependencies.some(dep => dep.upstreamId === item?.id))
        return <article className="swarm-relation-member" key={member.id} data-selected={selected === member.id || selected === item?.id}>
          <header><button type="button" className="tt-act" aria-pressed={selected === member.id || selected === item?.id} onClick={() => onSelect(member.id)}>{member.name}</button><small>{member.executor === 'native' ? 'Roami' : member.executor}</small></header>
          <p className="swarm-relation-duty">{member.duty}</p>
          <span className="swarm-state" style={{ color: `var(${swarmStateToken(member.state)})` }}>{t(`swarm.managed.state.${member.state}`)}</span>
          {item && <details><summary>{t('swarm.relations.dependencies')}</summary><dl>
            <div><dt>{t('swarm.relations.upstream')}</dt><dd>{!upstream.length ? <span>{t('swarm.relations.none')}</span> : upstream.map(dep => dep.work && byWork.has(dep.id) ? <button type="button" className="tt-act" key={dep.id} onClick={() => onSelect(byWork.get(dep.id)!.id)}>{dep.work.member_name}<small>{dep.work.title}</small></button> : <span key={dep.id}>{t('swarm.relations.unavailable')}</span>)}</dd></div>
            <div><dt>{t('swarm.relations.downstream')}</dt><dd>{!downstream.length ? <span>{t('swarm.relations.none')}</span> : downstream.filter(next => byWork.has(next.id)).map(next => <button type="button" className="tt-act" key={next.id} onClick={() => onSelect(byWork.get(next.id)!.id)}>{next.member_name}<small>{next.title}</small></button>)}</dd></div>
          </dl></details>}
          <div className="swarm-relation-actions">
            {member.registered && onMember ? <button type="button" className="tt-act" onClick={() => onMember(member.id)}>{t('swarm.member.details')}</button> : item && <button type="button" className="tt-act" onClick={() => onWork(item)}>{t(item.task_id ? 'swarm.relations.openWork' : 'swarm.relations.viewPlan')}</button>}
            <button type="button" className="tt-act" onClick={() => onChat(member.registered || item?.task_id ? member.id : 'main')}>{t(member.registered || item?.task_id ? 'swarm.relations.chat' : 'swarm.relations.adjustMain')}</button>
          </div>
        </article>
      })}
    </div>}
  </section>
}
