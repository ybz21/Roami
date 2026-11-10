import { taskSessionError } from '../agent/task-session-error'
import { refreshTask } from '../agent/agent-task-events'
import { api } from '../../api'
import { submitLifecycle, lifecycleRequestError } from './session-lifecycle'
import { nodeApi } from '../cluster/node-url'
import type { TaskDetail } from '../agent/agent-task-protocol'
import { nativeSessionId } from './session-record'
import { refreshSessionLists } from './native-session-list'

export async function renameSession(name: string, label: string) {
  const id = nativeSessionId(name)
  const result = await api('PATCH', id ? '/agent/native-sessions/' + encodeURIComponent(id) : '/sessions/' + encodeURIComponent(name), { name: label })
  refreshSessionLists()
  return result
}

async function nativeTask(name: string) {
  const id = nativeSessionId(name), scope = nodeApi('/agent/native-sessions')
  const metadata = (await api('GET', '/agent/native-sessions/' + encodeURIComponent(id!))).data
  if (nodeApi('/agent/native-sessions') !== scope) throw Object.assign(new Error('TASK_REVISION_CHANGED'), { apiError: { code: 'TASK_REVISION_CHANGED' } })
  const path = '/agent/tasks/' + encodeURIComponent(metadata.taskId)
  const detail: TaskDetail = (await api('GET', path)).data
  if (nodeApi('/agent/native-sessions') !== scope || detail.task.nativeSession?.id !== id) throw Object.assign(new Error('TASK_REVISION_CHANGED'), { apiError: { code: 'TASK_REVISION_CHANGED' } })
  return { path, detail }
}

export async function closeSession(name: string) {
  if (!nativeSessionId(name)) {
    const st = (await api('GET', '/sessions/' + encodeURIComponent(name) + '/worktree-status')).data
    return submitLifecycle('close', { mode: 'keep', path: st.path, sessionIdentity: st.sessionIdentity }, name)
  }
  const { path, detail } = await nativeTask(name)
  if (detail.sessionClosure?.state !== 'closed') await api('POST', path + '/close-session', { revision: detail.task.revision, runId: detail.attempts[0]?.id })
  refreshTask(detail.task.id)
  refreshSessionLists()
}

export async function stopSession(name: string) {
  if (!nativeSessionId(name)) return api('POST', '/sessions/' + encodeURIComponent(name) + '/keys', { keys: ['Escape'] })
  const { path, detail } = await nativeTask(name)
  await api('POST', path + '/cancel', { revision: detail.task.revision })
  refreshTask(detail.task.id)
  refreshSessionLists()
}


export function sessionActionError(error: any, t: (key: string) => string) {
  if ((error?.apiError?.code || error?.message || '').startsWith('LIFECYCLE_')) return lifecycleRequestError(error, t)
  return error?.apiError?.code ? taskSessionError(error.apiError.code, t) : error?.message || t('agent.requestFailed')
}


export async function sendSessionPrompt(name: string, text: string) {
  if (!nativeSessionId(name)) return api('POST', '/tasks/_/send', { sess: name, msg: text })
  const { path, detail } = await nativeTask(name)
  await api('POST', path + '/steer', { text, revision: detail.task.revision, requestKey: crypto.randomUUID() })
  refreshTask(detail.task.id)
  refreshSessionLists()
}
