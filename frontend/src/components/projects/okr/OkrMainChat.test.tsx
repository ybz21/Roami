// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OkrMainChat from './OkrMainChat'
import { emptyConfiguration } from './okr-workspace'
const state = vi.hoisted(() => ({ api: vi.fn(), refresh: vi.fn(), thread: vi.fn(), globalNode: null as string | null }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: false, size: 'large' }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../cluster/node-url', () => ({ useCurrentNodeId: () => null, currentNodeId: () => state.globalNode }))
vi.mock('../../agent/useAgentThread', () => ({ useAgentThread: (...args: unknown[]) => { state.thread(...args); return { refresh: state.refresh, view: null } } }))
vi.mock('../../shell/AdaptivePanel', () => ({ default: ({ children }: any) => children }))
vi.mock('../../markdown/Markdown', () => ({ default: ({ children }: any) => children }))
beforeEach(() => { state.globalNode = null; localStorage.clear(); state.thread.mockReset(); state.api.mockReset(); state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkr: true, projectOkrMain: true } : path === '/agent/conversations' ? { id: 'independent' } : { kind: 'message' } })); window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
afterEach(cleanup)
it('restores the same persistent Main when reopened and closing the view never stops it', async () => {
  const close = vi.fn()
  const view = render(<OkrMainChat projectId="project" projectDir="/repo" draft={emptyConfiguration()} workspace={null} onClose={close} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('independent', '', null, ''))
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Help define my goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/agent/conversations/independent/messages', expect.objectContaining({ text: expect.stringContaining('"projectId":"project"') })))
  expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages')).every(call => call[1] === '/agent/conversations/independent/messages')).toBe(true)
  expect(state.api.mock.calls.find(call => call[1] === '/agent/conversations')[2]).toMatchObject({ projectId: 'project' })
  const first = state.api.mock.calls.find(call => call[1] === '/agent/conversations')[2].requestKey
  fireEvent.click(screen.getByRole('button', { name: 'okr.endChat' }))
  await waitFor(() => expect(close).toHaveBeenCalledOnce())
  expect(state.api.mock.calls.some(call => call[2]?.text === '/stop')).toBe(false)
  view.unmount()
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[1] === '/agent/conversations')).toHaveLength(2))
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'New discussion' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[1] === '/agent/conversations')).toHaveLength(2))
  expect(state.api.mock.calls.filter(call => call[1] === '/agent/conversations')[1][2].requestKey).not.toBe(first)
})
it('preserves the draft and reuses the exact message key after an ambiguous failure', async () => {
  let failed = false
  state.api.mockImplementation(async (_method, path) => {
    if (path === '/agent/status') return { data: { projectOkr: true, projectOkrMain: true } }
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

it('preserves input and explains a runtime that cannot bind project conversations', async () => {
  state.api.mockResolvedValue({ data: { version: 'older-runtime' } })
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Keep the goal in this project' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByText('okr.agentUpgradeRequired')
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe('Keep the goal in this project')
  expect(state.api.mock.calls.every(call => call[1] === '/agent/status')).toBe(true)
})

const savedWorkspace = () => ({ ...emptyConfiguration(), projectId: 'project', revision: 1, updatedAt: 'now', observations: [], reviews: [], swarm: 'sw-existing' })
it('restores an existing exclusive team Main on older runtimes without creating a replacement', async () => {
  const team = { id: 'sw-existing', mainConversationId: 'existing-main', target: { projectId: 'project' } }
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? {} : path === '/agent/main-conversation' ? { id: 'home' } : path === '/agent/swarms' ? [team] : team }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('existing-main', '', null, ''))
  expect(state.api.mock.calls.some(call => call[1] === '/agent/conversations')).toBe(false)
  expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(false)
})
it.each(['home', 'other-project'])('rejects an old team Main shared with %s', async kind => {
  const team = { id: 'sw-existing', mainConversationId: 'existing-main', target: { projectId: 'project' } }
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? {} : path === '/agent/main-conversation' ? { id: kind === 'home' ? 'existing-main' : 'home' } : path === '/agent/swarms' ? [team, { ...team, target: { projectId: 'other-project' } }] : team }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  await screen.findByRole('alert')
  expect(state.thread.mock.calls.every(call => !call[0])).toBe(true)
  expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(false)
})
it('restores the unsent project draft after closing and reopening', async () => {
  const view = render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Keep my next instruction' } })
  view.unmount()
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe('Keep my next instruction')
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('independent', '', null, ''))
})
it('keeps a private Main instruction out of the shared group even when a team exists', async () => {
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('independent', '', null, ''))
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: '@writer needs a new plan' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/agent/conversations/independent/messages', expect.objectContaining({ text: expect.stringContaining('@writer needs a new plan'), requestKey: expect.any(String) })))
  expect(state.api.mock.calls.some(call => call[1] === '/agent/swarms/sw-existing/messages')).toBe(false)
})


it('opens a verified project notification in the existing Main without creating or sending anything', async () => {
  const team = { id: 'sw-existing', mainConversationId: 'existing-main', target: { projectId: 'project' } }
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true } : path === '/agent/main-conversation' ? { id: 'home' } : path === '/agent/swarms' ? [team] : team }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} reference={{ conversationId: 'existing-main', branchId: 'original-branch', messageId: 'original-message' }} onClose={vi.fn()} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('existing-main', 'original-branch', null, 'original-message'))
  expect(state.api.mock.calls.some(call => call[1] === '/agent/conversations' || call[1].endsWith('/messages'))).toBe(false)
})

it('rejects a notification for another conversation and keeps the project draft', async () => {
  const team = { id: 'sw-existing', mainConversationId: 'existing-main', target: { projectId: 'project' } }
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true } : path === '/agent/main-conversation' ? { id: 'home' } : path === '/agent/swarms' ? [team] : team }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} reference={{ conversationId: 'another-project-main', branchId: '', messageId: '' }} onClose={vi.fn()} />)
  await screen.findByRole('alert')
  expect(state.thread.mock.calls.every(call => !call[0])).toBe(true)
  expect(state.api.mock.calls.some(call => call[1] === '/agent/conversations' || call[1].endsWith('/messages'))).toBe(false)
})

it('restores a referenced fixed Main before a team exists using read-only identity', async () => {
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true, conversationIdentity: true } : { kind: 'project_main', projectId: 'project', conversationId: 'fixed-main' } }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} reference={{ conversationId: 'fixed-main', branchId: 'branch', messageId: 'message' }} onClose={vi.fn()} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('fixed-main', 'branch', null, 'message'))
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})

it('does not create or send on a newly selected node before React re-renders', async () => {
  let resolve!: (value: unknown) => void
  state.api.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Keep this project request' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  state.globalNode = 'another-node'
  resolve({ data: { projectOkrMain: true } })
  await screen.findByRole('alert')
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe('Keep this project request')
})
