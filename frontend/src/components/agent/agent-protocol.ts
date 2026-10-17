export type AgentConversation = { id: string; title: string; active_branch_id: string; updated_ms: number }
export type AgentMessage = {
  id: string; branch_id: string; role: string; status: string; seq: number; turn_id?: string
  content: { text?: string; tool_calls?: unknown[] }; completedEventId?: number
}
export type AgentTurn = { id: string; state: string }
export type AgentSnapshot = { conversation: AgentConversation; branchId: string; messages: AgentMessage[]; turns: AgentTurn[]; snapshotCursor: number; compaction?: { operationId: string; state: string; snapshotId?: string; error?: string } | null }
export type AgentEvent = { id: number; kind: string; branchId?: string; message_id?: string; turn_id?: string; payload: Record<string, any> }
export type AgentNotice = { id: number; conversation_id: string; branch_id: string; title: string; content_json: string; created_ms: number }
export type AgentTask = { id: string; state: string; intent_json: string; latestAttempt?: { sessionId?: string; workspace?: { directory: string; branch?: string }; state: string } }

export function projectAgentEvent(view: AgentSnapshot, event: AgentEvent): { view: AgentSnapshot; reload: boolean } {
  if (event.id <= view.snapshotCursor) return { view, reload: false }
  const next = { ...view, snapshotCursor: event.id }
  if (event.branchId && event.branchId !== view.branchId) return { view: next, reload: false }
  const data = event.payload
  if (event.kind === 'message.started') {
    if (!view.messages.some((m) => m.id === data.messageId)) next.messages = [...view.messages, {
      id: data.messageId, branch_id: view.branchId, role: 'assistant', status: 'streaming',
      turn_id: data.turnId, seq: Math.max(0, ...view.messages.map((m) => m.seq)) + 1, content: { text: '' },
    }]
    next.turns = [...view.turns.filter((t) => t.id !== data.turnId), { id: data.turnId, state: 'running' }]
    return { view: next, reload: false }
  }
  if (event.kind === 'message.delta') {
    const message = view.messages.find((m) => m.id === data.messageId)
    if (!message || Array.from(message.content.text || '').length !== data.offset) return { view: next, reload: true }
    next.messages = view.messages.map((m) => m.id === message.id ? { ...m, content: { ...m.content, text: (m.content.text || '') + data.text } } : m)
    return { view: next, reload: false }
  }
  if (event.kind.startsWith('context.compaction.')) next.compaction = { operationId: data.operationId, state: event.kind.split('.').pop() || '', snapshotId: data.snapshotId }
  if (event.kind === 'message.completed') {
    next.messages = view.messages.map((m) => m.id === data.messageId ? { ...m, status: 'completed', completedEventId: event.id } : m)
    next.turns = view.turns.map((t) => t.id === data.turnId ? { ...t, state: 'completed' } : t)
  }
  return { view: next, reload: true }
}

export async function* agentEvents(response: Response): AsyncGenerator<AgentEvent> {
  if (!response.body) throw new Error('EVENT_STREAM_MISSING')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      if (buffer.length > 1_000_000) throw new Error('EVENT_FRAME_TOO_LARGE')
      let match: RegExpExecArray | null
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, match.index)
        buffer = buffer.slice(match.index + match[0].length)
        const data = frame.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).replace(/^ /, '')).join('\n')
        if (data) yield JSON.parse(data) as AgentEvent
      }
      if (done) return
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
}
