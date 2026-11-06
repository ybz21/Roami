import { useMemo } from 'react'
import { useI18n } from '../../i18n'
import { ChatMessage } from '../chat/Message'
import type { Msg } from '../chat/types'
import type { AgentReplyPreview as ReplyPreview } from './agent-protocol'

export default function AgentReplyPreview({ value, messageId, resolveResource }: { value: ReplyPreview; messageId: string; resolveResource: (href: string) => string }) {
  const { t } = useI18n()
  const draft = useMemo<Msg>(() => ({ id: messageId + ':preview', role: 'assistant', blocks: [{ kind: 'text', text: value.text }] }), [messageId, value.text])
  return <div className="agent-reply-preview" data-preview-state={value.state}>
    <span className="agent-muted" role="status">{t('agent.replyPreview.' + value.state)}</span>
    <ChatMessage m={draft} results={{}} side="native" allowImages={false} resolveHref={resolveResource} />
    {value.clipped && <span className="agent-muted">{t('agent.replyPreview.clipped')}</span>}
  </div>
}
