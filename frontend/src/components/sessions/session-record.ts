import type { AgentKind } from '../../agent-kind'

export type SessionAgent = AgentKind | 'native'
export type NativeSessionRecord = {
  nativeSessionId: string; taskId: string; title: string; taskState: string
  projectId?: string; parentNativeSessionId?: string; directory?: string; branch?: string; createdAt?: string
  lastActivity?: number; lifecycle?: string; closureError?: string
}

export const nativeSessionName = (id: string) => 'roami:' + id
export const nativeSessionId = (name: string) => name.startsWith('roami:') ? name.slice(6) : null

export function nativeSessionRecord(session: NativeSessionRecord) {
  return {
    name: nativeSessionName(session.nativeSessionId), label: session.title,
    parent: session.parentNativeSessionId ? nativeSessionName(session.parentNativeSessionId) : undefined,
    nativeSessionId: session.nativeSessionId, taskId: session.taskId, agent: 'native' as const,
    projectKey: session.projectId, cwd: session.directory || '', branch: session.branch,
    lastActivity: session.lastActivity || Date.parse(session.createdAt || '') / 1000 || 0,
    running: ['queued', 'preparing', 'running', 'verifying', 'cancelling'].includes(session.taskState),
    waiting: false, dormant: false, state: 'live' as const,
  }
}
