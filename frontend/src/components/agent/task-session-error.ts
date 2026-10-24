import { taskFailureKey } from './task-failure'

export function taskSessionError(code: string | undefined, t: (key: string) => string) {
  if (code === 'TASK_SESSION_CLOSED') return t('agent.task.sessionClosed')
  if (code === 'TASK_SESSION_CLOSING' || code === 'TASK_SESSION_CLOSE_UNKNOWN') return t('agent.task.sessionCloseUnknown')
  if (code === 'SESSION_NOT_IDLE' || code === 'TASK_SESSION_BUSY') return t('agent.task.sessionBusy')
  if (code === 'SESSION_TARGET_NOT_FOUND' || code === 'SESSION_LIFECYCLE_UNAVAILABLE' || code === 'SESSION_BINDING_CONFLICT' || code === 'TASK_SESSION_UNAVAILABLE') return t('agent.task.sessionUnavailable')
  if (code === 'TASK_OUTCOME_UNRESOLVED') return t('agent.task.reconcile')
  if (code === 'RESOURCE_STOP_UNCONFIRMED' || code === 'TASK_RESOURCE_NOT_RELEASED') return t('agent.task.waitForControl')
  if (code === 'TASK_REVISION_CHANGED' || code === 'TASK_RESULT_SUPERSEDED' || code === 'TASK_STEER_PENDING') return t('agent.task.changed')
  if (code === 'TASK_SOURCE_FORGOTTEN' || code === 'CONTEXT_SOURCE_FORGOTTEN') return t('agent.task.forgotten')
  if (code === 'PARENT_TASK_NOT_RUNNING') return t('agent.task.parentStopped')
  const reason = taskFailureKey(code || '')
  if (reason) return t(reason)
  return t('agent.requestFailed')
}
