import { useEffect, useMemo, useSyncExternalStore } from 'react'
import { api } from '../../api'
import { createSessionPoll } from '../../session-poll'
import { agentLaunch } from '../../agent-command'
import type { AgentKind } from '../../agent-kind'
import type { Preferences } from '../../preferences'
import { nodeApi, useCurrentNodeId } from '../cluster/node-url'
import { briefPreamble, type BriefWhere } from './kickoff-brief'
import { refreshSessionLists } from './native-session-list'
import { sessionLabel } from './session-label'

export type LifecycleIntent = {
  name?: string; task?: string; dir?: string; parent?: string; worktree?: boolean; branch?: string; base?: string; remote?: string; existing?: boolean
  mode?: 'keep' | 'merge' | 'discard'; path?: string; snapshot?: string; sessionIdentity?: string; strategy?: string; keepBranch?: boolean
  launch?: { command: string; agent: string; task: string; preamble: string; taskHeading: string; setupHeading: string; fileBase: string; autoReview: boolean }
}
export type LifecycleOperation = {
  operationId: string; resourceId: string; requestKey: string; kind: 'create' | 'close'; intent: LifecycleIntent
  state: 'queued' | 'running' | 'attention' | 'succeeded' | 'cancelled'; stage: string; revision: number
  cancelRequested: boolean; receipts: Record<string, { result: any; durationMs: number }>; errorCode?: string; errorDetail?: string; acceptedAt: number; updatedAt: number
}
export const lifecycleEnded = (op: LifecycleOperation) => op.state === 'succeeded' || op.state === 'cancelled'
const useOperations = createSessionPoll<LifecycleOperation[]>('/session-lifecycle/operations', 3000, [], r => Array.isArray(r.data) ? r.data : [], ops => ops.some(op => !lifecycleEnded(op) && op.state !== 'attention'))
const accepted = new Map<string, { scope: string; op: LifecycleOperation }>()
const acceptedListeners = new Set<() => void>()
let acceptedRevision = 0
const acceptedSubscribe = (listener: () => void) => { acceptedListeners.add(listener); return () => { acceptedListeners.delete(listener) } }
const acceptedSnapshot = () => acceptedRevision
function rememberAccepted(scope: string, op: LifecycleOperation) {
  accepted.set(op.operationId, { scope, op }); acceptedRevision++; acceptedListeners.forEach(listener => listener())
}

let events: { path: string; count: number; close: () => void } | undefined
function subscribeEvents() {
  const path = nodeApi('/session-lifecycle/events')
  if (events?.path !== path) { events?.close(); events = undefined }
  if (!events) {
    let source: EventSource | undefined
    const visibility = () => {
      source?.close(); source = undefined
      if (!document.hidden && typeof EventSource !== 'undefined') {
        source = new EventSource(path)
        source.onopen = refreshSessionLists
        source.onmessage = refreshSessionLists
      }
    }
    document.addEventListener('visibilitychange', visibility); visibility()
    events = { path, count: 0, close: () => { source?.close(); document.removeEventListener('visibilitychange', visibility) } }
  }
  const own = events; own.count++
  return () => { if (--own.count === 0) { own.close(); if (events === own) events = undefined } }
}

export function useSessionLifecycle(enabled = true) {
  const node = useCurrentNodeId()
  useEffect(() => enabled ? subscribeEvents() : undefined, [node, enabled])
  const snapshot = useOperations(enabled)
  const revision = useSyncExternalStore(acceptedSubscribe, acceptedSnapshot, acceptedSnapshot)
  const scope = nodeApi('/session-lifecycle/operations')
  const value = useMemo(() => {
    if (!enabled) return snapshot.value
    const known = new Set(snapshot.value.map(op => op.operationId))
    const optimistic = [...accepted.values()].filter(item => item.scope === scope && !known.has(item.op.operationId)).map(item => item.op)
    return optimistic.length ? [...optimistic, ...snapshot.value] : snapshot.value
  }, [snapshot.value, revision, scope, enabled])
  useEffect(() => { for (const op of snapshot.value) accepted.delete(op.operationId) }, [snapshot.value])
  return { ...snapshot, value }
}

