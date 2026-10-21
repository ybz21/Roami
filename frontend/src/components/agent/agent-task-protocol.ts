import type { AgentTask } from './agent-protocol'

export type TaskSteering = { operationId: string; taskId: string; state: string; revision: number; errorCode?: string; text?: string }
export type TaskAttempt = { id: string; revision: number; attemptNo?: number; state: string; hasConversation?: boolean; sessionId?: string | null; startedMs?: number | null; finishedMs?: number | null; result?: { summary?: string; stderr?: string; output?: string; exitCode?: number; outcomeKnown?: boolean } | null }
export type TaskDetail = { outcome?: { state: string; errorCode?: string | null } | null; task: AgentTask; attempts: TaskAttempt[]; children: AgentTask[]; steering?: TaskSteering | null; attemptsTruncated: boolean; childrenTruncated: boolean; delivery?: { artifacts: TaskArtifact[]; unavailable: { sourcePath: string; runId: string; state: string }[] } }
export type TaskArtifact = { id: string; name: string; mimeType: string; sizeBytes: number; createdMs?: number; metadata?: { sourcePath?: string; runId?: string } }
export type TaskResource = {
  browserId?: string | null; targetId?: string | null; id: string; kind: string; state: string; controlReleased: boolean; takeoverReady: boolean; canPause: boolean; canResume: boolean
  observation?: { title?: string; url?: string; screenshotRef?: string }
}
export type TaskControls = { resources: TaskResource[]; resourcesTruncated: boolean; actions: { id: string; state: string; inputStopped?: boolean; outcomeKnown?: boolean }[]; actionsTruncated: boolean }

export function taskGoal(task: AgentTask): string {
  try { const intent = JSON.parse(task.intent_json); const goal = intent.initialIntent?.goal || intent.goal; return typeof goal === 'string' ? goal : task.id } catch { return task.id }
}

export function taskInstructions(task: AgentTask): string {
  try { const goal = JSON.parse(task.intent_json).goal; return typeof goal === 'string' ? goal : '' } catch { return '' }
}

export function taskExecutor(task: AgentTask): 'native' | 'codex' | 'claude' | null {
  const kind = task.latestAttempt?.executorKind
  if (kind === 'native' || kind === 'codex' || kind === 'claude') return kind
  if (kind !== 'cli') return null
  try { const executor = JSON.parse(task.intent_json).executor; return executor === 'codex' || executor === 'claude' ? executor : null } catch { return null }
}
