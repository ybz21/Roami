import { useI18n } from '../../i18n'
import { swarmStateToken } from './swarm-protocol'
import type { SwarmTeamMember, SwarmRoleBinding } from './swarm-members'

export default function SwarmConversations({ members, historical = [], unbound = [], selected, onSelect }: { members: SwarmTeamMember[]; historical?: SwarmTeamMember[]; unbound?: SwarmRoleBinding[]; selected: string; onSelect: (id: string) => void }) {
  const { t, locale } = useI18n()
  const row = (member: SwarmTeamMember) => <button type="button" key={member.id} aria-label={member.name} aria-pressed={selected === member.id} onClick={() => onSelect(member.id)}>
    <strong>{member.name}</strong><small style={{ color: `var(${swarmStateToken(member.state)})` }}>{t(`swarm.managed.state.${member.state}`)}</small>
  </button>
  return <nav className="swarm-conversations" aria-label={t('swarm.conversation.list')}>
    <button type="button" aria-label={t('swarm.managed.tab.chat')} aria-pressed={selected === 'group'} onClick={() => onSelect('group')}><strong>{t('swarm.managed.tab.chat')}</strong><small>{t('swarm.conversation.groupRole')}</small></button>
    <button type="button" aria-label={t('swarm.conversation.main')} aria-pressed={selected === 'main'} onClick={() => onSelect('main')}><strong>{t('swarm.conversation.main')}</strong><small>{t('swarm.conversation.mainRole')}</small></button>
    {Boolean(members.length) && <h3>{t('swarm.conversation.members')}</h3>}
    {members.map(row)}
    {Boolean(unbound.length) && <p className="swarm-note">{t('swarm.member.rolesUnbound', { names: new Intl.ListFormat(locale, { style: 'short', type: 'conjunction' }).format(unbound.map(role => role.name)) })}</p>}
    {Boolean(historical.length) && <details className="swarm-conversation-history" open={historical.some(member => member.id === selected) || undefined}><summary>{t('swarm.member.history', { count: new Intl.NumberFormat(locale).format(historical.length) })}</summary>{historical.map(row)}</details>}

  </nav>
}
