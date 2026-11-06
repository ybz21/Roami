// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SwarmMemberChat from './SwarmMemberChat'
import type { SwarmSnapshot } from './swarm-protocol'
import { swarmMembers } from './swarm-members'

const state = vi.hoisted(() => ({ api: vi.fn(), sessions: [{ name: 'original', agent: 'codex', dormant: false, projectKey: 'project' }], failed: false }))
vi.mock('../../api', () => ({ api: (...args: unknown[]) => state.api(...args) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => ({ value: state.sessions, failed: state.failed }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path, useCurrentNodeId: () => null, currentNodeId: () => null }))
vi.mock('../chat/CodexChat', () => ({ default: ({ name, onSend }: any) => <button onClick={() => { void onSend('Continue').catch(() => {}) }}>codex:{name}</button> }))
vi.mock('../chat/ClaudeChat', () => ({ default: ({ name }: any) => <p>claude:{name}</p> }))
vi.mock('../chat/OpenCodeChat', () => ({ default: ({ name }: any) => <p>opencode:{name}</p> }))
vi.mock('../agent/NativeSession', () => ({ default: ({ id, expectedTask }: any) => <p>native:{id}:{expectedTask.id}</p> }))
function snapshot(executor = 'codex'): SwarmSnapshot {
  return { id: 'swarm', name: 'Team', goal: '', mainConversationId: 'main', revision: 1, sequence: 1, paused: false, archived: false, state: 'running', target: { projectId: 'project' }, memberProtocol: 1, posts: [], mainMessages: [], work: [{ id: 'work', memberId: 'member', member_name: 'Member', executor, title: 'Work', goal: '', acceptance: '', integration: 0, dependencies: [], dispatch_error: null, task_id: 'task', revision: 2, state: 'running', attempt: { runId: 'run', state: 'running', sessionId: 'original' } }], members: [{ id: 'member', swarm_id: 'swarm', name: 'Member', executor, dutyPreview: '', workId: 'work', taskId: 'task', taskRevision: 2, state: 'running', memoryPath: '', roundCount: 2, instance: { id: 'instance', taskId: 'task', conversationId: 'worker', branchId: 'branch', nativeSessionId: executor === 'native' ? 'native-original' : null, state: 'assigned' } }] }
}
function detail(executor = 'codex') { return { task: { id: 'task', revision: 2, executor, projectId: 'project', ...(executor === 'native' ? { nativeSession: { id: 'native-original', conversationId: 'worker' } } : {}) }, attempts: [{ id: 'run', revision: 2, sessionId: 'original', state: 'running' }] } }
const props = { onMain: vi.fn(), onSession: vi.fn(), onChanged: vi.fn() }
function view(data: SwarmSnapshot) { return <SwarmMemberChat data={data} member={swarmMembers(data)[0]} {...props} /> }
beforeEach(() => { localStorage.clear(); state.failed = false; state.sessions = [{ name: 'original', agent: 'codex', dormant: false, projectKey: 'project' }]; state.api.mockReset().mockResolvedValue({ data: detail() }); vi.clearAllMocks() })
afterEach(cleanup)
it.each(['codex', 'claude', 'opencode', 'native'])('embeds the original %s conversation after exact identity verification', async executor => {
  state.sessions[0].agent = executor; state.api.mockResolvedValue({ data: detail(executor) })
  render(view(snapshot(executor)))
  expect(await screen.findByText(executor === 'native' ? 'native:native-original:task' : executor + ':original')).toBeTruthy()
  expect(state.api).toHaveBeenCalledWith('GET', '/agent/tasks/task', undefined, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})
it.each(['project', 'revision', 'run', 'closure', 'native identity', 'instance Main', 'live executor', 'live missing'])('rejects %s mismatches without creating or falling back to Main', async kind => {
  const data = snapshot(kind === 'native identity' ? 'native' : 'codex'), result: any = detail(data.work[0].executor)
  if (kind === 'project') result.task.projectId = 'foreign'
  if (kind === 'revision') result.attempts[0].revision = 1
  if (kind === 'run') result.attempts[0].id = 'previous'
  if (kind === 'closure') result.sessionClosure = { state: 'unknown' }
  if (kind === 'native identity') result.task.nativeSession.conversationId = 'foreign'
  if (kind === 'instance Main') data.members![0].instance!.conversationId = 'main'
  if (kind === 'live executor') state.sessions[0].agent = 'claude'
  if (kind === 'live missing') state.sessions = []
  state.api.mockResolvedValue({ data: result }); render(view(data))
  expect(await screen.findByText('swarm.member.sessionUnavailable')).toBeTruthy()
  expect(screen.queryByText('codex:original')).toBeNull(); expect(screen.queryByText(/^native:/)).toBeNull()
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})
it('discards a deferred old-run response when the member advances, and immediately drops a removed live session', async () => {
  let resolve!: (value: unknown) => void
  state.api.mockReturnValueOnce(new Promise(done => { resolve = done }))
  const data = snapshot(), mounted = render(view(data))
  const next = structuredClone(data); next.work[0].revision = 3; next.work[0].attempt!.runId = 'next'; next.members![0].taskRevision = 3
  state.api.mockResolvedValue({ data: { ...detail(), task: { ...detail().task, revision: 3 }, attempts: [{ ...detail().attempts[0], revision: 3, id: 'next' }] } })
  mounted.rerender(view(next)); await screen.findByText('codex:original')
  await act(async () => resolve({ data: detail() }))
  expect(screen.getByText('codex:original')).toBeTruthy()
  state.sessions = []; mounted.rerender(view(next))
  expect(screen.queryByText('codex:original')).toBeNull()
  expect(screen.getByText('swarm.member.sessionUnavailable')).toBeTruthy()
})
it('steers the original member and preserves an uncertain command key through remount', async () => {
  const data = snapshot(), first = render(view(data))
  await screen.findByText('codex:original')
  state.api.mockRejectedValueOnce(new Error('unknown'))
  fireEvent.click(screen.getByText('codex:original'))
  await waitFor(() => expect(state.api.mock.calls).toHaveLength(2))
  const request = state.api.mock.calls[1]
  expect(request).toEqual(['POST', '/agent/swarms/swarm/messages', expect.objectContaining({ workId: 'work', taskRevision: 2, text: 'Continue', commandKey: expect.any(String) })])
  first.unmount(); state.api.mockResolvedValue({ data: detail() })
  render(view(data)); await screen.findByText('codex:original')
  fireEvent.click(screen.getByText('codex:original'))
  await waitFor(() => expect(state.api.mock.calls).toHaveLength(4))
  expect(state.api.mock.calls[3]).toEqual(request)
})

it('reuses a registered legacy CLI member without allocating a replacement instance', async () => {
  const data = snapshot(); data.members![0].instance = null
  state.api.mockResolvedValue({ data: { ...detail(), task: { ...detail().task, projectId: null, origin_conversation_id: 'main' } } })
  render(view(data)); expect(await screen.findByText('codex:original')).toBeTruthy()
  fireEvent.click(screen.getByText('codex:original'))
  await waitFor(() => expect(state.api.mock.calls).toHaveLength(2))
  expect(state.api.mock.calls[1]).toEqual(['POST', '/agent/swarms/swarm/messages', expect.objectContaining({ workId: 'work', taskRevision: 2 })])
})
it.each(['missing home', 'other home', 'other Main'])('rejects legacy CLI with %s', async kind => {
  const data = snapshot(); data.members![0].instance = null
  state.sessions[0].projectKey = kind === 'missing home' ? '' : kind === 'other home' ? 'foreign' : 'project'
  state.api.mockResolvedValue({ data: { ...detail(), task: { ...detail().task, projectId: null, origin_conversation_id: kind === 'other Main' ? 'foreign' : 'main' } } })
  render(view(data)); expect(await screen.findByText('swarm.member.sessionUnavailable')).toBeTruthy()
  expect(screen.queryByText('codex:original')).toBeNull()
})
it('migrates the original uncertain legacy command once and permits a later intentional same-text message', async () => {
  const data=snapshot();data.members![0].instance=null
  localStorage.setItem('roami.swarm.draft:/agent/swarms/swarm', JSON.stringify({scope:'work',draft:'Continue',pending:{key:'original-command-key',body:{text:'Continue',workId:'work',taskRevision:1}}}))
  const first=render(view(data));await screen.findByText('codex:original');fireEvent.click(screen.getByText('codex:original'))
  await waitFor(()=>expect(state.api.mock.calls).toHaveLength(2));expect(state.api.mock.calls[1][2]).toMatchObject({commandKey:'original-command-key',taskRevision:1})
  first.unmount();render(view(data));await screen.findByText('codex:original');fireEvent.click(screen.getByText('codex:original'))
  await waitFor(()=>expect(state.api.mock.calls).toHaveLength(4));expect(state.api.mock.calls[3][2].commandKey).not.toBe('original-command-key');expect(state.api.mock.calls[3][2].taskRevision).toBe(2)
})
