import { expect, it } from 'vitest'
import { swarmSessionMembership } from './swarm-session-membership'
import type { SwarmSnapshot, SwarmWork } from './swarm-protocol'

it('uses actual attempt sessions and stable group IDs, excluding archived groups and pending work with no session', () => {
  const work = (state: SwarmWork['state'], sessionId?: string) => ({ state, attempt: sessionId ? { sessionId } : null }) as SwarmWork
  const groups = [
    { id: 'sw-first', name: 'Same name', archived: false, work: [work('running', 'actual-session'), work('queued'), work('blocked')] },
    { id: 'sw-second', name: 'Same name', archived: false, work: [work('waiting_user', 'second-session')] },
    { id: 'sw-old', name: 'Old', archived: true, work: [work('running', 'old-session')] },
  ] as SwarmSnapshot[]
  expect(swarmSessionMembership(groups)).toEqual({
    sessions: { 'actual-session': { swarm: 'sw-first', label: 'Same name', role: 'member' }, 'second-session': { swarm: 'sw-second', label: 'Same name', role: 'member' } },
    pending: { 'sw-first': 2, 'sw-second': 0 },
  })
})
