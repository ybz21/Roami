const reasons: Record<string, string> = {
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

export function taskFailureKey(code: string): string | undefined {
  const reason = reasons[code] || (code.includes('OUTCOME_UNKNOWN') || code.includes('RELEASE_UNKNOWN') ? 'unknown' : '')
  return reason ? 'agent.task.failure.' + reason : undefined
}
