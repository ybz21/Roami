import type { AgentTask } from './agent-protocol'

export type TaskSteering = { operationId: string; taskId: string; state: string; revision: number; errorCode?: string; text?: string }
export type TaskAttempt = { id: string; revision: number; state: string; startedMs?: number | null; finishedMs?: number | null; result?: { summary?: string } | null }
export type TaskDetail = { task: AgentTask; attempts: TaskAttempt[]; children: AgentTask[]; steering?: TaskSteering | null; attemptsTruncated: boolean; childrenTruncated: boolean }
export type TaskArtifact = { id: string; name: string; mimeType: string; sizeBytes: number; createdMs?: number }
export type TaskResource = {
  browserId?: string | null; targetId?: string | null; id: string; kind: string; state: string; controlReleased: boolean; takeoverReady: boolean; canPause: boolean; canResume: boolean
  observation?: { title?: string; url?: string; screenshotRef?: string }
}
export type TaskControls = { resources: TaskResource[]; resourcesTruncated: boolean; actions: { id: string; state: string; inputStopped?: boolean; outcomeKnown?: boolean }[]; actionsTruncated: boolean }

export function taskGoal(task: AgentTask): string {
  try { const intent = JSON.parse(task.intent_json); const goal = intent.initialIntent?.goal || intent.goal; return typeof goal === 'string' ? goal : task.id } catch { return task.id }
}
