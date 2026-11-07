import { expect, it } from 'vitest'
import { displayOkrMessage, okrContextMarker, prepareOkrContext } from './okr-conversation-context'
import { emptyConfiguration, type Workspace } from './okr-workspace'

it('keeps literal markers while hiding only the old generated context envelope', () => {
  const literal = 'Explain' + okrContextMarker + '{"projectId":"project"}\n你是此 OKR 固定的主智能体；old guidance\n</roami-okr-context>'
  expect(displayOkrMessage(literal)).toBe('Explain')
  expect(displayOkrMessage(literal, { okrContext: { version: 1, revision: 1 } })).toBe(literal)
  expect(displayOkrMessage('Explain' + okrContextMarker + 'my own text')).toContain('my own text')
})

it('bounds multilingual drafts by bytes without truncation and excludes slash commands', () => {
  const draft = { ...emptyConfiguration(), objective: '数'.repeat(23000) }
  expect(() => prepareOkrContext('Discuss', draft, null, true)).toThrow('OKR_MESSAGE_CONTEXT_TOO_LARGE')
  expect(draft.objective.length).toBe(23000)
  expect(prepareOkrContext('/stop', draft, null, true)).toBeUndefined()
})

it('compares configuration rather than history or derived source identities', () => {
  const workspace: Workspace = { ...emptyConfiguration(), revision: 3, projectId: 'p', updatedAt: 'now', observations: [], reviews: [], metrics: [{ id: 'users', name: 'Users', unit: 'users', source: 'manual', sourceKey: 'manual:users' }] }
  const draft = { ...workspace, metrics: workspace.metrics.map(({ sourceKey: _source, ...metric }) => metric) }
  expect(prepareOkrContext('Discuss', draft, workspace, true)).toEqual({ version: 1, revision: 3 })
})
