import { describe, expect, it } from 'vitest'
import { agentEvents, projectAgentEvent, type AgentSnapshot } from './agent-protocol'
import { agentTimeline } from './agent-timeline'

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

it('stops the running indicator immediately when a turn fails', () => {
  const view = projectAgentEvent(snapshot(), { id: 2, kind: 'message.started', payload: { messageId: 'm', turnId: 't' } }).view
  const failed = projectAgentEvent(view, { id: 3, kind: 'turn.failed', payload: { turnId: 't', error: 'CONTEXT_TOO_LARGE' } })
  expect(failed.reload).toBe(true)
  expect(failed.view.turns[0].state).toBe('failed')
  expect(failed.view.messages[0].status).toBe('failed')
})

it('settles tool-call messages before the next reply starts while history is delayed', () => {
  const calls = [{ id: 'read', function: { name: 'read', arguments: '{}' } }]
  let view = projectAgentEvent(snapshot(), { id: 2, kind: 'message.started', payload: { messageId: 'tools', turnId: 't' } }).view
  const settled = projectAgentEvent(view, { id: 3, kind: 'message.tool_calls', payload: { messageId: 'tools', calls } })
  expect(settled.view.messages[0]).toMatchObject({ status: 'completed', content: { tool_calls: calls } })
  expect(settled.view.turns[0].state).toBe('running')
  expect(settled.reload).toBe(true)
  view = projectAgentEvent(settled.view, { id: 4, kind: 'message.started', payload: { messageId: 'reply', turnId: 't' } }).view
  expect(agentTimeline(view.messages, []).map(entry => entry.id)).toEqual(['reply'])
})

it('clears the old typing indicator immediately when a new message defers the turn', () => {
  const started = projectAgentEvent(snapshot(), { id: 2, kind: 'message.started', payload: { messageId: 'old', turnId: 'old-turn' } }).view
  const deferred = projectAgentEvent(started, { id: 3, kind: 'turn.deferred', payload: { turnId: 'old-turn', reason: 'NEW_USER_INTENT' } })
  expect(deferred.view.messages[0].status).toBe('interrupted')
  expect(deferred.view.turns[0].state).toBe('queued')
  expect(agentTimeline(deferred.view.messages, [])).toEqual([])
  const next = projectAgentEvent(deferred.view, { id: 4, kind: 'message.started', payload: { messageId: 'new', turnId: 'new-turn' } }).view
  expect(agentTimeline(next.messages, []).map(entry => entry.id)).toEqual(['new'])
})

it('hides routine tools while retaining unknown outcomes and replay ordering', () => {
  const activity = { id: 'tool:one', kind: 'tool', name: 'shell', anchorMessageId: 'm', state: 'running', startedMs: 100, updatedMs: 100 }
  const start = { id: 2, kind: 'tool.started', branchId: 'b', payload: { activity } }
  const running = projectAgentEvent(snapshot(), start)
  expect(running.reload).toBe(false)
  expect(running.view.activities).toEqual([])
  const done = projectAgentEvent(running.view, { ...start, id: 3, kind: 'tool.completed', payload: { activity: { ...activity, state: 'unknown', updatedMs: 200 } } })
  expect(done.reload).toBe(false)
  expect(done.view.activities).toHaveLength(1)
  expect(done.view.activities?.[0].state).toBe('unknown')
  expect(projectAgentEvent(done.view, start).view).toBe(done.view)
  expect(projectAgentEvent(done.view, { id: 4, kind: 'tool.completed', payload: { toolCallId: 'old' } }).reload).toBe(true)
  expect(projectAgentEvent(snapshot(), { ...start, branchId: 'other' }).view.activities).toBeUndefined()
})

it('shows a streamed choice question even when the assistant has no text', () => {
  const question = { prompt: 'Which session?', options: [{ label: 'A' }, { label: 'B' }] }
  const started = projectAgentEvent(snapshot(), { id: 2, kind: 'message.started', payload: { messageId: 'q', turnId: 't' } }).view
  const completed = projectAgentEvent(started, { id: 3, kind: 'message.completed', payload: { messageId: 'q', turnId: 't', question } }).view
  expect(completed.messages[0].content.question).toEqual(question)
  expect(completed.turns[0].state).toBe('completed')
})
