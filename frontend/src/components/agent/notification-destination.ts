import { api } from '../../api'
import { currentNodeId } from '../cluster/node-url'
import { getHashParams } from '../../route-hash'
import { loadSwarmDirectory } from '../swarm/swarm-directory'
import type { AgentNotice } from './agent-protocol'

export type OkrMessageReference = { conversationId: string; branchId: string; messageId: string }
export function readOkrMessageReference(): OkrMessageReference | undefined {
  const params = getHashParams(), conversationId = params.get('okrConversation')
  return conversationId ? { conversationId, branchId: params.get('okrBranch') || '', messageId: params.get('okrMessage') || '' } : undefined
}
export function clearOkrMessageReference() {
  const params = getHashParams()
  for (const key of ['okrConversation', 'okrBranch', 'okrMessage']) params.delete(key)
  history.replaceState(history.state, '', location.hash.split('?')[0] + (params.size ? '?' + params : ''))
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

export async function notificationDestination(notice: Pick<AgentNotice, 'conversation_id' | 'branch_id' | 'message_id'>, home: string): Promise<string | null> {
  if (notice.conversation_id === home) return null
  const node = currentNodeId()
  const teams = (await loadSwarmDirectory()).filter(team => team.mainConversationId === notice.conversation_id)
  if (node !== currentNodeId()) throw new Error('Node changed')
  if (!teams.length) return null
  const projects = new Set(teams.map(team => team.target?.projectId))
  if (projects.size !== 1) throw new Error('Ambiguous message source')
  const projectId = teams[0].target?.projectId
  if (!projectId) return null
  const { data: workspace } = await api('GET', '/projects/' + encodeURIComponent(projectId) + '/okr')
  if (node !== currentNodeId()) throw new Error('Node changed')
  const bound = teams.find(team => team.id === workspace?.swarm && !team.archived)
  if (!bound || workspace.projectId !== projectId) return null
  const params = getHashParams()
  params.set('okrConversation', notice.conversation_id)
  if (notice.branch_id) params.set('okrBranch', notice.branch_id); else params.delete('okrBranch')
  if (notice.message_id) params.set('okrMessage', notice.message_id); else params.delete('okrMessage')
  return '#/okr/' + encodeURIComponent(projectId) + '?' + params
}
