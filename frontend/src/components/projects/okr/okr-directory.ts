import { api } from '../../../api'
import { nodeApi } from '../../cluster/node-url'
import type { SwarmSnapshot } from '../../swarm/swarm-protocol'
import type { OkrOverview } from './okr-workspace'

export type ProjectSwarm = { projectId: string; id: string; name: string; sessionIds: string[] }

const pending = new Map<string, Promise<OkrOverview[]>>()
export function loadOkrDirectory(): Promise<OkrOverview[]> {
  const scope = nodeApi('/okr')
  let request = pending.get(scope)
  if (!request) {
    const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 15000)
    request = api('GET', '/okr', undefined, { signal: abort.signal })
      .then(value => (value.data || []) as OkrOverview[])
      .finally(() => { clearTimeout(timeout); pending.delete(scope) })
    pending.set(scope, request)
  }
  return request
}

export function projectSwarmDirectory(okrs: OkrOverview[], swarms: SwarmSnapshot[]): ProjectSwarm[] {
  const teams = new Map(swarms.filter(team => !team.archived).map(team => [team.id, team]))
  return okrs.flatMap(okr => {
    const team = okr.swarm && teams.get(okr.swarm)
    if (!team || team.target.projectId !== okr.projectId) return []
    const sessionIds = team.sessionIds || team.work.flatMap(work => work.attempt?.sessionId || [])
    return [{ projectId: okr.projectId, id: team.id, name: team.name, sessionIds }]
  })
}
