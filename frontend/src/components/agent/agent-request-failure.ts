import { taskFailureKey } from './task-failure'

export function agentFailure(error: any, t: (key: string) => string) {
  const code = error?.apiError?.code || error?.message
  const reason = typeof code === 'string' ? taskFailureKey(code) : undefined
  if (reason) return t(reason)
  return t(code === 'MODEL_NOT_CONFIGURED' ? 'agent.modelMissing' : code === 'BRANCH_BUSY' || code === 'COMPACTION_IN_PROGRESS' ? 'agent.busy' : code === 'NOT_ENOUGH_HISTORY' ? 'agent.compactSkipped' : 'agent.requestFailed')
}
