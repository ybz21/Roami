import { useI18n } from '../../i18n'
import { swarmStateToken } from './swarm-protocol'
import type { SwarmTeamMember } from './swarm-members'

export default function SwarmConversations({ members, selected, onSelect }: { members: SwarmTeamMember[]; selected: string; onSelect: (id: string) => void }) {
  const { t } = useI18n()
  return <nav className="swarm-conversations" aria-label={t('swarm.conversation.list')}>
    <button type="button" aria-label={t('swarm.conversation.main')} aria-pressed={selected === 'main'} onClick={() => onSelect('main')}><strong>{t('swarm.conversation.main')}</strong><small>{t('swarm.conversation.mainRole')}</small></button>
    <button type="button" aria-label={t('swarm.managed.tab.chat')} aria-pressed={selected === 'group'} onClick={() => onSelect('group')}><strong>{t('swarm.managed.tab.chat')}</strong><small>{t('swarm.conversation.groupRole')}</small></button>
    {Boolean(members.length) && <h3>{t('swarm.conversation.members')}</h3>}
    {members.map(member => <button type="button" key={member.id} aria-label={member.name} aria-pressed={selected === member.id} onClick={() => onSelect(member.id)}>
      <strong>{member.name}</strong><small style={{ color: `var(${swarmStateToken(member.state)})` }}>{t(`swarm.managed.state.${member.state}`)}</small>
    </button>)}
  </nav>
}
