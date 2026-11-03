import { api } from '../../api'
import { nodeApi } from '../cluster/node-url'
import type { SwarmSnapshot } from './swarm-protocol'

const pending = new Map<string, Promise<SwarmSnapshot[]>>()
export function loadSwarmDirectory(): Promise<SwarmSnapshot[]> {
  const scope = nodeApi('/agent/swarms')
  let request = pending.get(scope)
  if (!request) {
    const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 15000)
    request = api('GET', '/agent/swarms', undefined, { signal: abort.signal }).then(value => value.data as SwarmSnapshot[]).finally(() => { clearTimeout(timeout); pending.delete(scope) })
    pending.set(scope, request)
  }
  return request
}
