// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OkrMainChat from './OkrMainChat'
import { emptyConfiguration, type Workspace } from './okr-workspace'
const state = vi.hoisted(() => ({ api: vi.fn(), refresh: vi.fn(), thread: vi.fn(), view: null as any, globalNode: null as string | null }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: false, size: 'large' }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../cluster/node-url', () => ({ useCurrentNodeId: () => null, currentNodeId: () => state.globalNode, nodeApi: (path: string) => '/api' + path }))
vi.mock('../../agent/useAgentThread', () => ({ useAgentThread: (...args: unknown[]) => { state.thread(...args); return { accepted: vi.fn(), refresh: state.refresh, view: state.view } } }))
vi.mock('../../shell/AdaptivePanel', () => ({ default: ({ children }: any) => children }))
vi.mock('../../markdown/Markdown', () => ({ default: ({ children }: any) => children }))
beforeEach(() => { state.view = null; state.globalNode = null; localStorage.clear(); state.thread.mockReset(); state.api.mockReset(); state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkr: true, projectOkrMain: true, okrMessageContext: true } : path === '/agent/model-settings' ? { main: { model: 'saved-main', reasoningEffort: 'low', reasoningEfforts: ['low', 'high'], reasoningSupport: 'supported', images: true }, worker: { model: 'saved-worker' } } : path === '/agent/conversations' ? { id: 'independent' } : { kind: 'message' } })); window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('restores the same persistent Main when reopened and closing the view never stops it', async () => {
  const close = vi.fn()
  const view = render(<OkrMainChat projectId="project" projectDir="/repo" draft={emptyConfiguration()} workspace={null} onClose={close} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('independent', '', null, ''))
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Help define my goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/agent/conversations/independent/messages', expect.objectContaining({ text: 'Help define my goal', okrContext: expect.objectContaining({ version: 1, revision: 0 }) })))
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
    if (path === '/agent/status') return { data: { projectOkr: true, projectOkrMain: true, okrMessageContext: true } }
    if (path === '/agent/main-conversation') return { data: { id: 'home' } }
    if (path === '/agent/conversations') return { data: { id: 'independent' } }
    if (!path.endsWith('/messages')) return { data: {} }
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

it('sends literal instructions without duplicating saved history, skills or project guidance', async () => {
  const workspace: Workspace = { ...emptyConfiguration(), projectId: 'project', revision: 8, updatedAt: 'now', observations: [], reviews: [], objective: 'Automatic publishing', projectFiles: { root: '.roami/okr', schemaVersion: 1, revision: 8, mainInstructions: 'Old publishing ban', teamMemory: 'x'.repeat(44000), skills: [{ id: 'source', path: 'source/SKILL.md', content: 'old instructions', sha256: 'hash' }] } }
  render(<OkrMainChat projectId="project" draft={workspace} workspace={workspace} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Automatically review, publish and collect' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(true))
  const payload = state.api.mock.calls.find(call => call[1].endsWith('/messages'))![2]
  expect(payload.text).toBe('Automatically review, publish and collect')
  expect(payload.okrContext).toEqual({ version: 1, revision: 8 })
  expect(JSON.stringify(payload)).not.toContain('Old publishing ban')
  expect(JSON.stringify(payload).length).toBeLessThan(400)
})

it('preserves input and explains a runtime that cannot bind project conversations', async () => {
  state.api.mockResolvedValue({ data: { version: 'older-runtime' } })
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Keep the goal in this project' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByText('okr.agentUpgradeRequired')
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe('Keep the goal in this project')
  expect(state.api.mock.calls.every(call => call[0] === 'GET' && ['/agent/status', '/agent/model-settings', '/speech/config'].includes(call[1]))).toBe(true)
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
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true, okrMessageContext: true } : path === '/agent/main-conversation' ? { id: 'home' } : path === '/agent/swarms' ? [team] : team }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} reference={{ conversationId: 'existing-main', branchId: 'original-branch', messageId: 'original-message' }} onClose={vi.fn()} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('existing-main', 'original-branch', null, 'original-message'))
  expect(state.api.mock.calls.some(call => call[1] === '/agent/conversations' || call[1].endsWith('/messages'))).toBe(false)
})

