import { expect, it } from 'vitest'
import { agentTimeline } from './agent-timeline'
import { modelLabel } from './agent-models'
import type { AgentActivityItem, AgentMessage } from './agent-protocol'
const message = (id: string, created_ms: number, text = id): AgentMessage => ({ id, branch_id: 'b', role: 'assistant', seq: created_ms, created_ms, status: 'completed', content: { text } })
const step = (id: string, startedMs: number): AgentActivityItem => ({ id, kind: 'tool', name: 'shell', state: 'running', anchorMessageId: 'empty', startedMs, updatedMs: startedMs })
it('keeps actions between replies and later background actions after subsequent messages', () => {
  expect(agentTimeline([message('first', 1), message('empty', 2, ''), message('reply', 5)], [step('later-child', 8), step('command', 3)]).map(e => e.id)).toEqual(['first', 'command', 'reply', 'later-child'])
})
it('renders legacy history without timestamps using the original tool-call anchor', () => {
  const messages = [message('first', 1), message('empty', 2, ''), message('reply', 5)].map(({ created_ms: _time, ...m }) => m)
  expect(agentTimeline(messages, [step('command', 3)]).map(e => e.id)).toEqual(['first', 'command', 'reply'])
})
it('uses one Unicode-safe middle ellipsis rule for model labels and keeps short names complete', () => {
  expect(modelLabel('deepseek-4.1-flash')).toBe('deepseek…1-flash')
  expect(modelLabel('blade-35b')).toBe('blade-35b')
  expect(modelLabel('provider/a-very-long-model-name-1234567')).toBe('provider…1234567')
})
