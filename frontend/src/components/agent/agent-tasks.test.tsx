// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentTasks from './AgentTasks'
import { api } from '../../api'

vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) => key + (params ? ' ' + Object.values(params).join(' ') : ''), locale: 'en-US' }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => '/n/selected/api' + path }))
vi.mock('antd', () => ({
  Button: ({ children, loading: _loading, danger: _danger, ...props }: any) => <button {...props}>{children}</button>,
  Input: { TextArea: ({ autoSize: _auto, ...props }: any) => <textarea {...props} /> },
  Spin: () => <span role="progressbar" />,
}))
afterEach(() => { cleanup(); vi.resetAllMocks() })

const task = (id: string, parent?: string, revision = 1) => ({ id, parent_task_id: parent, revision, state: 'succeeded', intent_json: JSON.stringify({ goal: 'Goal ' + id }) })
const detail = (id: string, children: any[] = [], revision = 1) => ({ task: task(id, undefined, revision), attempts: [{ id: 'attempt-' + id, revision, state: 'succeeded', result: { summary: 'Result ' + id } }], children, attemptsTruncated: false, childrenTruncated: false })
const controls = (resources: any[] = []) => ({ resources, actions: [], actionsTruncated: false, resourcesTruncated: false })
const artifact = (id: string) => ({ id, name: id + '.png', mimeType: 'image/png', sizeBytes: 1024 })

it.each([
  ['WORKSPACE_STALE', 'workspace'], ['MODEL_HTTP_401', 'authentication'],
  ['UNKNOWN_PROJECT', 'workspace'],
  ['EXECUTION_DIRECTORY_UNAVAILABLE', 'directory'], ['WORKSPACE_BUSY', 'workspaceBusy'],
  ['EXECUTION_DEADLINE_OR_INTERRUPTION', 'deadline'], ['NATIVE_WORKSPACE_RELEASE_UNKNOWN', 'unknown'],
].flatMap(([code, reason]) => [true, false].map(compact => [code, reason, compact] as const)))('explains %s in the task list and detail while retaining diagnostic evidence', async (code, reason, compact) => {
  const failed = { ...task('one'), state: 'failed', latestAttempt: { state: 'failed', summary: code } }
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [failed] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: { ...detail('one'), task: failed, attempts: [{ id: 'attempt-one', revision: 1, state: 'failed', result: { summary: code } }] } }
  })
  render(<AgentTasks compact={compact} cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByText('agent.task.failure.' + reason)
  expect(screen.queryByText(code)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Goal one/ }))
  await screen.findByText('agent.task.failure.' + reason)
  await screen.findByText(code)
  expect(screen.getByRole('button', { name: 'agent.task.continue' })).toBeTruthy()
})

it('shows main task data when an auxiliary request fails and keeps downloads on the selected node', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) throw new Error('offline')
    if (path.startsWith('/agent/artifacts')) return { data: [artifact('proof')] }
    return { data: detail('one') }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  await screen.findByText('Result one')
  await screen.findByText('agent.task.controlUnavailable')
  expect(screen.getByRole('link', { name: 'agent.task.download' }).getAttribute('href')).toBe('/n/selected/api/agent/artifacts/proof/content')
  expect(screen.queryByText('agent.task.noControl')).toBeNull()
})

it('ignores an old task artifact response after opening a child, even if transport ignores abort', async () => {
  let finishOld!: (value: any) => void
  const old = new Promise((resolve) => { finishOld = resolve })
  let signal: AbortSignal | undefined
  vi.mocked(api).mockImplementation(async (_method, path, _body, options) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path === '/agent/artifacts?taskId=one') { signal = options?.signal; return old }
    if (path.startsWith('/agent/artifacts')) return { data: [artifact('current')] }
    return { data: path.endsWith('/one') ? detail('one', [task('two', 'one')]) : detail('two') }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  fireEvent.click(await screen.findByRole('button', { name: /Goal two/ }))
  await screen.findByText('current.png')
  expect(signal?.aborted).toBe(true)
  await act(async () => { finishOld({ data: [artifact('previous')] }); await old })
  expect(screen.queryByText('previous.png')).toBeNull()
  expect(screen.getByText('current.png')).toBeTruthy()
})

