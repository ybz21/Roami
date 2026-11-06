import type { OverviewItem } from '../../session-overview'
import { taskExecutor, type TaskDetail } from '../agent/agent-task-protocol'
import type { SwarmTeamMember } from './swarm-members'
import type { SwarmSnapshot } from './swarm-protocol'

export type MemberSession = { kind: 'native'; id: string; taskId: string; projectId?: string } | { kind: 'codex' | 'claude' | 'opencode' | 'pi' | 'terminal'; id: string }

export function memberSessionIdentity(data: SwarmSnapshot, member: SwarmTeamMember) {
  return JSON.stringify([data.id, data.target.projectId, data.mainConversationId, member.id, member.executor, member.work?.id, member.work?.task_id, member.work?.revision, member.work?.attempt?.runId, member.registered?.instance])
}

export function memberSession(data: SwarmSnapshot, member: SwarmTeamMember, detail: TaskDetail, sessions: OverviewItem[]): MemberSession | null {
  const work = member.work, instance = member.registered?.instance, task = detail.task, attempt = detail.attempts?.[0]
  if (!work?.task_id || !work.revision || work.executor !== member.executor || instance && (instance.state !== 'assigned' || instance.taskId !== work.task_id || !instance.conversationId || instance.conversationId === data.mainConversationId || !instance.branchId)) return null
  if (!task || task.id !== work.task_id || task.revision !== work.revision || taskExecutor(task) !== member.executor || !attempt || attempt.id !== work.attempt?.runId || attempt.revision !== task.revision || ['closing', 'closed', 'unknown'].includes(detail.sessionClosure?.state || '')) return null
  const matches = sessions.filter(session => session.name === attempt.sessionId)
  const live = matches.length === 1 && !matches[0].dormant && matches[0].agent === member.executor ? matches[0] : undefined
  const project = data.target.projectId
  const projectMatches = !project || (task.projectId === project || task.projectId == null && !task.nativeSession && task.origin_conversation_id === data.mainConversationId && live?.projectKey === project) && (!live?.projectKey || live.projectKey === project)
  if (!projectMatches) return null
  if (member.executor === 'native') {
    if (!instance || !task.nativeSession || instance.nativeSessionId !== task.nativeSession.id || instance.conversationId !== task.nativeSession.conversationId) return null
    return { kind: 'native', id: task.nativeSession.id, taskId: task.id, projectId: project }
  }
  if (task.nativeSession || !live || work.attempt?.sessionId !== live.name) return null
  return { kind: ['codex', 'claude', 'opencode', 'pi'].includes(member.executor) ? member.executor as 'codex' | 'claude' | 'opencode' | 'pi' : 'terminal', id: live.name }
}
