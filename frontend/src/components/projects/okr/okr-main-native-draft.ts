import { sessionDraftKey } from '../../chat/session-draft'
import type { AgentMessage } from '../../agent/agent-protocol'

export type NativeMainRequest = { cid: string; text: string; key: string; okrContext?: AgentMessage['content']['okrContext'] }

export function transferMainDraft(key: string, sessionId: string) {
  try {
    const value = localStorage.getItem(key), destination = sessionDraftKey(sessionId)
    if (!value || localStorage.getItem(destination) || localStorage.getItem(key + ':native-migration') === value) return
    localStorage.setItem(destination, value)
    localStorage.setItem(key + ':native-migration', value)
  } catch { /* Keep the original draft when storage is unavailable. */ }
}

export function nativeMainRequest(key: string, cid: string, text: string, context?: AgentMessage['content']['okrContext']): NativeMainRequest {
  try {
    for (const suffix of [':native-pending', ':pending']) {
      const saved = JSON.parse(localStorage.getItem(key + suffix) || 'null')
      if (saved?.cid === cid && saved.text === text && typeof saved.key === 'string' && saved.key) return { cid, text, key: saved.key as string, ...(saved.okrContext ? { okrContext: saved.okrContext } : {}) }
    }
  } catch { /* A corrupt record cannot establish an old request identity. */ }
  return { cid, text, key: crypto.randomUUID(), ...(context ? { okrContext: context } : {}) }
}