it('rejects a notification for another conversation and keeps the project draft', async () => {
  const team = { id: 'sw-existing', mainConversationId: 'existing-main', target: { projectId: 'project' } }
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true, okrMessageContext: true } : path === '/agent/main-conversation' ? { id: 'home' } : path === '/agent/swarms' ? [team] : team }))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} reference={{ conversationId: 'another-project-main', branchId: '', messageId: '' }} onClose={vi.fn()} />)
  await screen.findByRole('alert')
  expect(state.thread.mock.calls.every(call => !call[0])).toBe(true)
  expect(state.api.mock.calls.some(call => call[1] === '/agent/conversations' || call[1].endsWith('/messages'))).toBe(false)
})

it('restores a referenced fixed Main before a team exists using read-only identity', async () => {
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true, okrMessageContext: true, conversationIdentity: true } : { kind: 'project_main', projectId: 'project', conversationId: 'fixed-main' } }))
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
  resolve({ data: { projectOkrMain: true, okrMessageContext: true } })
  await screen.findByRole('alert')
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe('Keep this project request')
})


it('keeps unsaved dashboard, source and team edits in separate reference data', async () => {
  const workspace = savedWorkspace()
  const draft = { ...workspace, objective: 'New objective', dashboard: { schemaVersion: 2 as const, widgets: [], html: { entry: 'dashboard/index.html', assets: ['dashboard/index.html'], metricIds: ['users'] } }, team: { schemaVersion: 1 as const, roles: [{ id: 'data', name: 'Data', executor: 'native' as const, duty: 'Review facts', memberId: 'original-member' }] } }
  render(<OkrMainChat projectId="project" draft={draft} workspace={workspace} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Discuss these edits' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(true))
  const payload = state.api.mock.calls.find(call => call[1].endsWith('/messages'))![2]
  expect(payload.text).toBe('Discuss these edits')
  expect(payload.okrContext).toMatchObject({ version: 1, revision: 1, draft: { objective: 'New objective', dashboard: draft.dashboard, team: draft.team } })
  expect(payload.okrContext.draft).not.toHaveProperty('projectId')
  expect(payload.okrContext.draft).not.toHaveProperty('observations')
})

it('preserves an unsaved draft on an older host but sends saved discussion literally', async () => {
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true } : path === '/agent/conversations' ? { id: 'independent' } : { kind: 'message' } }))
  const workspace = savedWorkspace()
  const view = render(<OkrMainChat projectId="project" draft={{ ...workspace, objective: 'Unsaved edit' }} workspace={workspace} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Discuss my edit' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByRole('alert')
  expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(false)
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe('Discuss my edit')
  view.rerender(<OkrMainChat projectId="project" draft={workspace} workspace={workspace} onClose={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(true))
  const payload = state.api.mock.calls.find(call => call[1].endsWith('/messages'))![2]
  expect(payload.text).toBe('Discuss my edit')
  expect(payload).not.toHaveProperty('okrContext')
})

it('reuses the complete composer and reads Main model settings without changing them', async () => {
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  await screen.findByText('saved-main')
  expect(screen.queryByText('saved-worker')).toBeNull()
  expect(screen.getByRole('button', { name: 'agent.reasoning.picker' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'agent.composer.more' })).toBeTruthy()
  expect(document.querySelector('.conversation-composer .tt-cend button')).toBeTruthy()
  expect(state.api.mock.calls.some(call => call[0] === 'PUT')).toBe(false)
})
it('sends restored attachments through the original project Main and preserves the exact retry payload', async () => {
  const attachment = { key: 'file-key', name: 'source.csv', sizeBytes: 12, state: 'ready', reference: { id: 'file-id', name: 'source.csv', sizeBytes: 12, mimeType: 'text/csv' } }
  localStorage.setItem('roami.agent.attachments.roami.okr.main.draft:local:project', JSON.stringify([attachment]))
  let count = 0
  state.api.mockImplementation(async (_method, path) => {
    if (path === '/agent/status') return { data: { projectOkrMain: true, okrMessageContext: true } }
    if (path === '/agent/conversations') return { data: { id: 'original-main' } }
    if (path.endsWith('/messages') && count++ === 0) throw Error('ambiguous')
    return { data: {} }
  })
  const view = render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  await screen.findByText('source.csv')
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByRole('alert')
  const first = state.api.mock.calls.find(call => call[1].endsWith('/messages'))![2]
  expect(first.attachmentIds).toEqual(['file-id'])
  view.unmount()
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  await screen.findByText('source.csv')
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages'))).toHaveLength(2))
  expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages'))[1][2]).toEqual(first)
  await waitFor(() => expect(screen.queryByText('source.csv')).toBeNull())
})
it('sends an explicit slash command without adding the OKR context to its argument', async () => {
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: '/status' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(true))
  expect(state.api.mock.calls.find(call => call[1].endsWith('/messages'))![2]).toMatchObject({ text: '/status', attachmentIds: [] })
})


