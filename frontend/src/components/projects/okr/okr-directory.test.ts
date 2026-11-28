import { expect, it } from 'vitest'
import type { SwarmSnapshot } from '../../swarm/swarm-protocol'
import { projectSwarmDirectory } from './okr-directory'
import type { OkrOverview } from './okr-workspace'

it('uses the exact confirmed Swarm and project even if a project contains several groups', () => {
  const overview = { projectId: 'promo', swarm: 'confirmed' } as OkrOverview
  const team = (id: string, projectId: string, archived = false) =>
    ({ id, target: { projectId }, archived, name: 'Production', sessionIds: ['member'] } as SwarmSnapshot)
  expect(projectSwarmDirectory([overview], [team('other', 'promo'), team('confirmed', 'promo')]))
    .toEqual([{ projectId: 'promo', id: 'confirmed', name: 'Production', sessionIds: ['member'] }])
  expect(projectSwarmDirectory([overview], [team('confirmed', 'other')])).toEqual([])
  expect(projectSwarmDirectory([overview], [team('confirmed', 'promo', true)])).toEqual([])
})