it('waits for server-confirmed handoff and invalidates old readiness immediately when returning control', async () => {
  const resource = { id: 'resource', kind: 'browser', state: 'paused', controlReleased: true, canPause: false, canResume: false, takeoverReady: false, browserId: 'browser-instance', targetId: 'exact-tab' }
  let ready = false, resumed = false, finish!: (value: any) => void
  const pending = new Promise((resolve) => { finish = resolve })
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (method === 'POST') { resumed = true; return { data: { ...resource, state: 'idle', takeoverReady: false } } }
    if (path.endsWith('/resources')) return resumed ? pending : { data: controls([{ ...resource, canResume: ready, takeoverReady: ready }]) }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: detail('one') }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  await screen.findByText('agent.task.waitForStop')
  expect(screen.queryByRole('link', { name: 'agent.task.openBrowser' })).toBeNull()
  ready = true
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  const link = await screen.findByRole('link', { name: 'agent.task.openBrowser' })
  expect(link.getAttribute('href')).toBe('#/browser/task/browser-instance/exact-tab')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.returnControl' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/resources/resource/resume', {}))
  await waitFor(() => expect(screen.queryByText('agent.task.controlReady')).toBeNull())
  expect(screen.queryByRole('link', { name: 'agent.task.openBrowser' })).toBeNull()
  await act(async () => { finish({ data: controls([{ ...resource, state: 'idle', canResume: false, takeoverReady: false }]) }); await pending })
  await screen.findByText('agent.task.controlIdle')
})

it('retries an uncertain steering response with the original request key and revision', async () => {
  const requests: any[] = []
  let revision = 1
  vi.mocked(api).mockImplementation(async (method, path, body) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (method === 'POST') {
      requests.push(body); revision = 2
      if (requests.length === 1) throw new Error('lost response')
      return { data: { operationId: 'same-operation', state: 'applied', revision: 2 } }
    }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: detail('one', [], revision) }
  })
  const changed = vi.fn()
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={changed} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  const input = await screen.findByLabelText('agent.task.additionalRequirements')
  fireEvent.change(input, { target: { value: 'Keep the current workspace' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.continue' }))
  await screen.findByRole('alert')
  await screen.findByText('agent.task.revision 2')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.continue' }))
  await waitFor(() => expect(requests).toHaveLength(2))
  expect(requests[0]).toEqual(requests[1])
  expect(requests[1].revision).toBe(1)
  await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe(''))
  expect(changed).toHaveBeenCalledTimes(1)
})

it('binds acceptance to the displayed revision and execution attempt', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') return { data: {} }
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    const result = detail('one', [], 2)
    result.task.state = 'waiting_user'
    return { data: result }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'agent.task.accept' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/tasks/one/verify', { accepted: true, revision: 2, runId: 'attempt-one' }))
})

it('groups attention before active and ended tasks without treating unknown as success', async () => {
  vi.mocked(api).mockResolvedValue({ data: [{ ...task('done'), updated_ms: 1 }, { ...task('active'), state: 'running', updated_ms: 2 }, { ...task('waiting'), state: 'waiting_user', updated_ms: 3 }, { ...task('unknown'), state: 'future-state', updated_ms: 4 }] })
  const page = render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByRole('button', { name: /Goal waiting/ })
  const groups = page.container.querySelectorAll('.agent-task-list-group')
  expect(groups[0].textContent).toContain('agent.workspace.taskGroup.attention')
  expect(groups[0].textContent).toContain('agent.state.unknown')
  expect(groups[0].textContent).not.toContain('agent.state.succeeded')
  expect(groups[1].textContent).toContain('agent.workspace.taskGroup.active')
  expect(groups[2].textContent).toContain('agent.workspace.taskGroup.recent')
})

