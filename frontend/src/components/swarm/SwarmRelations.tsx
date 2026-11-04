import { useI18n } from '../../i18n'
import { swarmStateToken, type SwarmSnapshot } from './swarm-protocol'

export default function SwarmRelations({ data, selected, onSelect, onMain }: {
  data: SwarmSnapshot; selected: string; onSelect: (id: string) => void; onMain: () => void
}) {
  const { t } = useI18n()
  const byId = new Map(data.work.map(item => [item.id, item]))
  return <section className="swarm-relations" aria-label={t('swarm.relations.title')}>
    <h3>{t('swarm.relations.title')}</h3>
    {data.mainConversationId ? <div className="swarm-relations-main" data-members={Boolean(data.work.length)}>
      <button type="button" className="swarm-relation-main" aria-pressed={selected === 'main'} onClick={onMain}>
        <strong>Roami Main</strong><span>{t('swarm.relations.coordinates')}</span>
      </button>
    </div> : <p className="swarm-note">{t('swarm.relations.mainUnavailable')}</p>}
    {!data.work.length ? <p className="swarm-note">{t('swarm.managed.planning')}</p> : <div className="swarm-relations-members" data-coordinated={Boolean(data.mainConversationId)}>
      {data.work.map(item => {
        const upstream = item.dependencies.map(dep => ({ id: dep.upstreamId, work: byId.get(dep.upstreamId) }))
        const downstream = data.work.filter(other => other.dependencies.some(dep => dep.upstreamId === item.id))
        return <article className="swarm-relation-member" key={item.id} data-selected={selected === item.id}>
          <header><button type="button" className="tt-act" aria-pressed={selected === item.id} onClick={() => onSelect(item.id)}>{item.member_name}</button><small>{item.executor === 'native' ? 'Roami' : item.executor}</small></header>
          <p className="swarm-relation-duty">{item.title}</p>
          <span className="swarm-state" style={{ color: `var(${swarmStateToken(item.state)})` }}>{t(`swarm.managed.state.${item.state}`)}</span>
          <dl>
            <div><dt>{t('swarm.relations.upstream')}</dt><dd>{!upstream.length ? <span>{t('swarm.relations.none')}</span> : upstream.map(dep => dep.work ? <button type="button" className="tt-act" key={dep.id} onClick={() => onSelect(dep.id)}>{dep.work.member_name}<small>{dep.work.title}</small></button> : <span key={dep.id}>{t('swarm.relations.unavailable')}</span>)}</dd></div>
            <div><dt>{t('swarm.relations.downstream')}</dt><dd>{!downstream.length ? <span>{t('swarm.relations.none')}</span> : downstream.map(next => <button type="button" className="tt-act" key={next.id} onClick={() => onSelect(next.id)}>{next.member_name}<small>{next.title}</small></button>)}</dd></div>
          </dl>
        </article>
      })}
    </div>}
  </section>
}
