import { describe, expect, it } from 'vitest'
import { swarmMember, swarmMembers, swarmRoleMembers } from './swarm-members'
import type { SwarmMember, SwarmSnapshot, SwarmWork } from './swarm-protocol'

const work: SwarmWork = { id: 'work', memberId: 'role', member_name: 'Writer', executor: 'codex', title: 'Current request', goal: 'Goal', acceptance: 'Verify', integration: 0, task_id: 'task', revision: 3, state: 'waiting_user', dispatch_error: null, dependencies: [], attempt: { runId: 'run-3', state: 'verifying' } }
const member: SwarmMember = { id: 'role', swarm_id: 'sw-team', name: 'Writer', executor: 'codex', dutyPreview: 'Long-lived writing role', workId: 'work', taskId: 'task', taskRevision: 3, state: 'waiting_user', memoryPath: 'members/role/memory.md', roundCount: 3 }
function snapshot(): SwarmSnapshot { return { id: 'sw-team', name: 'Team', goal: 'Goal', mainConversationId: 'main', revision: 4, sequence: 10, paused: false, archived: false, state: 'review', target: {}, posts: [], mainMessages: [], memberProtocol: 1, members: [{ ...member }], work: [{ ...work }] } }

describe('stable role selection', () => {
  it('three execution rounds remain one registered member and use the current exact work', () => {
    const data = snapshot(), members = swarmMembers(data)
    expect(members).toHaveLength(1)
    expect(members[0]).toMatchObject({ id: 'role', duty: 'Long-lived writing role', registered: { roundCount: 3 }, work: { revision: 3 } })
    expect(swarmMember(members, 'work')?.id).toBe('role')
    expect(swarmMember(members, 'old-work')).toBeUndefined()
  })
  it('keeps an unassigned role visible without inventing a task or a running instance', () => {
    const data = snapshot(); data.members = [{ ...member, workId: null, taskId: null, taskRevision: null, state: 'unassigned', roundCount: 0 }]; data.work = []
    expect(swarmMembers(data)).toMatchObject([{ id: 'role', state: 'unassigned', work: undefined }])
  })
  it.each([
    { taskId: 'another-task' }, { taskRevision: 2 }, { executor: 'claude' }, { workId: 'another-work' },
  ])('never opens a work whose current role binding changed: %j', changes => {
    const data = snapshot(); Object.assign(data.members![0], changes)
    expect(swarmMembers(data)[0]).toMatchObject({ state: 'unknown', work: undefined })
    expect(swarmMember(swarmMembers(data), 'work')).toBeUndefined()
  })
  it('rejects cross-project registry entries and does not guess from duplicate names', () => {
    const data = snapshot(); data.members!.push({ ...member, id: 'other-role', swarm_id: 'other-team' })
    data.work.push({ ...work, id: 'old-work', memberId: 'other-role' })
    expect(swarmMembers(data).map(member => member.id)).toEqual(['role'])
    expect(swarmMember(swarmMembers(data), 'old-work')).toBeUndefined()
  })
  it('does not fall back to work-derived people when the new protocol is incomplete', () => {
    const data = snapshot(); delete data.members
    expect(swarmMembers(data)).toEqual([])
    data.memberProtocol = 2; expect(swarmMembers(data)).toEqual([])
    delete data.memberProtocol
    expect(swarmMembers(data)).toMatchObject([{ id: 'work' }])
  })
  it('a closed member instance stays closed even if the task previously succeeded', () => {
    const data = snapshot(); data.work[0].state = 'succeeded'; data.members![0].state = 'succeeded'
    data.members![0].instance = { id: 'instance', conversationId: 'cid', branchId: 'branch', taskId: 'task', nativeSessionId: 'native', state: 'closed' }
    expect(swarmMembers(data)[0].state).toBe('closed')
  })
})

it('binds desired roles only by exact member identity and preserves all historical records', () => {
  const data = snapshot(); data.target.projectId = 'project'
  data.members!.push({ ...member, id: 'old-role', name: 'Writer-r1', workId: null, taskId: null, taskRevision: null, state: 'unknown' })
  const before = JSON.stringify(data)
  const result = swarmRoleMembers(data, [{ id: 'writer', name: 'Content', duty: 'Daily content', executor: 'codex', memberId: 'role' }], 'project')
  expect(result.current.map(member => [member.id, member.name])).toEqual([['role', 'Content']])
  expect(result.current[0].work?.task_id).toBe('task')
  expect(result.historical.map(member => [member.id, member.state])).toEqual([['old-role', 'unknown']])
  expect(JSON.stringify(data)).toBe(before)
})

it('never guesses bindings from matching names, labels or task IDs', () => {
  const data = snapshot(); data.target.projectId = 'project'
  const roles = [{ id: 'role', name: 'Writer', duty: 'Write', executor: 'codex', memberId: 'task' }]
  const result = swarmRoleMembers(data, roles, 'project')
  expect(result.current).toEqual([])
  expect(result.historical).toHaveLength(1)
  expect(result.unbound).toEqual(roles)
  expect(swarmRoleMembers(data, [{ ...roles[0], memberId: 'role' }], 'other-project').current).toEqual([])
  expect(swarmRoleMembers(data, [{ ...roles[0], memberId: 'role', executor: 'native' }], 'project').current).toEqual([])
})

it('preserves unassigned member identities and rejects duplicate role bindings', () => {
  const data = snapshot(); data.target.projectId = 'project'; data.members![0] = { ...member, workId: null, taskId: null, taskRevision: null, state: 'unassigned' }; data.work = []
  const role = { id: 'writer', name: 'Content', duty: 'Write', executor: 'codex', memberId: 'role' }
  expect(swarmRoleMembers(data, [role], 'project').current[0]).toMatchObject({ id: 'role', state: 'unassigned', work: undefined })
  const duplicate = swarmRoleMembers(data, [role, { ...role, id: 'editor' }], 'project')
  expect(duplicate.current).toEqual([])
  expect(duplicate.unbound).toHaveLength(2)
})
