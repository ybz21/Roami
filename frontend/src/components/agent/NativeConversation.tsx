import { Fragment, useCallback, useMemo } from 'react'
import { useI18n } from '../../i18n'
import { ChatMessage } from '../chat/Message'
import { ToolRun } from '../chat/ToolRun'
import { groupRuns } from '../chat/runs'
import { pairToolResults } from '../chat/useTranscript'
import AgentMessageView from './AgentMessageView'
import TaskDescription from './TaskDescription'
import type { AgentMessage } from './agent-protocol'
import { agentResourceUrl } from './agent-resource-url'
import { nativeTranscript } from './native-transcript'

export default function NativeConversation({ messages, active, node, canAnswer, answer }: { messages: AgentMessage[]; active: boolean; node: string | null; canAnswer: boolean; answer: (text: string) => Promise<boolean> }) {
  const { t } = useI18n()
  const { results, view } = useMemo(() => {
    const paired = pairToolResults(nativeTranscript(messages))
    if (!active) for (const message of paired.view) for (const block of message.blocks) {
      if (block.kind === 'tool_use' && block.id && !paired.results[block.id]) paired.results[block.id] = { kind: 'tool_result', toolUseId: block.id, text: t('agent.task.outcomeUnknown'), isError: true }
    }
    return paired
  }, [messages, active, t])
  const items = useMemo(() => groupRuns(view, results), [view, results])
  const sources = useMemo(() => new Map(messages.map(message => [message.id, message])), [messages])
  const renderUserText = useCallback((text: string) => <TaskDescription content={text} title={false} />, [])
  const resolveHref = useCallback((href: string) => agentResourceUrl(href, node), [node])
  const extras = (item?: AgentMessage) => item && (item.content.question || item.content.taskStatus || item.content.attachments?.length) ? <AgentMessageView item={{ ...item, content: { ...item.content, text: undefined, tool_calls: undefined } }} node={node} readOnly focused={false} remember={() => {}} canAnswer={canAnswer && item.seq === messages[messages.length - 1]?.seq} answer={answer} /> : null
  const streaming = messages.some(item => item.role === 'assistant' && item.status === 'streaming')
  return <>
    {items.map((item, index) => item.kind === 'run' ? <ToolRun key={item.run.key} run={item.run} isLast={index === items.length - 1} /> : <Fragment key={item.msg.id}>{item.msg.blocks.some(block => block.kind !== 'native_extra') && <ChatMessage m={item.msg.blocks.some(block => block.kind === 'native_extra') ? { ...item.msg, blocks: item.msg.blocks.filter(block => block.kind !== 'native_extra') } : item.msg} results={results} side="native" resolveHref={resolveHref} renderUserText={renderUserText} />}{extras(item.msg.id ? sources.get(item.msg.id) : undefined)}</Fragment>)}
    {streaming && <span className="agent-typing" aria-label={t('agent.responding')} />}
  </>
}
