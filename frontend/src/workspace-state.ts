export type StatePolicy = 'view' | 'draft' | 'cache'
type Entry = { path: readonly string[]; value: unknown; policy: StatePolicy; bytes: number }
type Listener = () => void

// Snapshots contain data only; runtime resources stay with their owning view.
function dataBytes(value: unknown, seen = new Set<object>()): number {
  if (value == null) return 0
  if (typeof value === 'string') return value.length * 2
  if (typeof value === 'number' && !Number.isFinite(value)) throw new TypeError('View state numbers must be finite')
  if (typeof value === 'boolean' || typeof value === 'number') return 8
  if (typeof value !== 'object' || seen.has(value)) throw new TypeError('View state must be acyclic data')
  const prototype = Object.getPrototypeOf(value)
  if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) throw new TypeError('View state must contain plain data')
  seen.add(value)
  let bytes = 0
  for (const [key, item] of Object.entries(value)) bytes += key.length * 2 + dataBytes(item, seen)
  seen.delete(value)
  return bytes
}
const within = (path: readonly string[], parent: readonly string[]) => parent.every((part, index) => path[index] === part)

export class WorkspaceStateStore {
  private entries = new Map<string, Entry>()
  private listeners = new Map<string, Set<Listener>>()
  private cacheBytes = 0
  private cacheEntries = 0
  constructor(private limits = { cacheBytes: 2 * 1024 * 1024, cacheEntries: 200 }) {}

  node(id: string | null) { return this.scope('node', JSON.stringify(id)) }
  scope(...path: string[]) { return new ViewStateScope(this, path) }
  has(path: readonly string[]) { return this.entries.has(JSON.stringify(path)) }
  read<T>(path: readonly string[]): T | undefined {
    const key = JSON.stringify(path), entry = this.entries.get(key)
    if (entry?.policy === 'cache') { this.entries.delete(key); this.entries.set(key, entry) }
    return entry?.value as T | undefined
  }
  write<T>(path: readonly string[], value: T, policy: StatePolicy = 'view') {
    const key = JSON.stringify(path), previous = this.entries.get(key)
    if (previous && Object.is(previous.value, value) && previous.policy === policy) return
    const bytes = dataBytes(value)
    this.removeEntry(key)
    this.entries.set(key, { path, value, policy, bytes })
    if (policy === 'cache') { this.cacheBytes += bytes; this.cacheEntries++ }
    this.listeners.get(key)?.forEach(listener => listener())
    this.trimCache()
  }
  delete(path: readonly string[]) {
    const key = JSON.stringify(path)
    if (this.removeEntry(key)) this.listeners.get(key)?.forEach(listener => listener())
  }
  subscribe(path: readonly string[], listener: Listener) {
    const key = JSON.stringify(path)
    let listeners = this.listeners.get(key)
    if (!listeners) { listeners = new Set(); this.listeners.set(key, listeners) }
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
      if (!listeners.size) this.listeners.delete(key)
      this.trimCache()
    }
  }
  clear(path: readonly string[], preserveDrafts = false) {
    const protectedView = preserveDrafts && [...this.entries.values()].some(entry => within(entry.path, path) && entry.policy === 'draft')
    for (const [key, entry] of this.entries) {
      if (!within(entry.path, path) || protectedView && entry.policy !== 'cache') continue
      this.removeEntry(key); this.listeners.get(key)?.forEach(listener => listener())
    }
  }
  hasDrafts() { for (const entry of this.entries.values()) if (entry.policy === 'draft') return true; return false }
  stats() {
    return { entries: this.entries.size, cacheBytes: this.cacheBytes, cacheEntries: this.cacheEntries, subscriptions: this.listeners.size }
  }
  private removeEntry(key: string) {
    const entry = this.entries.get(key)
    if (!entry) return false
    if (entry.policy === 'cache') { this.cacheBytes -= entry.bytes; this.cacheEntries-- }
    return this.entries.delete(key)
  }
  private trimCache() {
    for (const [key, entry] of this.entries) {
      if (this.cacheBytes <= this.limits.cacheBytes && this.cacheEntries <= this.limits.cacheEntries) break
      if (entry.policy === 'cache' && !this.listeners.has(key)) this.removeEntry(key)
    }
  }
}

export class ViewStateScope {
  constructor(readonly store: WorkspaceStateStore, readonly path: readonly string[]) {}
  child(...path: string[]) { return this.store.scope(...this.path, ...path) }
  has(key: string) { return this.store.has([...this.path, key]) }
  get<T>(key: string) { return this.store.read<T>([...this.path, key]) }
  set<T>(key: string, value: T, policy?: StatePolicy) { this.store.write([...this.path, key], value, policy) }
  delete(key: string) { this.store.delete([...this.path, key]) }
  initialize<T>(key: string, value: T, policy?: StatePolicy) { if (!this.has(key)) this.set(key, value, policy) }
  subscribe(key: string, listener: Listener) { return this.store.subscribe([...this.path, key], listener) }
  clear(options?: { preserveDrafts?: boolean }) { this.store.clear(this.path, options?.preserveDrafts) }
}