it('keeps compact task cards truthful and selects the exact task without a modal', async () => {
 vi.mocked(api).mockResolvedValue({ data: [{ ...task('waiting'), state: 'waiting_user' }, { ...task('unknown'), state: 'future-state' }] })
 const selected = vi.fn()
 const page = render(<AgentTasks compact cid="conversation" selectedTask="" onSelectTask={selected} onSession={vi.fn()} onChanged={vi.fn()} />)
 const waiting = await screen.findByRole('button', { name: /Goal waiting/ })
 expect(page.container.querySelectorAll('.agent-task-card')).toHaveLength(2)
 expect(screen.getByText('agent.state.waiting_user')).toBeTruthy()
 expect(screen.getByText('agent.state.unknown')).toBeTruthy()
 expect(screen.queryByText('agent.state.succeeded')).toBeNull()
 fireEvent.click(waiting)
 expect(selected).toHaveBeenCalledWith('waiting')
 expect(screen.queryByRole('dialog')).toBeNull()
})

it('shows a chronological compact list with reported summaries and unknown timestamps', async () => {
 const now = Date.now()
 vi.mocked(api).mockResolvedValue({ data: [{ ...task('older'), updated_ms: now - 1000 }, { ...task('newer'), state: 'failed', updated_ms: now, latestAttempt: { state: 'succeeded', summary: 'Actual executor report' } }, { ...task('undated'), updated_ms: 0 }] })
 const page = render(<AgentTasks compact cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
 await screen.findByText('Actual executor report')
 const rows = page.container.querySelectorAll('.agent-task-card')
 expect(rows[0].textContent).toContain('Goal newer')
 expect(rows[0].getAttribute('data-state')).toBe('failed')
 expect(rows[0].textContent).toContain('agent.state.failed')
 expect(rows[2].querySelector('time')).toBeNull()
 expect(screen.getByText('agent.workspace.timeUnknown')).toBeTruthy()
 expect(page.container.querySelector('.agent-task-list-group')).toBeNull()
})

it('opens retained execution records after completion instead of a dead tmux session', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    const value: any = detail('one')
    value.task.latestAttempt = { sessionId: 'expired-session', state: 'succeeded' }
    value.attempts[0].finishedMs = 1000
    return { data: value }
  })
  const session = vi.fn()
  render(<AgentTasks cid="conversation" onSession={session} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'agent.task.viewRecord' }))
  expect(screen.queryByRole('button', { name: 'agent.openSession' })).toBeNull()
  expect(session).not.toHaveBeenCalled()
  expect(screen.getByText('agent.task.archivedRecord')).toBeTruthy()
})

it('keeps a live task linked to its exact working session', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    const value: any = detail('one')
    value.task.state = 'running'
    value.task.latestAttempt = { sessionId: 'live-session', state: 'running' }
    return { data: value }
  })
  const session = vi.fn()
  render(<AgentTasks cid="conversation" onSession={session} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'agent.openSession' }))
  expect(session).toHaveBeenCalledWith('live-session')
})

it('shows a backfilled report immediately with a retained download and text preview', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: { ...detail('one'), delivery: { artifacts: [{ id: 'report', name: 'review.md', mimeType: 'text/markdown', sizeBytes: 64, metadata: { sourcePath: '/work/review.md' } }], unavailable: [] } } }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  await screen.findByText('review.md')
  expect(screen.getByRole('button', { name: 'agent.task.previewNamed review.md' })).toBeTruthy()
  expect(screen.getByRole('link', { name: 'agent.task.download' }).getAttribute('href')).toBe('/n/selected/api/agent/artifacts/report/content')
})

it('renders historical result metadata with unsupported summary types without crashing', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    const value: any = detail('one')
    value.attempts[0].result = { summary: { legacy: true }, stderr: 42 }
    return { data: value }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  await screen.findByText('agent.task.result')
  expect(screen.queryByText('[object Object]')).toBeNull()
})
