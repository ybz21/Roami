import { modelProxyFailureKey } from './agent-models'
const reasons: Record<string, string> = {
  BROWSER_DRIVER_UNAVAILABLE: 'browser', BROWSER_DRIVER_PROTOCOL_INVALID: 'browser',
  WEB_RETRIEVAL_EVIDENCE_MISSING: 'retrieval',
  TOOL_ARGUMENT_REPAIR_STALLED: 'toolProgress',
  MODEL_HTTP_401: 'authentication', MODEL_HTTP_403: 'authentication',
  MODEL_DEADLINE: 'deadline', EXECUTION_DEADLINE_OR_INTERRUPTION: 'deadline', TASK_BUDGET_EXCEEDED: 'deadline',
  AGENT_STEP_LIMIT: 'steps',
  WORKSPACE_STALE: 'workspace', UNKNOWN_WORKSPACE: 'workspace', WORKSPACE_PROJECT_MISMATCH: 'workspace',
  NATIVE_WORKSPACE_UNAVAILABLE: 'workspace', PROJECT_PROVISION_UNAVAILABLE: 'workspace', WORKSPACE_PREPARATION_FAILED: 'workspace',
  UNKNOWN_PROJECT: 'workspace', PROJECT_CATALOG_UNAVAILABLE: 'workspace', PROJECT_HAS_NO_GIT: 'workspace',
  INVALID_PROJECT_DIRECTORY: 'workspace', INVALID_WORKSPACE_TARGET: 'workspace',
  INVALID_EXECUTION_DIRECTORY: 'directory', EXECUTION_DIRECTORY_UNAVAILABLE: 'directory',
  WORKSPACE_BUSY: 'workspaceBusy',
}

export function taskFailureKey(code: unknown): string | undefined {
  if (modelProxyFailureKey(code)) return modelProxyFailureKey(code)
  if (typeof code !== 'string') return undefined
  const reason = reasons[code] || (code.includes('OUTCOME_UNKNOWN') || code.includes('RELEASE_UNKNOWN') ? 'unknown' : '')
  return reason ? 'agent.task.failure.' + reason : undefined
}
