import { describe, expect, it } from 'vitest'
import { agentEvents, projectAgentEvent, type AgentSnapshot } from './agent-protocol'

const snapshot = (): AgentSnapshot => ({ conversation: { id: 'c', title: 'Conversation', active_branch_id: 'b', updated_ms: 0 }, branchId: 'b', messages: [], turns: [], snapshotCursor: 1 })

describe('durable Agent events', () => {
  it('decodes UTF-8 and CRLF frames split at arbitrary byte boundaries', async () => {
    const data = { id: 3, kind: 'message.delta', payload: { text: '中文\uD83D\uDE00', offset: 0 } }
    const bytes = new TextEncoder().encode(': ping\r\n\r\ndata: ' + JSON.stringify(data) + '\r\n\r\n')
    const response = new Response(new ReadableStream({ start(controller) { for (let i = 0; i < bytes.length; i += 2) controller.enqueue(bytes.slice(i, i + 2)); controller.close() } }))
    const results = []
    for await (const event of agentEvents(response)) results.push(event)
    expect(results).toEqual([data])
  })
  it('deduplicates replay and counts Python Unicode offsets rather than UTF-16 units', () => {
    let view = projectAgentEvent(snapshot(), { id: 2, kind: 'message.started', branchId: 'b', payload: { messageId: 'm', turnId: 't' } }).view
    const first = { id: 3, kind: 'message.delta', branchId: 'b', payload: { messageId: 'm', text: '\uD83D\uDE00', offset: 0 } }
    view = projectAgentEvent(view, first).view
    view = projectAgentEvent(view, first).view
    const last = projectAgentEvent(view, { id: 4, kind: 'message.delta', branchId: 'b', payload: { messageId: 'm', text: '继续', offset: 1 } })
    expect(last.reload).toBe(false)
    expect(last.view.messages[0].content.text).toBe('\uD83D\uDE00继续')
    expect(projectAgentEvent(last.view, { id: 5, kind: 'message.delta', payload: { messageId: 'm', text: 'wrong', offset: 99 } }).reload).toBe(true)
  })
  it('never appends another branch reply to the visible conversation branch', () => {
    const projected = projectAgentEvent(snapshot(), { id: 9, kind: 'message.started', branchId: 'other', payload: { messageId: 'm' } })
    expect(projected.view.messages).toEqual([])
    expect(projected.view.snapshotCursor).toBe(9)
  })
})
