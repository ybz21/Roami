import type { SwarmMember, SwarmSnapshot, SwarmWork } from './swarm-protocol'

export type SwarmTeamMember = {
  id: string; name: string; executor: string; duty: string; state: string; work?: SwarmWork; registered?: SwarmMember
}

export function swarmMembers(data: SwarmSnapshot): SwarmTeamMember[] {
  if (data.memberProtocol !== undefined && ![0, 1].includes(data.memberProtocol)) return []
  if (!data.members) return data.memberProtocol === 1 ? [] : data.work.map(work => ({ id: work.id, name: work.member_name, executor: work.executor, duty: work.title, state: work.state, work }))
  return data.members.filter(member => member.swarm_id === data.id).map(member => {
    const candidate = data.work.find(work => work.id === member.workId)
    const bound = candidate && candidate.executor === member.executor
      && (!candidate.memberId || candidate.memberId === member.id)
      && candidate.task_id === member.taskId && candidate.revision === member.taskRevision
      && (!member.instance?.taskId || member.instance.taskId === candidate.task_id)
    const work = bound ? candidate : undefined
    const unavailable = Boolean(member.workId && !work)
    return { id: member.id, name: member.name, executor: member.executor, duty: member.dutyPreview, state: unavailable ? 'unknown' : member.instance && ['closed', 'closing', 'unknown'].includes(member.instance.state) ? member.instance.state : member.state, work, registered: member }
  })
}

export function swarmMember(members: SwarmTeamMember[], selection: string) {
  // Old drafts may use the current work ID; only an exact binding can migrate them.
  return members.find(member => member.id === selection) || members.find(member => member.work?.id === selection)
}