async function durableRequestKey(signature: string) {
  const digest = crypto.subtle ? [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(signature)))].map(byte => byte.toString(16).padStart(2, '0')).join('') : encodeURIComponent(signature)
  const storageKey = 'roami:lifecycle-request:' + digest
  let key = localStorage.getItem(storageKey)
  if (!key) { const bytes = crypto.getRandomValues(new Uint8Array(16)); key = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join(''); localStorage.setItem(storageKey, key) }
  return { key, forget: () => localStorage.removeItem(storageKey) }
}

const pending = new Map<string, Promise<LifecycleOperation>>()
export function submitLifecycle(kind: 'create' | 'close', intent: LifecycleIntent, resourceId?: string): Promise<LifecycleOperation> {
  if (kind === 'close' && resourceId && !intent.name) intent = { ...intent, name: sessionLabel(resourceId) }
  const scope = nodeApi('/session-lifecycle/operations')
  const signature = JSON.stringify({ scope, kind, intent, resourceId })
  const previous = pending.get(signature); if (previous) return previous
  const submit = async () => {
    const request = await durableRequestKey(signature)
    const requestKey = request.key
    if (nodeApi('/session-lifecycle/operations') !== scope) throw new Error('LIFECYCLE_NODE_CHANGED')
    let op: LifecycleOperation
    try { op = (await api('POST', '/session-lifecycle/operations', { kind, requestKey, resourceId, intent })).data }
    catch (error) {
      if (nodeApi('/session-lifecycle/operations') !== scope) throw error
      try { op = (await api('GET', '/session-lifecycle/operations?requestKey=' + encodeURIComponent(requestKey))).data }
      catch { throw error }
    }
    if (nodeApi('/session-lifecycle/operations') !== scope) throw new Error('LIFECYCLE_NODE_CHANGED')
    if (!op?.operationId || !op.resourceId) throw new Error('LIFECYCLE_RESPONSE_INVALID')
    rememberAccepted(scope, op)
    request.forget()
    refreshSessionLists()
    return op
  }
  const promise = submit().finally(() => pending.delete(signature)); pending.set(signature, promise)
  return promise
}

export function lifecycleLaunchIntent(agent: AgentKind | 'none', prefs: Preferences, task: string, where: BriefWhere['kind'], autoReview: boolean, t: (key: string, vars?: Record<string, unknown>) => string) {
  if (agent === 'none') return undefined
  const vars = { path: '{{PATH}}', branch: '{{BRANCH}}', base: '{{BASE}}', sess: '{{SESSION}}' }
  return { command: agentLaunch(agent, prefs), agent, task, preamble: briefPreamble({ kind: where, ...vars } as BriefWhere, vars.sess, autoReview, t), taskHeading: t('session.wt.briefTask'), setupHeading: t('session.wt.briefSetup'), fileBase: nodeApi('/file'), autoReview }
}

export async function lifecycleAction(op: LifecycleOperation, action: 'retry' | 'cancel' | 'retain' | 'retain-branch') {
  const scope = nodeApi('/session-lifecycle/operations')
  const request = await durableRequestKey(JSON.stringify({ scope, id: op.operationId, action, revision: op.revision }))
  if (nodeApi('/session-lifecycle/operations') !== scope) throw new Error('LIFECYCLE_NODE_CHANGED')
  const response = await api('POST', `/session-lifecycle/operations/${encodeURIComponent(op.operationId)}/${action}`, { revision: op.revision, requestKey: request.key })
  request.forget(); refreshSessionLists(); return response.data as LifecycleOperation
}

export function blockingLifecycle(ops: LifecycleOperation[], name: string) {
  const op = ops.find(op => op.resourceId === name)
  return op && (op.kind === 'close' || op.state !== 'succeeded') ? op : undefined
}

export function lifecycleRequestError(error: any, t: (key: string) => string) {
  const code = error?.apiError?.code || error?.message || ''
  if (code.startsWith('LIFECYCLE_')) {
    const key = 'session.lifecycle.error.' + code, text = t(key)
    return text === key ? t('session.lifecycle.requestFailed') : text
  }
  return error?.message || t('session.lifecycle.requestFailed')
}
