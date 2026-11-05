import { useCallback, useEffect } from 'react'
import type { AgentConversation, AgentNotice } from './agent-protocol'
import { agentDataKey, clearAgentDataCache, loadAgentData } from './agent-data-cache'
import { useAgentData } from './useAgentData'

export function useAgentInbox(enabled: boolean, node: string | null, preloadMain = false): AgentInboxState {
  const main = useAgentData<AgentConversation>(enabled ? '/agent/main-conversation' : null, 60_000, 60_000, 'POST')
  const cid = main.value?.id
  const notices = useAgentData<{ unread: number; cursor: number; conversationId: string }>(enabled && cid ? '/agent/notifications/summary?conversationId=' + encodeURIComponent(cid) : null, 5000, 10_000)
  const summary = notices.value?.conversationId === cid ? notices.value : undefined
  const mainKey = enabled ? agentDataKey('/agent/main-conversation', 'POST') : ''
  useEffect(() => { if (!enabled) clearAgentDataCache() }, [enabled])
  useEffect(() => {
    if (!enabled || !preloadMain || !cid || mainKey !== agentDataKey('/agent/main-conversation', 'POST')) return
    // Only the visible main chat needs history; badges must not load it on other pages.
    void loadAgentData('/agent/conversations/' + encodeURIComponent(cid) + '/messages?limit=50', 5000).catch(() => {})
  }, [enabled, preloadMain, node, cid, mainKey])
  const refresh = useCallback(() => { notices.refresh(); if (!main.value || main.failed) main.refresh() }, [notices.refresh, main.refresh, main.value, main.failed])
  return {
    conversations: enabled && mainKey && main.value ? [main.value] : [],
    notices: [], cursor: enabled ? summary?.cursor : undefined, unread: enabled ? summary?.unread || 0 : 0,
    unavailable: enabled && main.failed, notificationsLoading: main.loading || notices.loading, notificationsFailed: main.failed || notices.failed, refresh,
  }
}
export type AgentInboxState = {
  conversations: AgentConversation[]; notices: AgentNotice[]; unread: number; unavailable: boolean; refresh: () => void
  cursor?: number; notificationsLoading?: boolean; notificationsFailed?: boolean
}
