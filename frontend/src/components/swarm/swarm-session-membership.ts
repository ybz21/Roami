import type { SwarmSnapshot } from './swarm-protocol'

export type SwarmSessionMember = { swarm: string; label: string; role: 'member' }
export function swarmSessionMembership(groups: SwarmSnapshot[]) {
  const sessions: Record<string, SwarmSessionMember> = {}, pending: Record<string, number> = {}
  for (const group of groups) {
    if (group.archived) continue
    pending[group.id] = group.work.filter(work => ['queued', 'blocked'].includes(work.state)).length
    for (const work of group.work) {
      const session = work.attempt?.sessionId
      if (session) sessions[session] = { swarm: group.id, label: group.name, role: 'member' }
    }
  }
  return { sessions, pending }
}
