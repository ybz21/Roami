export type SwarmState = 'planning' | 'queued' | 'preparing' | 'running' | 'verifying' | 'waiting_user' | 'review' | 'blocked' | 'failed' | 'succeeded' | 'done' | 'unknown' | 'cancelled' | 'interrupted' | 'cancelling'
export type SwarmWork = {
  id: string; member_name: string; executor: string; title: string; goal: string; acceptance: string; integration: number
  task_id: string | null; revision: number | null; state: SwarmState; dispatch_error: string | null
  dependencies: { upstreamId: string; revision: number; artifactId?: string }[]
  deliverables?: { kind: 'artifact' | 'external_action'; description: string; mimeType?: string }[]
  evidence?: { artifacts: { id: string; name: string; mimeType: string; sizeBytes: number; sha256: string; downloadUrl: string }[]; verification: { kind?: string; state?: string; externalAction?: string | null; receipt?: { artifactId: string; target: string; state: string }; [key: string]: unknown } | null }
  attempt: { runId: string; state: string; sessionId?: string; finishedMs?: number; summary?: string } | null
}
export type SwarmSnapshot = {
  id: string; name: string; goal: string; mainConversationId: string; revision: number; sequence: number
  mainState?: string; paused: boolean; archived: boolean; state: SwarmState; target: { projectId?: string; directory?: string }
  teamMemory?: { available: boolean; content?: string; sha256?: string; source: string; updatedMs?: number | null; author?: string | null; errorCode?: string }
  work: SwarmWork[]; posts: { id: number; author: string; text: string; taskId?: string | null; createdMs: number; deliveryState?: 'accepted' | 'pending' }[]
  mainMessages: { id: string; role: string; text: string; createdMs: number }[]
}
export type StudioNode = { id: string; name: string; executor: string; state: string; main?: boolean }
export function swarmColumn(state: string) {
  if (state === 'succeeded' || state === 'done') return 'done'
  if (['failed', 'blocked', 'unknown', 'interrupted', 'cancelled'].includes(state)) return 'blocked'
  if (['waiting_user', 'verifying', 'review'].includes(state)) return 'review'
  if (['running', 'preparing', 'cancelling'].includes(state)) return 'doing'
  return 'backlog'
}
export function swarmStateToken(state: string) {
  if (['running', 'succeeded', 'done'].includes(state)) return '--ok'
  if (['waiting_user', 'blocked', 'verifying', 'review'].includes(state)) return '--warn'
  if (state === 'failed') return '--danger'
  if (['preparing', 'queued', 'planning'].includes(state)) return '--accent'
  return '--text-dim'
}
