// 轮询会话转录(JSONL)，按**字节偏移**增量拉取，自动归一为 Msg[]。
//
// offset 在这一层是**不透明游标**：只原样回传、只比大小（变小=文件被换过，重来）。
// 后端 2026-08-30 把它从行号改成字节偏移，这里一行没动——行号逼着后端每次轮询
// 从第 1 行重数一遍，一次请求就分配一整个文件（见 backend/api/transcript-read.go）。
// Claude 与 Codex 共用，只是 path 不同(transcript / codex-transcript)。
import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react'
import { api } from '../../api'
import { usePageActive } from '../../page-activity'
import { pollWhileVisible } from '../../visible-poll'
import { useWorkspaceStateStore } from '../../view-state'
import type { ViewStateScope, WorkspaceStateStore } from '../../workspace-state'
import { currentNodeId, useCurrentNodeId } from '../cluster/node-url'
import type { Block, Msg } from './types'
import type { RawStatus } from './status'

export const FIRST_PAGE = 50

type Snapshot = {
  msgs: Msg[]
  err: string
  status: RawStatus
  resolvedFile?: string
  serverPending?: boolean
  hasEarlier: boolean
  offset: number
  before?: number
  tail: number
}
const empty: Snapshot = { msgs: [], err: '', status: {}, hasEarlier: false, offset: 0, tail: FIRST_PAGE }
type Options = { identity?: string; active?: boolean; source?: string; busy?: boolean; interval?: number }
type Reader = { interval: number; adaptive: boolean; busy?: boolean }
type Feed = ReturnType<typeof createFeed>
const openFeeds = new WeakMap<WorkspaceStateStore, Map<string, Feed>>()

function feedsFor(store: WorkspaceStateStore) {
  let feeds = openFeeds.get(store)
  if (!feeds) { feeds = new Map(); openFeeds.set(store, feeds) }
  return feeds
}

