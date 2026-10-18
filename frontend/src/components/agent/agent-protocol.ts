export type AgentQuestion = { prompt: string; options: { label: string; description?: string }[] }
export type AgentConversation = { id: string; title: string; active_branch_id: string; updated_ms: number }
export type AgentMessage = {
  id: string; branch_id: string; role: string; status: string; seq: number; turn_id?: string; created_ms?: number
  content: { question?: AgentQuestion; text?: string; tool_calls?: unknown[]; taskStatus?: { taskId: string; state: string; errorCode?: string; reportError?: string }; attachments?: { id: string; name: string; sizeBytes: number; mimeType: string; previewState?: string }[] }; completedEventId?: number
}
export type AgentActivityItem = { id: string; kind: 'tool' | 'task' | 'turn'; name: string; anchorMessageId: string; taskId?: string; parentTaskId?: string | null; state: string; target?: string; delivered?: boolean; external?: boolean; startedMs: number; updatedMs: number; errorCode?: string | null }
export type AgentTurn = { id: string; state: string }
export type AgentSnapshot = { conversation: AgentConversation; branchId: string; messages: AgentMessage[]; turns: AgentTurn[]; activities?: AgentActivityItem[]; snapshotCursor: number; compaction?: { operationId: string; state: string; snapshotId?: string; error?: string } | null }
export type AgentEvent = { id: number; kind: string; created_ms?: number; branchId?: string; message_id?: string; turn_id?: string; payload: Record<string, any> }
export type AgentNotice = { id: number; message_id?: string; conversation_id: string; branch_id: string; title: string; content_json: string; created_ms: number }
export type AgentTask = { id: string; state: string; revision: number; parent_task_id?: string | null; intent_json: string; latestAttempt?: { sessionId?: string; workspace?: { directory: string; branch?: string }; state: string } | null }

export function projectAgentEvent(view: AgentSnapshot, event: AgentEvent): { view: AgentSnapshot; reload: boolean } {
  if (event.id <= view.snapshotCursor) return { view, reload: false }
  const next = { ...view, snapshotCursor: event.id }
  if (event.branchId && event.branchId !== view.branchId) return { view: next, reload: false }
  const data = event.payload
  if ((event.kind.startsWith('tool.') || event.kind.startsWith('task.')) && data.activity) {
    const item = data.activity as AgentActivityItem
    next.activities = [...(view.activities || []).filter(existing => existing.id !== item.id), item]
      .sort((a, b) => a.startedMs - b.startedMs || a.id.localeCompare(b.id)).slice(-200)
    return { view: next, reload: false }
  }
  if (event.kind === 'turn.failed' || event.kind === 'turn.interrupted') {
    next.turns = view.turns.map(turn => turn.id === data.turnId ? { ...turn, state: event.kind.slice(5) } : turn)
    next.messages = view.messages.map(message => message.turn_id === data.turnId && message.status === 'streaming' ? { ...message, status: event.kind.slice(5) } : message)
    return { view: next, reload: true }
  }
  if (event.kind === 'message.started') {
    if (!view.messages.some((m) => m.id === data.messageId)) next.messages = [...view.messages, {
      id: data.messageId, branch_id: view.branchId, role: 'assistant', status: 'streaming',
      created_ms: event.created_ms, turn_id: data.turnId, seq: Math.max(0, ...view.messages.map((m) => m.seq)) + 1, content: { text: '' },
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
    next.messages = view.messages.map((m) => m.id === data.messageId ? { ...m, content: { ...m.content, ...(data.question ? { question: data.question } : {}) }, status: 'completed', completedEventId: event.id } : m)
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
