// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OkrMainChat from './OkrMainChat'
import { emptyConfiguration } from './okr-workspace'
const state = vi.hoisted(() => ({ api: vi.fn(), refresh: vi.fn() }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: false, size: 'large' }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../agent/useAgentThread', () => ({ useAgentThread: () => ({ refresh: state.refresh, view: null }) }))
vi.mock('../../shell/AdaptivePanel', () => ({ default: ({ children }: any) => children }))
vi.mock('../../markdown/Markdown', () => ({ default: ({ children }: any) => children }))
beforeEach(() => { state.api.mockReset(); state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/conversations' ? { id: 'independent' } : { kind: 'message' } })); window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
afterEach(cleanup)
it('creates an independent Main instance only on first send and closes only that conversation', async () => {
  const close = vi.fn()
  const view = render(<OkrMainChat projectId="project" projectDir="/repo" draft={emptyConfiguration()} workspace={null} onClose={close} />)
  expect(state.api).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Help define my goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/agent/conversations/independent/messages', expect.objectContaining({ text: expect.stringContaining('"projectId":"project"') })))
  expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages')).every(call => call[1] === '/agent/conversations/independent/messages')).toBe(true)
  expect(state.api.mock.calls.find(call => call[1] === '/agent/conversations')[2]).toMatchObject({ projectId: 'project' })
  const first = state.api.mock.calls.find(call => call[1] === '/agent/conversations')[2].requestKey
  fireEvent.click(screen.getByRole('button', { name: 'okr.endChat' }))
  await waitFor(() => expect(close).toHaveBeenCalledOnce())
  expect(state.api).toHaveBeenCalledWith('POST', '/agent/conversations/independent/messages', expect.objectContaining({ text: '/stop' }))
  view.unmount()
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'New discussion' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[1] === '/agent/conversations')).toHaveLength(2))
  expect(state.api.mock.calls.filter(call => call[1] === '/agent/conversations')[1][2].requestKey).not.toBe(first)
})
it('preserves the draft and reuses the exact message key after an ambiguous failure', async () => {
  let failed = false
  state.api.mockImplementation(async (_method, path) => {
    if (path === '/agent/main-conversation') return { data: { id: 'home' } }
    if (path === '/agent/conversations') return { data: { id: 'independent' } }
    if (!failed) { failed = true; throw new Error('lost receipt') }
    return { data: { kind: 'message' } }
  })
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Keep this request' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe('Keep this request')
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages'))).toHaveLength(2))
  const calls = state.api.mock.calls.filter(call => call[1].endsWith('/messages'))
  expect(calls[0][2]).toEqual(calls[1][2])
  expect(state.api.mock.calls.filter(call => call[1] === '/agent/conversations')).toHaveLength(1)
})

it('provides verified board evidence for analysis without requiring unregistered CLI access', async () => {
  const draft = emptyConfiguration()
  const workspace = { ...draft, projectId: 'project', revision: 8, updatedAt: '2026-11-03T10:00:00Z', objective: 'Grow the project', keyResults: [{ id: 'growth', title: 'Stars', horizon: 'long' as const, metricId: 'stars', target: 100, mode: 'increase' as const, dueDate: draft.endDate }], metrics: [{ id: 'stars', name: 'Stars', unit: 'stars', source: 'manual' as const }], observations: [{ id: 'one', metricId: 'stars', date: draft.startDate, value: 11, source: 'manual' as const, sourceKey: 'manual:stars', capturedAt: 'now', note: '' }], reviews: [], initiatives: [{ id: 'x-posts', title: 'Product posts', channel: 'x', keyResultIds: ['growth'], description: 'Weekly examples', acceptance: 'Publication receipts' }], dashboard: { schemaVersion: 1 as const, widgets: [{ id: 'stars', type: 'metricTrend' as const, metricIds: ['stars'] }] }, projectFiles: { root: '.roami/okr', schemaVersion: 1 as const, revision: 8, mainInstructions: 'Use the project acceptance process', teamMemory: 'The last video is still unverified' } }
  render(<OkrMainChat projectId="project" draft={draft} workspace={workspace} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'What next?' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(true))
  const payload = state.api.mock.calls.find(call => call[1].endsWith('/messages'))![2].text
  const context = JSON.parse(payload.split('<roami-okr-context>\n')[1].split('\n')[0])
  expect(context.revision).toBe(8)
  expect(context.initiatives).toEqual(workspace.initiatives)
  expect(context.dashboard).toEqual(workspace.dashboard)
  expect(context.projectContext).toMatchObject({ mainInstructions: workspace.projectFiles.mainInstructions, teamMemory: workspace.projectFiles.teamMemory })
  expect(context.snapshot.keyResults[0].latest.value).toBe(11)
  expect(context.snapshot.metrics[0].recentDays[0]).toMatchObject({ value: 11, delta: null })
  expect(state.api.mock.calls.some(call => call[1].includes('/okr'))).toBe(false)
})
