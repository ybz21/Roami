import { nodeApi } from '../cluster/node-url'
import { sessionDraftKey } from '../chat/session-draft'
import type { SwarmTeamMember } from './swarm-members'

export function memberDraft(swarmId: string, member: SwarmTeamMember) {
  const base = 'roami.swarm.draft:' + nodeApi('/agent/swarms/' + swarmId)
  try {
    for (const key of [base + ':thread:' + member.id, base]) {
      const raw = localStorage.getItem(key)
      if (!raw) continue
      const saved = JSON.parse(raw), scope = saved.scope || saved.recipient || 'group'
      if (key === base && ![member.id, member.work?.id].includes(scope)) continue
      return { key, raw, saved }
    }
  } catch { /* An unreadable old draft cannot establish a recipient. */ }
  return null
}

export function transferMemberDraft(swarmId: string, member: SwarmTeamMember, sessionId: string) {
  try {
    const legacy = memberDraft(swarmId, member), destination = sessionDraftKey(sessionId)
    if (!legacy || typeof legacy.saved.draft !== 'string' || !legacy.saved.draft || localStorage.getItem(destination)) return
    const marker = legacy.key + ':native-chat-migration'
    if (localStorage.getItem(marker) === legacy.raw) return
    localStorage.setItem(destination, legacy.saved.draft)
    localStorage.setItem(marker, legacy.raw)
  } catch { /* Preserve the original draft if storage is unavailable. */ }
}
