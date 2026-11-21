import { useCallback, useSyncExternalStore } from 'react'
import { api } from '../../api'
import { usePageActive } from '../../page-activity'
import { pollWhileVisible } from '../../visible-poll'
import { currentNodeId, useCurrentNodeId } from '../cluster/node-url'
import { nativeSessionId } from '../sessions/session-record'

type Screen = { raw: string; fresh: boolean }
const empty: Screen = { raw: '', fresh: false }

type Reader = { interval: number; notify: () => void }
type Capture = {
  snapshot: Screen
  readers: Set<Reader>
  revision: number
  poll?: ReturnType<typeof pollWhileVisible>
}
const captures = new Map<string, Capture>()

const intervalOf = (capture: Capture) => Math.min(...Array.from(capture.readers, reader => reader.interval))
const screenKey = (node: string | null, name: string, identity?: string) => JSON.stringify([node, name, identity])
const capturePath = (name: string) => `/sessions/${encodeURIComponent(name)}/capture?lines=50`

function publish(capture: Capture, next: Screen) {
  if (next.raw === capture.snapshot.raw && next.fresh === capture.snapshot.fresh) return
  capture.snapshot = next
  capture.readers.forEach(reader => reader.notify())
}

export async function readSessionScreen(name: string, node: string | null, identity?: string, signal?: AbortSignal) {
  if (currentNodeId() !== node) return
  const key = screenKey(node, name, identity)
  const entry = captures.get(key)
  const revision = entry ? ++entry.revision : 0
  const current = () => !signal?.aborted && currentNodeId() === node
  try {
    const { data } = await api('GET', capturePath(name), undefined, { signal })
    if (!current()) return
    const raw = typeof data === 'string' ? data : ''
    if (entry?.revision === revision) publish(entry, { raw, fresh: true })
    return raw
  } catch (error) {
    if (currentNodeId() === node && entry?.revision === revision && captures.get(key) === entry) {
      publish(entry, { ...entry.snapshot, fresh: false })
    }
    throw error
  }
}

function subscribeScreen(key: string, name: string, node: string | null, identity: string | undefined, reader: Reader) {
  let capture = captures.get(key)
  if (!capture) {
    capture = { snapshot: empty, readers: new Set(), revision: 0 }
    captures.set(key, capture)
  }
  const entry = capture
  const previousInterval = intervalOf(entry)
  entry.readers.add(reader)
  if (!entry.poll) {
    entry.poll = pollWhileVisible(signal => readSessionScreen(name, node, identity, signal), () => intervalOf(entry))
  } else if (reader.interval < previousInterval) {
    void entry.poll.refresh()
  }
  return () => {
    entry.readers.delete(reader)
    if (!entry.readers.size) {
      entry.poll?.stop()
      captures.delete(key)
    }
  }
}

export function useSessionScreen(name: string | null, { interval = 1200, identity }: { interval?: number; identity?: string } = {}): Screen {
  const node = useCurrentNodeId()
  const active = usePageActive()
  const key = name && active && !nativeSessionId(name) ? screenKey(node, name, identity) : null
  const subscribe = useCallback((notify: () => void) =>
    key && name ? subscribeScreen(key, name, node, identity, { interval, notify }) : () => {},
  [key, name, node, identity, interval])
  const snapshot = useCallback(() => key ? captures.get(key)?.snapshot || empty : empty, [key])
  return useSyncExternalStore(subscribe, snapshot, () => empty)
}
