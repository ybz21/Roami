import { api } from '../../api'
import { nodeApi } from '../cluster/node-url'

type Entry = { value?: unknown; updated: number; bytes: number; stale?: boolean; pending?: Promise<any>; abort?: AbortController }
const entries = new Map<string, Entry>()
const MAX_BYTES = 16 * 1024 * 1024, MAX_ENTRIES = 48, MAX_AGE = 10 * 60_000
let epoch = 0

export const agentDataKey = (path: string, method = 'GET') => method + ' ' + nodeApi(path)
export const agentCacheEpoch = () => epoch

function trim() {
  let bytes = [...entries.values()].reduce((sum, entry) => sum + entry.bytes, 0)
  for (const [key, entry] of entries) {
    if (entry.pending) continue
    if (bytes <= MAX_BYTES && entries.size <= MAX_ENTRIES && Date.now() - entry.updated < MAX_AGE) continue
    entries.delete(key); bytes -= entry.bytes
  }
}

export function peekAgentData<T>(key: string): T | undefined {
  trim()
  const entry = entries.get(key)
  if (entry) { entries.delete(key); entries.set(key, entry) }
  return entry?.value as T | undefined
}

export function storeAgentData(key: string, value: unknown, owner = epoch) {
  if (owner !== epoch) return
  // Budget UTF-16 payload plus object overhead; active views own their data independently.
  const bytes = JSON.stringify(value).length * 3
  if (bytes > MAX_BYTES) { entries.delete(key); return }
  const entry = entries.get(key) || { updated: 0, bytes: 0 }
  entry.value = value; entry.updated = Date.now(); entry.stale = false
  entry.bytes = bytes
  entries.delete(key); entries.set(key, entry); trim()
}

export function invalidateAgentData(key: string) {
  const entry = entries.get(key)
  if (!entry) return
  entry.abort?.abort()
  entries.set(key, { value: entry.value, bytes: entry.bytes, updated: entry.updated, stale: true })
}

export function clearAgentDataCache() {
  epoch++
  for (const entry of entries.values()) entry.abort?.abort()
  entries.clear()
}

export async function loadAgentData<T>(path: string, freshFor = 0, method = 'GET'): Promise<T> {
  const key = agentDataKey(path, method), cached = peekAgentData<T>(key)
  let entry = entries.get(key)
  if (entry?.pending) return entry.pending
  if (cached !== undefined && entry && !entry.stale && Date.now() - entry.updated < freshFor) return cached
  entry ||= { updated: 0, bytes: 0 }
  const request = entry, owner = epoch, abort = new AbortController()
  entries.set(key, request)
  request.abort = abort
  const timeout = setTimeout(() => abort.abort(), 15_000)
  abort.signal.addEventListener('abort', () => clearTimeout(timeout), { once: true })
  request.pending = api(method, path, undefined, { signal: abort.signal }).then(({ data }) => {
    if (owner !== epoch || entries.get(key) !== request || abort.signal.aborted) throw new DOMException('Aborted', 'AbortError')
    storeAgentData(key, data, owner)
    return data as T
  }).finally(() => {
    clearTimeout(timeout)
    if (entries.get(key) === request) { request.pending = undefined; request.abort = undefined }
    trim()
  })
  return request.pending
}
