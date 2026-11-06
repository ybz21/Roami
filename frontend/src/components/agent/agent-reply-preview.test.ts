import { expect, it } from 'vitest'
import { projectAgentEvent, type AgentEvent, type AgentSnapshot } from './agent-protocol'
const snapshot = (): AgentSnapshot => ({ conversation: { id: 'main', title: 'Main', active_branch_id: 'branch', updated_ms: 0 }, branchId: 'branch', messages: [{ id: 'model', branch_id: 'branch', role: 'assistant', seq: 1, turn_id: 'turn', status: 'streaming', content: { text: '' } }], turns: [{ id: 'turn', state: 'running' }], snapshotCursor: 0 })
const preview = (payload: Record<string, any> = {}): AgentEvent => ({ id: 1, kind: 'reply.preview', branchId: 'branch', payload: { messageId: 'model', turnId: 'turn', offset: 0, text: 'Draft', state: 'generating', ...payload } })
it('does not apply a missing prefix or another branch/turn to the candidate', () => {
  const view = snapshot()
  expect(projectAgentEvent(view, preview({ offset: 5 })).reload).toBe(true)
  expect(projectAgentEvent(view, { ...preview(), branchId: 'another' }).view.messages[0].content.replyPreview).toBeUndefined()
  expect(projectAgentEvent(view, preview({ turnId: 'another' })).view.messages[0].content.replyPreview).toBeUndefined()
})
it('does not revive an older model candidate after a new model message starts in the same turn', () => {
  const started = projectAgentEvent(snapshot(), { id: 1, kind: 'message.started', payload: { messageId: 'fresh-model', turnId: 'turn' } }).view
  const late = projectAgentEvent(started, { ...preview(), id: 2 }).view
  expect(late.messages.every(message => !message.content.replyPreview)).toBe(true)
})
it('resets and clears only the selected candidate without setting final body text', () => {
  const first = projectAgentEvent(snapshot(), preview()).view
  const reset = projectAgentEvent(first, { ...preview({ reset: true, text: 'Corrected', state: 'checking' }), id: 2 }).view
  expect(reset.messages[0].content.replyPreview?.text).toBe('Corrected')
  expect(reset.messages[0].content.text).toBe('')
  expect(reset.turns[0].state).toBe('running')
  const cleared = projectAgentEvent(reset, { ...preview({ clear: true }), id: 3 }).view
  expect(cleared.messages[0].content.replyPreview).toBeUndefined()
})
