import { useCallback, useEffect } from 'react'
import type { AgentConversation, AgentNotice } from './agent-protocol'
import { agentDataKey, clearAgentDataCache, loadAgentData } from './agent-data-cache'
import { useAgentData } from './useAgentData'

export function useAgentInbox(enabled: boolean, node: string | null): AgentInboxState {
  const main = useAgentData<AgentConversation>(enabled ? '/agent/main-conversation' : null, 60_000, 60_000, 'POST')
  const notices = useAgentData<{ items: AgentNotice[]; unread: number }>(enabled ? '/agent/notifications?includeRead=true' : null, 5000, 10_000)
  const cid = main.value?.id
  const mainKey = enabled ? agentDataKey('/agent/main-conversation', 'POST') : ''
  useEffect(() => { if (!enabled) clearAgentDataCache() }, [enabled])
  useEffect(() => {
    if (!enabled || !cid || mainKey !== agentDataKey('/agent/main-conversation', 'POST')) return
    // Start the large history before navigation mounts its view; share that same request.
    void loadAgentData('/agent/conversations/' + encodeURIComponent(cid) + '/messages', 5000).catch(() => {})
    void loadAgentData('/agent/tasks?conversationId=' + encodeURIComponent(cid), 3000).catch(() => {})
    void import('./AgentChat').catch(() => {})
    void import('./AgentHomePage').catch(() => {})
  }, [enabled, node, cid, mainKey])
  const refresh = useCallback(() => { notices.refresh(); if (!main.value || main.failed) main.refresh() }, [notices.refresh, main.refresh, main.value, main.failed])
  return {
    conversations: enabled && mainKey && main.value ? [main.value] : [],
    notices: enabled ? notices.value?.items || [] : [], unread: enabled ? notices.value?.unread || 0 : 0,
    unavailable: enabled && main.failed, notificationsLoading: notices.loading, notificationsFailed: notices.failed, refresh,
  }
}
export type AgentInboxState = {
  conversations: AgentConversation[]; notices: AgentNotice[]; unread: number; unavailable: boolean; refresh: () => void
  notificationsLoading?: boolean; notificationsFailed?: boolean
}
