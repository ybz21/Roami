// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentDebug from './AgentDebug'

vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('./useAgentData', () => ({ useAgentData: (path: string) => ({ value: path?.includes('/trace?') ? {
  traceId: 'request', observedAtMs: 100, summary: { active: false, durationMs: 100, firstCommittedTextMs: null, modelCalls: 500, toolCalls: 0, taskStates: {} }, coverage: {},
  spans: [{ spanId: 'root', parentSpanId: null, name: 'agent.execution', state: 'completed', startedMs: 0, durationMs: 100, attributes: {} }, ...Array.from({ length: 500 }, (_, i) => ({ spanId: 'span-' + i, parentSpanId: 'root', name: 'model.request', state: 'succeeded', startedMs: 0, durationMs: 1, attributes: { context: { estimator: 'estimate for span-' + i } } }))],
} : undefined, loading: false, failed: false }) }))

afterEach(cleanup)

it('bounds the initial trace DOM and only mounts model metadata after disclosure', () => {
  render(<AgentDebug cid="conversation" branch="branch" node={null} selected="turn:request" onSelect={vi.fn()} />)
  const rows = () => document.querySelectorAll('.agent-debug-spans > li').length
  expect(rows()).toBeLessThanOrEqual(200)
  expect(screen.queryByText('estimate for span-0')).toBeNull()
  const details = screen.getAllByText('model.request')[0].closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  expect(screen.getByText('estimate for span-0')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'agent.debug.moreSpans' }))
  expect(rows()).toBeGreaterThan(200)
  expect(rows()).toBeLessThan(501)
})