function createFeed(scope: ViewStateScope, node: string | null, name: string, path: string, file?: string) {
  let current = scope.get<Snapshot>('snapshot') || empty
  let revision = 0, quiet = 0
  let validate = true
  let source: string | undefined
  let earlier: AbortController | undefined
  let poll: ReturnType<typeof pollWhileVisible> | undefined
  const readers = new Set<Reader>()
  const basePath = `/sessions/${encodeURIComponent(name)}/${path}`

  const update = (next: Snapshot) => {
    if (Object.keys(next).every(key => Object.is(next[key as keyof Snapshot], current[key as keyof Snapshot])) &&
        Object.keys(next).length === Object.keys(current).length) return
    current = next
    scope.set('snapshot', next, 'cache')
  }
  const eligible = (signal: AbortSignal, requestRevision: number) =>
    !signal.aborted && currentNodeId() === node && requestRevision === revision

  const failure = (error: unknown) => {
    const e = error as Error & { status?: number }
    const denied = e?.status === 401 || e?.status === 403 || e?.message === 'UNAUTHORIZED'
    validate = true
    if (denied) { revision++; earlier?.abort() }
    update({ ...(denied ? empty : current), err: e?.message || String(error) })
  }
  const load = async (signal: AbortSignal) => {
    if (currentNodeId() !== node) return
    const requestRevision = revision, snapshot = current
    const cursor = snapshot.offset
    const requestedFile = validate ? file : snapshot.resolvedFile || file
    const query = new URLSearchParams({ offset: String(cursor), boff: '1' })
    if (cursor === 0 || path === 'pi-transcript') query.set('tail', String(snapshot.tail))
    if (requestedFile) query.set('file', requestedFile)
    try {
      const { data: d } = await api('GET', basePath + '?' + query, undefined, { signal })
      if (!eligible(signal, requestRevision)) return
      validate = false

      const resolvedFile = typeof d.file === 'string' ? d.file : current.resolvedFile
      const replaced = resolvedFile !== current.resolvedFile && current.resolvedFile !== undefined
      const truncated = typeof d.nextOffset === 'number' && d.nextOffset < cursor
      if (replaced || truncated) {
        revision++
        earlier?.abort()
        quiet = 0
        if (cursor > 0) {
          update({ ...empty, resolvedFile, tail: current.tail })
          return
        }
      }
      const previous = replaced || truncated ? empty : current
      const replaceWindow = path === 'pi-transcript' && d.replace === true
      const messages: Msg[] = d.messages || []
      const msgs = replaceWindow ? messages : mergeMessages(previous.msgs, messages, path === 'opencode-transcript')
      const offset = typeof d.nextOffset === 'number' ? d.nextOffset : previous.offset
      const pending = typeof d.pending === 'boolean' ? d.pending : previous.serverPending
      quiet = msgs === previous.msgs && offset === cursor && !!resolvedFile && !(pending ?? isPending(msgs)) ? quiet + 1 : 0
      const page = cursor === 0 || replaceWindow
      update({
        msgs, offset, resolvedFile, serverPending: pending, tail: current.tail, err: '',
        status: mergeStatus(previous.status, d.status, d.quota),
        before: page ? d.before : previous.before,
        hasEarlier: page && typeof d.truncated === 'boolean' ? d.truncated : previous.hasEarlier,
      })
    } catch (error) {
      if (eligible(signal, requestRevision)) failure(error)
      throw error
    }
  }
  const refresh = () => { quiet = 0; void poll?.refresh() }
  const setSource = (hint?: string) => {
    if (!hint || source === hint) return
    source = hint
    if (current.resolvedFile && current.resolvedFile !== hint) {
      revision++
      validate = true
      earlier?.abort()
      update(empty)
      refresh()
    }
  }
  const visibility = () => {
    if (document.hidden) { validate = true; quiet = 0; earlier?.abort() }
  }
  const attach = (reader: Reader, onEmpty: () => void) => {
    readers.add(reader)
    if (!poll) {
      document.addEventListener('visibilitychange', visibility)
      poll = pollWhileVisible(load, () => {
        const interval = Math.min(...Array.from(readers, r => r.interval))
        return quiet >= 3 && Array.from(readers).every(r => r.adaptive && !r.busy) ? 10_000 : interval
      })
    }
    return () => {
      readers.delete(reader)
      if (readers.size) return
      document.removeEventListener('visibilitychange', visibility)
      poll?.stop()
      earlier?.abort()
      onEmpty()
    }
  }
  const loadEarlier = async () => {
    const { before, resolvedFile } = current
    if (earlier || !readers.size || document.hidden || currentNodeId() !== node) return
    if (before === undefined) {
      revision++
      validate = true
      update({ ...empty, tail: current.tail + FIRST_PAGE })
      refresh()
      return
    }
    if (before <= 0 || !resolvedFile) return
    const controller = new AbortController(), requestRevision = revision
    earlier = controller
    try {
      const query = new URLSearchParams({ before: String(before), tail: String(FIRST_PAGE), boff: '1', file: resolvedFile })
      const { data: d } = await api('GET', basePath + '?' + query, undefined, { signal: controller.signal })
      if (!eligible(controller.signal, requestRevision) || d.file !== resolvedFile) return
      update({ ...current, before: d.before, hasEarlier: d.truncated === true, err: '', msgs: d.messages?.length ? [...d.messages, ...current.msgs] : current.msgs })
    } catch (error) {
      if (eligible(controller.signal, requestRevision)) failure(error)
    } finally {
      if (earlier === controller) earlier = undefined
    }
  }
  return { attach, setSource, refresh, loadEarlier }
}

export function useTranscript(name: string, file: string | undefined, path: string, options: number | Options = 1500) {
  const store = useWorkspaceStateStore(), node = useCurrentNodeId(), pageActive = usePageActive()
  const active = pageActive && (typeof options === 'number' || options.active !== false)
  const interval = typeof options === 'number' ? options : options.interval ?? 1500
  const adaptive = typeof options !== 'number'
  const identity = typeof options === 'number' ? undefined : options.identity
  const source = typeof options === 'number' ? undefined : options.source
  const busy = typeof options === 'number' ? undefined : options.busy
  const key = JSON.stringify([node, name, identity || '', path, file || ''])
  const scope = useMemo(() => store.node(node).child('session-transcript', key), [store, node, key])
  const subscribe = useCallback((listener: () => void) => active ? scope.subscribe('snapshot', listener) : () => {}, [scope, active])
  const getSnapshot = useCallback(() => scope.get<Snapshot>('snapshot') || empty, [scope])
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  // The reader stays registered across busy-state updates so an in-flight fetch isn't cancelled.
  const reader = useMemo<Reader>(() => ({ interval, adaptive }), [interval, adaptive, key])
  reader.busy = busy

  useEffect(() => {
    if (!active || !name) return
    const feeds = feedsFor(store)
    let feed = feeds.get(key)
    if (!feed) { feed = createFeed(scope, node, name, path, file); feeds.set(key, feed) }
    return feed.attach(reader, () => feeds.delete(key))
  }, [active, file, key, name, node, path, reader, scope, store])

  useEffect(() => {
    if (active) feedsFor(store).get(key)?.setSource(source)
  }, [active, key, source, store])

  const refresh = useCallback(() => feedsFor(store).get(key)?.refresh(), [key, store])
  useEffect(() => { if (active && busy) refresh() }, [active, busy, refresh])
  const loadEarlier = useCallback(async () => feedsFor(store).get(key)?.loadEarlier(), [key, store])
  return { ...snapshot, refresh, loadEarlier }
}

