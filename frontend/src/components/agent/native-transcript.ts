import type { Block, Msg } from '../chat/types'
import type { AgentMessage } from './agent-protocol'

const nativeToolNames: Record<string, string> = { bash: 'Bash', read: 'Read', write: 'Write', edit: 'Edit' }

function nativeResultText(text: string): string {
  try {
    const value = JSON.parse(text)
    if (typeof value === 'string') return value
    if (value && typeof value === 'object') {
      const streams = [value.stdout, value.stderr].filter((stream): stream is string => typeof stream === 'string' && !!stream)
      if (streams.length) return streams.join('\n')
    }
  } catch { /* Plain and truncated output remains readable. */ }
  return text
}

export function nativeTranscript(messages: AgentMessage[]): Msg[] {
  return messages.flatMap(item => {
    const blocks: Block[] = []
    const callId = (id: string) => item.turn_id ? JSON.stringify([item.turn_id, id]) : id
    if (item.role === 'tool') {
      if (item.content.text && typeof item.content.tool_call_id === 'string') blocks.push({ kind: 'tool_result', toolUseId: callId(item.content.tool_call_id), text: nativeResultText(item.content.text), isError: item.content.toolState !== undefined && item.content.toolState !== 'succeeded' })
    } else if (item.role === 'user' || item.role === 'assistant') {
      if (item.content.text) blocks.push({ kind: 'text', text: item.content.text })
      if (item.role === 'assistant') for (const raw of item.content.tool_calls || []) {
        if (!raw || typeof raw !== 'object') continue
        const call = raw as { id?: unknown; function?: { name?: unknown; arguments?: unknown } }
        if (typeof call.id !== 'string' || typeof call.function?.name !== 'string') continue
        blocks.push({ kind: 'tool_use', id: callId(call.id), name: nativeToolNames[call.function.name] || call.function.name, input: typeof call.function.arguments === 'string' ? call.function.arguments : JSON.stringify(call.function.arguments ?? {}) })
      }
    }
    if (item.content.question || item.content.taskStatus || item.content.attachments?.length) blocks.push({ kind: 'native_extra' })
    return blocks.length ? [{ id: item.id, role: item.role, blocks, ...(item.created_ms ? { ts: new Date(item.created_ms).toISOString() } : {}) }] : []
  })
}
