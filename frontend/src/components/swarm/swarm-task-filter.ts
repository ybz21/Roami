import type { SwarmWork } from './swarm-protocol'

export const swarmTaskFilters = ['active', 'all', 'attention', 'ended'] as const
export type SwarmTaskFilter = typeof swarmTaskFilters[number]
const active = new Set(['queued', 'preparing', 'running', 'verifying', 'cancelling'])
const ended = new Set(['succeeded', 'done', 'failed', 'cancelled', 'interrupted'])

export function matchesSwarmTaskFilter(work: SwarmWork, filter: SwarmTaskFilter) {
  if (filter === 'all') return true
  const unconfirmed = ['running', 'preparing'].includes(work.state) && work.attempt?.state === 'unknown'
  if (filter === 'active') return active.has(work.state) && !unconfirmed
  if (filter === 'ended') return ended.has(work.state)
  return unconfirmed || !active.has(work.state) && !['succeeded', 'done', 'cancelled'].includes(work.state)
}
