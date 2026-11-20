// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OkrMainChat from './OkrMainChat'
import { emptyConfiguration } from './okr-workspace'
import { nativeMainRequest, transferMainDraft } from './okr-main-native-draft'
import { sessionDraftKey } from '../../chat/session-draft'

const state = vi.hoisted(() => ({ api: vi.fn(), sessions: [] as any[], failed: false, turnState: '', threadFailed: false }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: false, size: 'large' }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../../session-overview', () => ({ useSessionOverview: () => ({ value: state.sessions, loaded: true, failed: state.failed }) }))
vi.mock('../../cluster/node-url', () => ({ useCurrentNodeId: () => null, currentNodeId: () => null, nodeApi: (path: string) => '/api' + path }))
vi.mock('../../agent/useAgentThread', () => ({ useAgentThread: (cid: string) => ({
  failed: state.threadFailed,
  view: cid && state.turnState ? { turns: [{ id: 'current-turn', state: state.turnState }] } : null,
}) }))
vi.mock('../../agent/AgentConversation', () => ({ default: ({ cid, focusMessage, project }: any) => <p>legacy:{cid}:{focusMessage}:{project.nativeModel || ''}:{String(project.modelControlsDisabled)}</p> }))
vi.mock('../../chat/ExecutorSessionChat', () => ({ default: ({ executor, sessionId, mainTurnId, onSend, onCommand }: any) => <><output>{mainTurnId || "no running turn"}</output><button onClick={() => { void onSend('Continue the original team').catch(() => {}) }}>native:{executor}:{sessionId}</button><button onClick={() => { void onCommand('/model').catch(() => {}) }}>model command</button></> }))

const configuration = () => ({ conversationId: 'original-main', projectId: 'project', generation: 1, executor: 'claude', model: 'free', sessionId: 'original-provider' })
const props = () => ({ projectId: 'project', expectedConversationId: 'original-main', draft: emptyConfiguration(), workspace: null, onClose: vi.fn() })
const draftKey = 'roami.okr.main.draft:local:project'
beforeEach(() => {
  localStorage.clear(); state.failed = false; state.turnState = ''; state.threadFailed = false
  state.sessions = [{ name: 'original-provider', agent: 'claude', projectKey: 'project', dormant: false }]
  state.api.mockReset().mockImplementation(async (_method, path) => ({ data:
    path === '/agent/status' ? { projectOkrMain: true, projectMainExecution: true, conversationIdentity: true, okrMessageContext: true }
    : path === '/agent/conversations' ? { id: 'original-main' }
    : path.endsWith('/identity') ? { kind: 'project_main', projectId: 'project', conversationId: 'original-main' }
    : path.endsWith('/execution') ? configuration()
    : { kind: 'message' },
  }))
})
afterEach(cleanup)

it('renders the existing native provider but sends through the original Main queue', async () => {
  render(<OkrMainChat {...props()} />)
  fireEvent.click(await screen.findByText('native:claude:original-provider'))
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/agent/conversations/original-main/messages', expect.objectContaining({ text: 'Continue the original team', requestKey: expect.any(String), okrContext: expect.objectContaining({ version: 1, revision: 0 }) })))
  expect(state.api.mock.calls.some(call => call[1].includes('/sessions/') || call[1] === '/agent/main-conversation')).toBe(false)
  expect(state.api.mock.calls.filter(call => call[1] === '/agent/conversations')).toHaveLength(1)
})

it.each(['project', 'conversation', 'executor', 'generation', 'session'])('rejects a changed %s in the binding before displaying a provider', async kind => {
  const value: any = configuration()
  if (kind === 'project') value.projectId = 'foreign'
  if (kind === 'conversation') value.conversationId = 'home'
  if (kind === 'executor') value.executor = 'terminal'
  if (kind === 'generation') value.generation = 0
  if (kind === 'session') value.sessionId = ''
  state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/status' ? { projectOkrMain: true, projectMainExecution: true } : path === '/agent/conversations' ? { id: 'original-main' } : value }))
  render(<OkrMainChat {...props()} />)
  await screen.findByRole('alert')
  expect(screen.queryByText(/^native:/)).toBeNull()
  expect(state.api.mock.calls.some(call => call[1].endsWith('/messages'))).toBe(false)
})

it('immediately drops a closed or foreign live session and never opens homepage Main', async () => {
  const view = render(<OkrMainChat {...props()} />)
  await screen.findByText('native:claude:original-provider')
  state.sessions = [{ ...state.sessions[0], projectKey: 'foreign' }]
  view.rerender(<OkrMainChat {...props()} />)
  expect(screen.queryByText(/^native:/)).toBeNull()
  expect(screen.getByText('swarm.member.sessionUnavailable')).toBeTruthy()
  expect(state.api.mock.calls.some(call => call[1] === '/agent/main-conversation')).toBe(false)
})

it('retains an ambiguous send key through remount and uses the same Main', async () => {
  const original = state.api.getMockImplementation()!
  let failed = false
  state.api.mockImplementation(async (...args) => {
    if (String(args[1]).endsWith('/messages') && !failed) { failed = true; throw new Error('lost receipt') }
    return original(...args)
  })
  const first = render(<OkrMainChat {...props()} />)
  fireEvent.click(await screen.findByText('native:claude:original-provider'))
  await waitFor(() => expect(localStorage.getItem(draftKey + ':native-pending')).toBeTruthy())
  await act(async () => {})
  const sent = state.api.mock.calls.find(call => call[1].endsWith('/messages'))!
  first.unmount()
  render(<OkrMainChat {...props()} draft={{ ...emptyConfiguration(), objective: 'A different new draft' }} />)
  fireEvent.click(await screen.findByText('native:claude:original-provider'))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages'))).toHaveLength(2))
  expect(state.api.mock.calls.filter(call => call[1].endsWith('/messages'))[1]).toEqual(sent)
})

it('keeps referenced host history and removes global model controls', async () => {
  render(<OkrMainChat {...props()} reference={{ conversationId: 'original-main', branchId: 'original-branch', messageId: 'old-message' }} />)
  await screen.findByText('legacy:original-main:old-message:free:false')
  expect(screen.queryByText(/^native:/)).toBeNull()
})

it('transfers drafts without overwriting native input and retains legacy pending identity', () => {
  localStorage.setItem(draftKey, 'Unsent goal')
  transferMainDraft(draftKey, 'original-provider')
  expect(localStorage.getItem(sessionDraftKey('original-provider'))).toBe('Unsent goal')
  localStorage.setItem(sessionDraftKey('original-provider'), 'New native draft')
  transferMainDraft(draftKey, 'original-provider')
  expect(localStorage.getItem(sessionDraftKey('original-provider'))).toBe('New native draft')
  localStorage.setItem(draftKey + ':pending', JSON.stringify({ cid: 'original-main', text: 'Unsent goal', key: 'original-key' }))
  expect(nativeMainRequest(draftKey, 'original-main', 'Unsent goal').key).toBe('original-key')
  expect(nativeMainRequest(draftKey, 'other-main', 'Unsent goal').key).not.toBe('original-key')
})


it('model commands preserve an uncertain message key and its frozen context', async () => {
  const original = state.api.getMockImplementation()!
  let failed = false
  state.api.mockImplementation(async (...args) => {
    if (String(args[1]).endsWith('/messages') && args[2]?.text !== '/model' && !failed) { failed = true; throw new Error('lost receipt') }
    return original(...args)
  })
  const first = render(<OkrMainChat {...props()} />)
  fireEvent.click(await screen.findByText('native:claude:original-provider'))
  await waitFor(() => expect(localStorage.getItem(draftKey + ':native-pending')).toBeTruthy())
  await act(async () => {})
  const pending = localStorage.getItem(draftKey + ':native-pending')
  const sent = state.api.mock.calls.find(call => call[1].endsWith('/messages'))!
  fireEvent.click(screen.getByText('model command'))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[2]?.text === '/model')).toBe(true))
  await act(async () => {})
  expect(localStorage.getItem(draftKey + ':native-pending')).toBe(pending)
  first.unmount()
  render(<OkrMainChat {...props()} draft={{ ...emptyConfiguration(), objective: 'Changed draft' }} />)
  fireEvent.click(await screen.findByText('native:claude:original-provider'))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[2]?.text === 'Continue the original team')).toHaveLength(2))
  expect(state.api.mock.calls.filter(call => call[2]?.text === 'Continue the original team')[1]).toEqual(sent)
  expect(state.api.mock.calls.find(call => call[2]?.text === '/model')?.[2]).not.toHaveProperty('okrContext')
})

it('forwards the bound Main running turn even before the native transcript can report it', async () => {
  state.turnState = 'queued'
  const view = render(<OkrMainChat {...props()} />)
  await screen.findByText('no running turn')
  state.turnState = 'running'
  view.rerender(<OkrMainChat {...props()} />)
  expect(screen.getByText('current-turn')).toBeTruthy()
  state.threadFailed = true
  view.rerender(<OkrMainChat {...props()} />)
  expect(screen.getByText('no running turn')).toBeTruthy()
  state.threadFailed = false
  state.turnState = 'completed'
  view.rerender(<OkrMainChat {...props()} />)
  expect(screen.getByText('no running turn')).toBeTruthy()
})