function mergeMessages(current: Msg[], messages: Msg[], mergeById: boolean) {
  if (!messages.length) return current
  if (!mergeById) return [...current, ...messages]
  const ids = new Map<string, number>()
  const merged = [...current]
  let changed = false
  current.forEach((item, i) => { if (item.id) ids.set(item.id, i) })
  for (const item of messages) {
    const index = item.id ? ids.get(item.id) : undefined
    if (index === undefined) {
      if (item.id) ids.set(item.id, merged.length)
      merged.push(item)
      changed = true
    } else if (JSON.stringify(merged[index]) !== JSON.stringify(item)) {
      merged[index] = item
      changed = true
    }
  }
  return changed ? merged : current
}

// 只有非空字段才覆盖：后端每轮只回它这次扫到的东西，缺的字段不该把已知值抹掉。
// 没有任何字段变化时返回 prev 本身：React 靠引用相等跳过整棵对话树的重渲染，
// 而这个函数每 1.5s 被调一次——每次都造新对象等于每 1.5s 白重渲染一次几百条消息。
function mergeStatus(prev: RawStatus, next: RawStatus | undefined, quota?: number): RawStatus {
  const out: RawStatus = { ...prev }
  let changed = false
  for (const [k, v] of Object.entries(next || {})) {
    if (v !== '' && v !== 0 && v != null && (prev as any)[k] !== v) { (out as any)[k] = v; changed = true }
  }
  if (typeof quota === 'number' && quota > 0 && prev.quota !== quota) { out.quota = quota; changed = true }
  return changed ? out : prev
}

// 把 tool_result 按 tool_use_id 挂回对应 tool_use，并从消息流里隐去已收纳的独立结果气泡。
// Claude、Codex 共用（两端后端都已透出 id / toolUseId）。
export function pairToolResults(msgs: Msg[]): { results: Record<string, Block>; view: Msg[] } {
  const results: Record<string, Block> = {}
  for (const m of msgs) for (const b of m.blocks) if (b.kind === 'tool_result' && b.toolUseId) results[b.toolUseId] = b
  const consumed = new Set<string>()
  for (const m of msgs) for (const b of m.blocks) if (b.kind === 'tool_use' && b.id && results[b.id]) consumed.add(b.id)
  const view = msgs.map((m) => {
    const blocks = m.blocks.filter((b) => !(b.kind === 'tool_result' && b.toolUseId && consumed.has(b.toolUseId)))
    return { ...m, blocks }
  }).filter((m) => m.blocks.length > 0)
  return { results, view }
}

// 「正在生成」判定：最后一轮还没轮到 assistant 收尾(用户刚发 / 工具刚返回 / 正调用工具)。
export function isPending(view: Msg[]): boolean {
  const last = view[view.length - 1]
  if (!last) return false
  if (last.role === 'user' || last.role === 'tool') return true
  if (last.role === 'assistant') return last.blocks[last.blocks.length - 1]?.kind === 'tool_use'
  return false
}

export function hasNativeFinal(view: Msg[], startedMs?: number): boolean {
  const latest = view[view.length - 1]
  return startedMs !== undefined && latest?.final === true && Date.parse(latest.ts || '') >= startedMs
    && latest.blocks.some(block => block.kind === 'text' && !!block.text?.trim())
}
