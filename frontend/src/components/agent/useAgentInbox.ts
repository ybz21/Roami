import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { AgentConversation, AgentNotice } from './agent-protocol'

export function useAgentInbox(enabled: boolean, node: string | null) {
  const [data, setData] = useState<{ conversations: AgentConversation[]; notices: AgentNotice[]; unread: number; unavailable: boolean }>({ conversations: [], notices: [], unread: 0, unavailable: false })
  const refreshRef = useRef<() => void>(() => {})
  useEffect(() => {
    if (!enabled) return
    let stopped = false, busy = false, again = false
    const abort = new AbortController()
    const load = async () => {
      if (stopped) return
      if (busy) { again = true; return }
      busy = true
      const responses = await Promise.allSettled([
        api('POST', '/agent/main-conversation', undefined, { signal: abort.signal }),
        api('GET', '/agent/notifications?includeRead=true', undefined, { signal: abort.signal }),
      ])
      if (!stopped) setData((old) => ({
        conversations: responses[0].status === 'fulfilled' ? [responses[0].value.data] : old.conversations,
        notices: responses[1].status === 'fulfilled' ? responses[1].value.data.items : old.notices,
        unread: responses[1].status === 'fulfilled' ? responses[1].value.data.unread : old.unread,
        unavailable: responses[0].status === 'rejected',
      }))
      busy = false
      if (again && !stopped) { again = false; void load() }
    }
    refreshRef.current = () => { void load() }
    void load()
    const interval = setInterval(() => { if (document.visibilityState === 'visible') void load() }, 10_000)
    return () => { stopped = true; abort.abort(); clearInterval(interval); refreshRef.current = () => {} }
  }, [enabled, node])
  return { ...data, refresh: useCallback(() => refreshRef.current(), []) }
}
export type AgentInboxState = ReturnType<typeof useAgentInbox>
