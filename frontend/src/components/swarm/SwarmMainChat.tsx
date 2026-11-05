import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useCurrentNodeId, nodeApi } from '../cluster/node-url'
import { useAgentThread } from '../agent/useAgentThread'
import { useAgentDraft } from '../agent/useAgentDraft'
import NativeConversation from '../agent/NativeConversation'
import ConversationComposer from '../chat/ConversationComposer'

type PendingMessage = { text: string; key: string }
function pendingMessage(key: string): PendingMessage | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null')
    return value && typeof value.text === 'string' && typeof value.key === 'string' ? value : null
  } catch { return null }
}

export default function SwarmMainChat({ conversationId, projectId, onSent }: { conversationId: string; projectId?: string; onSent: () => Promise<void> }) {
  const { t } = useI18n(), node = useCurrentNodeId()
  const scope = nodeApi('/agent/conversations/' + encodeURIComponent(conversationId))
  const thread = useAgentThread(conversationId, '', node)
  const draftKey = 'roami.swarm.main.draft:' + scope
  const [draft, setDraft] = useAgentDraft(draftKey)
  const pendingKey = 'roami.swarm.main.pending:' + scope
  const [sending, setSending] = useState(false), [failed, setFailed] = useState(false)
  const alive = useRef(true), busy = useRef(false), latest = useRef({ scope, draft, projectId })
  latest.current = { scope, draft, projectId }
  const pending = useRef(pendingMessage(pendingKey))
  const scroll = useRef<HTMLDivElement>(null), followLatest = useRef(true)
  const current = () => alive.current && latest.current.scope === scope && latest.current.projectId === projectId && nodeApi('/agent/conversations/' + encodeURIComponent(conversationId)) === scope
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { localStorage.setItem(draftKey, draft) }, [draftKey, draft])
  useEffect(() => { if (followLatest.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight }, [thread.view?.messages])
  const send = async (text = draft, consumeDraft = true) => {
    const body = text.trim()
    if (!body || busy.current || !conversationId || !current()) return false
    if (!pending.current || pending.current.text !== body) pending.current = { text: body, key: crypto.randomUUID() }
    const request = pending.current
    localStorage.setItem(pendingKey, JSON.stringify(request))
    busy.current = true; setSending(true); setFailed(false)
    try {
      if (projectId) {
        const response = await api('GET', '/agent/conversations/' + encodeURIComponent(conversationId) + '/identity')
        const identity = response.data
        if (identity?.kind !== 'project_main' || identity.projectId !== projectId || identity.conversationId !== conversationId) throw new Error('Project Main changed')
      }
      if (!current()) return false
      await api('POST', '/agent/conversations/' + encodeURIComponent(conversationId) + '/messages', { requestKey: request.key, text: request.text, attachmentIds: [] })
      if (!current()) return false
      pending.current = null; localStorage.removeItem(pendingKey)
      if (consumeDraft && latest.current.draft.trim() === body) setDraft('')
      thread.refresh(); void onSent().catch(() => {})
      return true
    } catch { if (current()) setFailed(true); return false }
    finally { busy.current = false; if (current()) setSending(false) }
  }
  const messages = thread.view?.messages || []
  const running = !!thread.view?.turns.some(turn => ['queued', 'running'].includes(turn.state))
  return <section className="swarm-chat swarm-main-conversation">
    <div className="swarm-chat-log" ref={scroll} onScroll={event => { const pane = event.currentTarget; followLatest.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < pane.clientHeight * 0.1 }}>
      <div className="swarm-conversation-messages">
      {thread.view?.page?.hasMore && <button type="button" className="tt-act" disabled={thread.loadingOlder} onClick={() => void thread.loadOlder()}>{t('okr.earlierMessages')}</button>}
      <NativeConversation messages={messages} active={running} node={node} canAnswer={!sending} answer={text => send(text, false)} />
      {!messages.length && !thread.loading && <p className="swarm-note">{t('swarm.conversation.mainEmpty')}</p>}
      {(failed || thread.failed) && <p role="alert">{t('agent.requestFailed')}</p>}
      </div>
    </div>
    <ConversationComposer className="swarm-chat-composer" value={draft} onChange={setDraft} label={t('agent.message')} placeholder={t('swarm.conversation.mainPlaceholder')} disabled={!conversationId} send={{ label: t('common.send'), pending: sending, onClick: () => void send() }} />
  </section>
}