it('blocks sending until a real attachment upload finishes', async () => {
  let finish!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('agent.composer.addFiles'), { target: { files: [new File(['facts'], 'source.csv', { type: 'text/csv' })] } })
  await screen.findByText('agent.composer.uploading')
  expect((screen.getByRole('button', { name: 'okr.send' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(false)
  finish({ ok: true, json: async () => ({ data: { id: 'uploaded-file', name: 'source.csv', sizeBytes: 5, mimeType: 'text/csv' } }) })
  await screen.findByText('agent.composer.fileReady')
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(true))
  expect(state.api.mock.calls.find(call => call[1].endsWith('/messages'))![2].attachmentIds).toEqual(['uploaded-file'])
})
it('keeps a later Main draft when an earlier send returns', async () => {
  let finish!: (value: unknown) => void
  state.api.mockImplementation(async (_method, path) => {
    if (path === '/agent/status') return { data: { projectOkrMain: true, okrMessageContext: true } }
    if (path === '/agent/conversations') return { data: { id: 'original-main' } }
    if (path.endsWith('/messages')) return new Promise(resolve => { finish = resolve })
    return { data: {} }
  })
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  const input = screen.getByLabelText('okr.chatInput')
  fireEvent.change(input, { target: { value: 'First instruction' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  fireEvent.change(input, { target: { value: 'Next instruction' } })
  finish({ data: { kind: 'message' } })
  await waitFor(() => expect(screen.getByRole('button', { name: 'okr.send' }).getAttribute('aria-busy')).toBeNull())
  expect((input as HTMLTextAreaElement).value).toBe('Next instruction')
})
it('keeps historical Main branches read only with the complete composer', async () => {
  state.view = { branchId: 'historical', conversation: { active_branch_id: 'current' }, messages: [], turns: [] }
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={savedWorkspace()} onClose={vi.fn()} />)
  await screen.findByText('agent.historicalBranch')
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: 'agent.composer.more' }) as HTMLButtonElement).disabled).toBe(true)
  expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(false)
})

it('refuses a restored ambiguous request bound to a different Main instead of rekeying or retargeting it', async () => {
  const pending = { text: 'Original request', payload: 'Original request\noriginal context', key: 'same-key', conversationId: 'old-main', attachmentIds: [] }
  localStorage.setItem('roami.okr.main.draft:local:project:pending', JSON.stringify(pending))
  localStorage.setItem('roami.okr.main.draft:local:project', pending.text)
  render(<OkrMainChat projectId="project" draft={emptyConfiguration()} workspace={null} onClose={vi.fn()} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('independent', '', null, ''))
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByRole('alert')
  expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(false)
  expect(JSON.parse(localStorage.getItem('roami.okr.main.draft:local:project:pending')!)).toEqual(pending)
  expect((screen.getByLabelText('okr.chatInput') as HTMLTextAreaElement).value).toBe(pending.text)
})

it('retries an ambiguous direct message with its original key even if SSE already shows Main running', async () => {
  let count = 0
  state.api.mockImplementation(async (_method, path) => {
    if (path === '/agent/status') return { data: { projectOkrMain: true, okrMessageContext: true } }
    if (path === '/agent/conversations') return { data: { id: 'original-main' } }
    if (path.endsWith('/messages') && count++ === 0) throw Error('lost receipt')
    return { data: {} }
  })
  const props = { projectId: 'project', draft: emptyConfiguration(), workspace: null, onClose: vi.fn() }
  const page = render(<OkrMainChat {...props} />)
  await waitFor(() => expect(state.thread).toHaveBeenCalledWith('original-main', '', null, ''))
  fireEvent.change(screen.getByLabelText('okr.chatInput'), { target: { value: 'Keep one instruction' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await screen.findByRole('alert')
  state.view = { branchId: 'current', conversation: { id: 'original-main', active_branch_id: 'current' }, messages: [], turns: [{ id: 'accepted-turn', state: 'running' }] }
  page.rerender(<OkrMainChat {...props} />)
  fireEvent.click(screen.getByRole('button', { name: 'okr.send' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages'))).toHaveLength(2))
  const messages = state.api.mock.calls.filter(call => call[1].endsWith('/messages'))
  expect(messages[0][2]).toEqual(messages[1][2])
  expect(screen.queryByRole('region', { name: 'agent.outbox.title' })).toBeNull()
})
