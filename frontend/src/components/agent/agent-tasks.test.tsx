// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentTasks from './AgentTasks'
import NativeSession from './NativeSession'
import NativeSessionArtifacts from './NativeSessionArtifacts'
import NativeProjectSessions from './NativeProjectSessions'
import { clearAgentDataCache } from './agent-data-cache'
import { api } from '../../api'

vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) => key + (params ? ' ' + Object.values(params).join(' ') : ''), locale: 'en-US' }) }))
vi.mock('../cluster/node-url', () => ({ currentNodeId: () => 'selected', nodeApi: (path: string) => '/n/selected/api' + path }))
vi.mock('antd', () => ({
  Dropdown: ({ children }: any) => <>{children}</>,
  App: { useApp: () => ({ message: { error: vi.fn() } }) },
  Button: ({ children, loading: _loading, danger: _danger, ...props }: any) => <button {...props}>{children}</button>,
  Input: { TextArea: ({ autoSize: _auto, onPressEnter: _enter, ...props }: any) => <textarea {...props} /> },
  Spin: () => <span role="progressbar" />,
  Modal: ({ open, title, children, okText, cancelText, onOk, onCancel }: any) => open ? <div role="dialog">{title}{children}<button onClick={onOk}>{okText}</button><button onClick={onCancel}>{cancelText || 'common.cancel'}</button></div> : null,
  Segmented: ({ value, options, onChange }: any) => <div role="tablist">{options.map((item: any) => <button type="button" role="tab" key={item.value} aria-selected={value === item.value} onClick={() => onChange(item.value)}>{item.label}</button>)}</div>,
  Select: ({ value, options, onChange, ...props }: any) => <select {...props} value={value} onChange={e => onChange(e.target.value)}>{options.map((item: any) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>,
}))
afterEach(() => { clearAgentDataCache(); cleanup(); localStorage.clear(); vi.useRealTimers(); vi.resetAllMocks() })

const task = (id: string, parent?: string, revision = 1) => ({ id, parent_task_id: parent, revision, state: 'succeeded', intent_json: JSON.stringify({ goal: 'Goal ' + id }) })
const detail = (id: string, children: any[] = [], revision = 1) => ({ task: task(id, undefined, revision), attempts: [{ id: 'attempt-' + id, revision, state: 'succeeded', result: { summary: 'Result ' + id } }], children, attemptsTruncated: false, childrenTruncated: false })
const controls = (resources: any[] = []) => ({ resources, actions: [], actionsTruncated: false, resourcesTruncated: false })
const artifact = (id: string) => ({ id, name: id + '.png', mimeType: 'image/png', sizeBytes: 1024 })

it.each([
  ['BROWSER_DRIVER_UNAVAILABLE', 'browser'], ['TOOL_ARGUMENT_REPAIR_STALLED', 'toolProgress'],
  ['WORKSPACE_STALE', 'workspace'], ['MODEL_HTTP_401', 'authentication'],
  ['UNKNOWN_PROJECT', 'workspace'],
  ['EXECUTION_DIRECTORY_UNAVAILABLE', 'directory'], ['WORKSPACE_BUSY', 'workspaceBusy'],
  ['EXECUTION_DEADLINE_OR_INTERRUPTION', 'deadline'], ['NATIVE_WORKSPACE_RELEASE_UNKNOWN', 'unknown'],
].flatMap(([code, reason]) => [true, false].map(compact => [code, reason, compact] as const)))('keeps %s diagnostics in detail and a concise status in the list', async (code, reason, compact) => {
  const failed = { ...task('one'), state: 'failed', latestAttempt: { state: 'failed', summary: code } }
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [failed] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: { ...detail('one'), task: failed, attempts: [{ id: 'attempt-one', revision: 1, state: 'failed', result: { summary: code } }] } }
  })
  render(<AgentTasks compact={compact} cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByText('agent.state.failed')
  expect(screen.queryByText('agent.task.failure.' + reason)).toBeNull()
  expect(screen.queryByText(code)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Goal one/ }))
  await screen.findByText('agent.task.failure.' + reason)
  expect(screen.queryByText(code)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.viewRecord' }))
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
  expect(signal).toBeDefined()
  await act(async () => { finishOld({ data: [artifact('previous')] }); await old })
  expect(screen.queryByText('previous.png')).toBeNull()
  expect(screen.getByText('current.png')).toBeTruthy()
})

it('waits for server-confirmed handoff and invalidates old readiness immediately when returning control', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
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
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.checkControl' }))
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

it.each([false, true])('sorts by time across states and filters without extra requests (compact=%s)', async compact => {
  vi.mocked(api).mockResolvedValue({ data: [
    { ...task('failed'), state: 'failed', updated_ms: 2 },
    { ...task('active'), state: 'running', updated_ms: 7 },
    { ...task('waiting'), state: 'waiting_user', updated_ms: 3 },
    { ...task('unknown'), state: 'future-state', updated_ms: 8 },
    { ...task('done'), updated_ms: 9 },
    { ...task('cancelled'), state: 'cancelled', updated_ms: 4 },
    { ...task('interrupted'), state: 'interrupted', updated_ms: 1 },
    { ...task('queued'), state: 'queued', created_ms: 6 },
  ] })
  const page = render(<AgentTasks compact={compact} cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByRole('button', { name: /Goal done/ })
  const titles = () => [...page.container.querySelectorAll('.agent-task-link b')].map(el => el.textContent)
  expect(titles()).toEqual(['Goal done', 'Goal unknown', 'Goal active', 'Goal queued', 'Goal cancelled', 'Goal waiting', 'Goal failed', 'Goal interrupted'])
  expect(page.container.querySelector('.agent-task-list-group')).toBeNull()
  const reads = vi.mocked(api).mock.calls.length
  const choose = (value: string) => fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.' + value }))
  choose('attention')
  expect(titles()).toEqual(['Goal unknown', 'Goal waiting', 'Goal failed', 'Goal interrupted'])
  expect(screen.getByText('agent.state.unknown')).toBeTruthy()
  expect(screen.queryByText('agent.state.succeeded')).toBeNull()
  choose('active')
  expect(titles()).toEqual(['Goal active', 'Goal queued'])
  choose('ended')
  expect(titles()).toEqual(['Goal done', 'Goal cancelled', 'Goal failed', 'Goal interrupted'])
  choose('all')
  expect(titles()[0]).toBe('Goal done')
  expect(screen.getByRole('button', { name: 'agent.task.filter.all' }).getAttribute('aria-pressed')).toBe('true')
  expect(api).toHaveBeenCalledTimes(reads)
})

it('keeps the filter when returning from task details', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [{ ...task('one'), state: 'failed' }, task('done')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: detail('one') }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByRole('button', { name: /Goal one/ })
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.attention' }))
  fireEvent.click(screen.getByRole('button', { name: /Goal one/ }))
  await screen.findByText('Result one')
  fireEvent.click(screen.getByRole('button', { name: 'agent.tasks' }))
  await screen.findByRole('button', { name: /Goal one/ })
  expect(screen.getByRole('button', { name: 'agent.task.filter.attention' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByRole('button', { name: /Goal done/ })).toBeNull()
})

it('can clear an empty filter without losing tasks', async () => {
  vi.mocked(api).mockResolvedValue({ data: [task('one')] })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByRole('button', { name: /Goal one/ })
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.active' }))
  expect(screen.getByRole('status').textContent).toBe('agent.task.filter.empty')
  expect(screen.queryByText('agent.noTasks')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.all' }))
  expect(screen.getByRole('button', { name: /Goal one/ })).toBeTruthy()
  expect(screen.queryByRole('status')).toBeNull()
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

it('shows a chronological compact list with essential status and unknown timestamps', async () => {
 const now = Date.now()
 vi.mocked(api).mockResolvedValue({ data: [{ ...task('older'), updated_ms: now - 1000 }, { ...task('newer'), state: 'failed', updated_ms: now, latestAttempt: { state: 'succeeded', summary: 'Actual executor report' } }, { ...task('undated'), updated_ms: 0 }] })
 const page = render(<AgentTasks compact cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
 await screen.findByText('Goal newer')
 expect(screen.queryByText('Actual executor report')).toBeNull()
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

it.each(['succeeded', 'failed'])('renders historical %s results with unsupported summary types without crashing', async state => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [task('one')] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    const value: any = detail('one')
    value.task.state = state
    value.attempts[0].result = { summary: { legacy: true }, stderr: 42 }
    return { data: value }
  })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'agent.task.viewRecord' }))
  await screen.findByText('agent.task.archivedRecord')
  expect(screen.queryByText('[object Object]')).toBeNull()
})

it('shows a cached task result on reopening but waits for fresh detail before continuing', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.endsWith('/resources') ? controls() : path.startsWith('/agent/artifacts') ? [] : detail('one') }))
  const first = render(<AgentTasks cid="conversation" selectedTask="one" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByText('Result one')
  first.unmount()
  let finish!: (value: any) => void
  const pending = new Promise(resolve => { finish = resolve })
  vi.mocked(api).mockImplementation(async (_method, path) => path.endsWith('/resources') ? { data: controls() } : path.startsWith('/agent/artifacts') ? { data: [] } : pending)
  render(<AgentTasks cid="conversation" selectedTask="one" onSession={vi.fn()} onChanged={vi.fn()} />)
  expect(screen.getByText('Result one')).toBeTruthy()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Continue with the new requirements' } })
  expect((screen.getByRole('button', { name: 'agent.task.continue' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.continue' }))
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'POST')).toBe(false)
  await act(async () => { finish({ data: detail('one', [], 2) }); await pending })
  await waitFor(() => expect((screen.getByRole('button', { name: 'agent.task.continue' }) as HTMLButtonElement).disabled).toBe(false))
})


it('keeps failure authoritative when the executor claims success and reports a PR', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    const value = detail('one')
    value.task.state = 'failed'
    value.attempts[0].state = 'failed'
    value.attempts[0].result.summary = 'Everything succeeded! https://github.com/ybz21/Roami/pull/336'
    return { data: value }
  })
  render(<AgentTasks cid="conversation" selectedTask="one" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByText('agent.task.incomplete')
  expect(screen.getByText('agent.state.failed')).toBeTruthy()
  expect(screen.queryByText(/Everything succeeded!/)).toBeNull()
  expect(screen.getByText('agent.task.reportedLinks')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'agent.task.openPullRequest 336' }).getAttribute('href')).toBe('https://github.com/ybz21/Roami/pull/336')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.viewRecord' }))
  await screen.findByText(/Everything succeeded!/)
})

it('shows the verifier reason before the original executor report', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    const value = detail('one')
    value.task.state = 'failed'
    return { data: { ...value, outcome: { state: 'failed', errorCode: 'WEB_RETRIEVAL_EVIDENCE_MISSING' } } }
  })
  render(<AgentTasks cid="conversation" selectedTask="one" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByText('agent.task.failure.retrieval')
  expect(screen.queryByText('Result one')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.viewRecord' }))
  await screen.findByText('Result one')
})

it('separates the name, expandable task details and collapsed current agent instructions', async () => {
  const original = 'Original task details.\n' + 'Retain this full requirement. '.repeat(20)
  const sent = 'Actual current instructions, including the applied continuation.'
  const scroll = vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) { return this.classList.contains('agent-task-description') ? 300 : 0 })
  const height = vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) { return this.classList.contains('agent-task-description') ? 60 : 0 })
  try {
    vi.mocked(api).mockImplementation(async (_method, path) => {
      if (path.endsWith('/resources')) return { data: controls() }
      if (path.startsWith('/agent/artifacts')) return { data: [] }
      const value = detail('one')
      value.task.intent_json = JSON.stringify({ initialIntent: { title: 'Short task name', goal: original }, goal: sent })
      return { data: value }
    })
    const page = render(<AgentTasks cid="conversation" selectedTask="one" onSession={vi.fn()} onChanged={vi.fn()} />)
    await screen.findByRole('heading', { name: 'Short task name' })
    const expand = await screen.findByRole('button', { name: 'agent.task.expandContent' })
    expect(expand.getAttribute('aria-expanded')).toBe('false')
    expect(page.container.querySelector('.agent-task-description')?.textContent).toBe(original)
    const instructions = page.container.querySelector('details.agent-task-requirements') as HTMLDetailsElement
    expect(instructions.open).toBe(false)
    expect(instructions.querySelector('p')?.textContent).toBe(sent)
    fireEvent.click(expand)
    expect(screen.getByRole('button', { name: 'agent.task.collapseContent' }).getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'agent.task.collapseContent' }))
    expect(screen.getByRole('button', { name: 'agent.task.expandContent' }).getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(screen.getByText('agent.task.instructions'))
    expect(instructions.open).toBe(true)
  } finally { scroll.mockRestore(); height.mockRestore() }
})


it('opens the native process and conversation on demand and routes an answer through versioned task steering', async () => {
  const reads: string[] = [], writes: any[] = []
  vi.mocked(api).mockImplementation(async (method, path, body) => {
    if (method === 'POST') { writes.push({ path, body }); return { data: {} } }
    reads.push(path)
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    if (path.endsWith('/activities')) return { data: [{ id: 'tool:read', kind: 'tool', taskId: 'one', name: 'memory_search', anchorMessageId: 'm', state: 'succeeded', startedMs: 1, updatedMs: 2 }] }
    if (path.includes('/conversation?')) return { data: { messages: [
      { id: 'request', role: 'user', seq: 1, content: { text: 'Find the source' } },
      { id: 'question', role: 'assistant', seq: 2, status: 'completed', content: { question: { prompt: 'Which source?', options: [{ label: 'Official source' }] } } },
    ] } }
    const value: any = detail('one', [], 3)
    value.task.state = 'running'
    value.task.state = 'waiting_user'
    value.attempts[0] = { id: 'run-latest', revision: 3, state: 'waiting_user', finishedMs: 1000, hasConversation: true }
    return { data: value }
  })
  render(<AgentTasks cid="conversation" selectedTask="one" onSession={vi.fn()} onChanged={vi.fn()} />)
  const input = await screen.findByLabelText('agent.task.additionalRequirements')
  fireEvent.change(input, { target: { value: 'Keep this unsent draft' } })
  expect(reads.some(path => path.includes('/activities') || path.includes('/conversation?'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.viewRecord' }))
  await screen.findByText('agent.activity.memory memory_search')
  fireEvent.click(screen.getByRole('tab', { name: 'agent.task.conversation' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Official source' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0].path).toBe('/agent/tasks/one/steer')
  expect(writes[0].body).toEqual({ revision: 3, requestKey: expect.any(String), text: 'Official source' })
  await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe('Keep this unsent draft'))
  expect(reads).toContain('/agent/tasks/one/conversation?runId=run-latest')
  expect(writes.some(entry => entry.path.includes('/conversations/'))).toBe(false)
})


it('keeps old native conversations read-only and makes no periodic requests after completion', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.endsWith('/resources')) return { data: controls([{ id: 'unreleased', kind: 'browser', state: 'quarantined', controlReleased: false }]) }
    if (path.startsWith('/agent/artifacts') || path.endsWith('/activities')) return { data: [] }
    if (path.includes('/conversation?')) return { data: { messages: [{ id: 'q', role: 'assistant', seq: 1, content: { question: { prompt: 'Old question', options: [{ label: 'Old answer' }] } } }] } }
    const value: any = detail('one')
    value.attempts = [{ id: 'latest', attemptNo: 2, revision: 2, state: 'succeeded', finishedMs: 2000, hasConversation: true }, { id: 'old', attemptNo: 1, revision: 1, state: 'cancelled', finishedMs: 1000, hasConversation: true }]
    return { data: value }
  })
  render(<AgentTasks cid="conversation" selectedTask="one" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByRole('button', { name: 'agent.task.viewRecord' })
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.viewRecord' }))
  fireEvent.click(screen.getByRole('tab', { name: 'agent.task.conversation' }))
  await screen.findByRole('combobox', { name: 'agent.task.execution' })
  fireEvent.change(screen.getByRole('combobox', { name: 'agent.task.execution' }), { target: { value: 'old' } })
  const answer = await screen.findByRole('button', { name: 'Old answer' }) as HTMLButtonElement
  expect(answer.disabled).toBe(true)
  expect(vi.mocked(api).mock.calls.some(call => call[1] === '/agent/tasks/one/conversation?runId=old')).toBe(true)
  await act(async () => {})
  const calls = vi.mocked(api).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(api).toHaveBeenCalledTimes(calls)
})


it('retains an unsent intervention draft after returning from another page and clears it only after accepted submission', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') return { data: {} }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: detail('one') }
  })
  const props = { cid: 'conversation', selectedTask: 'one', onSession: vi.fn(), onChanged: vi.fn() }
  const first = render(<AgentTasks {...props} />)
  fireEvent.change(await screen.findByLabelText('agent.task.additionalRequirements'), { target: { value: 'Keep this while I inspect the trace' } })
  first.unmount()
  render(<AgentTasks {...props} />)
  const input = await screen.findByLabelText('agent.task.additionalRequirements') as HTMLTextAreaElement
  expect(input.value).toBe('Keep this while I inspect the trace')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.continue' }))
  await waitFor(() => expect(input.value).toBe(''))
  expect(Object.keys(localStorage).filter(key => key.startsWith('roami.agent.task.draft.'))).toEqual([])
})


it('keeps the completed professional session reachable and closes it only after confirmation', async () => {
  let closed = false
  const opened = vi.fn()
  const professional = { ...task('one'), intent_json: JSON.stringify({ goal: 'Goal one', executor: 'codex' }), latestAttempt: { executorKind: 'cli', sessionId: 'original-codex', agentConversationId: 'original-context' } }
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') { closed = true; return { data: { state: 'closed' } } }
    if (path.includes('?conversationId=')) return { data: [professional] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: { ...detail('one'), task: professional, sessionClosure: closed ? { state: 'closed' } : null, attempts: [{ ...detail('one').attempts[0], sessionId: 'original-codex', finishedMs: 1 }] } }
  })
  render(<AgentTasks cid="conversation" onSession={opened} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'agent.openSession' }))
  expect(opened).toHaveBeenCalledWith('original-codex')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.closeSession' }))
  expect(screen.getByRole('dialog')).toBeTruthy()
  expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'POST')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.closeSession' }))
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.completeAndClose' }))
  await screen.findByText('agent.task.sessionClosed')
  expect(api).toHaveBeenCalledWith('POST', '/agent/tasks/one/close-session', { revision: 1, runId: 'attempt-one' })
  expect(screen.queryByRole('button', { name: 'agent.openSession' })).toBeNull()
  expect(screen.getByRole('button', { name: 'agent.task.continue' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByText('Result one')).toBeTruthy()
})

it('keeps filters across remounts and exposes original session and project as separate actions', async () => {
  const openSession = vi.fn()
  const native = { ...task('native'), projectId: 'project-a', nativeSession: { id: 'native-identity', conversationId: 'child' } }
  const professional = { ...task('codex'), latestAttempt: { state: 'succeeded', executorKind: 'cli', sessionId: 'original-codex', agentConversationId: 'provider-context' } }
  vi.mocked(api).mockResolvedValue({ data: [native, professional] })
  const first = render(<AgentTasks cid="conversation" projects={[{ id: 'project-a', name: 'Roami' }]} onSession={openSession} onChanged={vi.fn()} />)
  await screen.findByRole('button', { name: /Goal native/ })
  expect(screen.getByRole('link', { name: 'Roami' }).getAttribute('href')).toBe('#/projects/project-a')
  const buttons = screen.getAllByRole('button', { name: 'agent.task.enterSession' })
  fireEvent.click(buttons[0]); expect(openSession).toHaveBeenCalledWith('original-codex')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.open' }))
  first.unmount()
  render(<AgentTasks cid="conversation" onSession={openSession} onChanged={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'agent.task.filter.open' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getAllByRole('button', { name: 'agent.task.enterSession' })[1])
  expect(location.hash).toContain('/session/')
  expect(decodeURIComponent(location.hash)).toContain('native-identity')
})


it('hides empty native tool replies while retaining real content and the active reply', async () => {
  const messages = [
    { id: 'user', role: 'user', status: 'completed', seq: 1, content: { text: 'Update the presentation' } },
    ...Array.from({ length: 13 }, (_, i) => ({ id: 'tool-' + i, role: 'assistant', status: 'completed', seq: i + 2, content: { text: '', tool_calls: [{ id: 'call-' + i }] } })),
    { id: 'result', role: 'tool', status: 'completed', seq: 15, content: { text: 'Internal tool result' } },
    { id: 'answer', role: 'assistant', status: 'completed', seq: 16, content: { text: 'Working on the presentation' } },
    { id: 'active', role: 'assistant', status: 'streaming', seq: 17, content: { text: '' } },
  ]
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/native-sessions/native-id') return { data: { nativeSessionId: 'native-id', taskId: 'original' } }
    if (path.endsWith('/conversation')) return { data: { messages, before: null } }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: detail('original') }
  })
  const page = render(<NativeSession id="native-id" node={null} projects={[]} onChanged={vi.fn()} />)
  await screen.findByText('Working on the presentation')
  expect(page.container.querySelectorAll('.cc-msg')).toHaveLength(2)
  expect(page.container.querySelectorAll('.agent-typing')).toHaveLength(1)
  expect(screen.queryByText('Internal tool result')).toBeNull()
  expect(screen.getByText('Update the presentation')).toBeTruthy()
})

it('refreshes a fast native continuation without Main events and stops reading after it settles', async () => {
  let phase = 0
  const nativeTask = { ...task('original'), nativeSession: { id: 'native-id', conversationId: 'native-conversation' } }
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') { phase = 1; return { data: { state: 'stopping' } } }
    if (path === '/agent/native-sessions/native-id') return { data: { nativeSessionId: 'native-id', taskId: 'original' } }
    if (path.endsWith('/conversation')) return { data: { messages: [{ id: 'reply-' + phase, role: 'assistant', status: 'completed', seq: phase + 1, content: { text: phase === 2 ? 'Updated answer' : 'Original answer' } }], before: null } }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: { ...detail('original'), task: { ...nativeTask, revision: phase === 2 ? 2 : 1 }, attempts: [{ id: phase === 2 ? 'second' : 'first', revision: phase === 2 ? 2 : 1, state: 'succeeded', finishedMs: phase === 2 ? 200 : 100 }], steering: phase ? { operationId: 'steering', state: phase === 2 ? 'applied' : 'stopping', revision: 1 } : null } }
  })
  render(<NativeSession id="native-id" node="selected" projects={[]} onChanged={vi.fn()} />)
  await screen.findByText('Original answer')
  vi.useFakeTimers()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Add the owner' } })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'agent.task.continue' })); await Promise.resolve() })
  phase = 2
  await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
  expect(screen.getByText('Updated answer')).toBeTruthy()
  expect(vi.mocked(api).mock.calls.some(([method, path, body]: any[]) => method === 'POST' && path === '/agent/tasks/original/steer' && body.text === 'Add the owner' && body.revision === 1)).toBe(true)
  const count = vi.mocked(api).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(6500) })
  expect(vi.mocked(api).mock.calls.length).toBe(count)
})


it('keeps a running professional session visible while its provider context is still being registered', async () => {
  const starting = { ...task('starting'), state: 'running', latestAttempt: { state: 'running', executorKind: 'cli', sessionId: 'original-session', agentConversationId: null } }
  vi.mocked(api).mockResolvedValue({ data: [starting] })
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByRole('button', { name: /Goal starting/ })
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.open' }))
  expect(screen.getByRole('button', { name: /Goal starting/ })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'agent.task.enterSession' })).toBeTruthy()
})

it('loads native execution steps on demand and retains the draft across tabs and failed continuation', async () => {
  let reject = true
  const posts: any[] = []
  vi.mocked(api).mockImplementation(async (method, path, body) => {
    if (method === 'POST') { posts.push(body); if (reject) throw { apiError: { code: 'TASK_REVISION_CHANGED' } }; return { data: {} } }
    if (path === '/agent/native-sessions/native-id') return { data: { nativeSessionId: 'native-id', taskId: 'original' } }
    if (path.endsWith('/conversation')) return { data: { messages: [], before: null } }
    if (path.endsWith('/activities')) return { data: [{ id: 'step', kind: 'tool', name: 'shell', state: 'succeeded', startedMs: 1000, updatedMs: 2000 }] }
    if (path.endsWith('/activities/step')) return { data: { input: { text: 'node build.mjs', truncated: false }, output: { text: 'Build passed', truncated: false } } }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: detail('original') }
  })
  render(<NativeSession id="native-id" node="selected" projects={[]} onChanged={vi.fn()} />)
  await screen.findByText('Goal original')
  expect(vi.mocked(api).mock.calls.some(([, path]) => path.endsWith('/activities'))).toBe(false)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep the draft' } })
  fireEvent.click(screen.getByRole('tab', { name: 'agent.task.sessionTab.process' }))
  await screen.findByText('agent.activity.shell shell')
  fireEvent.click(screen.getByRole('button', { name: /agent.activity.shell/ }))
  await screen.findByText(/node build.mjs/)
  fireEvent.click(screen.getByRole('tab', { name: 'agent.task.sessionTab.artifacts' }))
  await screen.findByText('agent.task.noArtifacts')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep the draft')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.continue' }))
  await screen.findByRole('alert')
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep the draft')
  reject = false
  fireEvent.click(screen.getByRole('tab', { name: 'agent.task.sessionTab.conversation' }))
  await waitFor(() => expect((screen.getByRole('button', { name: 'agent.task.continue' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.continue' }))
  await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(''))
  expect(posts).toHaveLength(2)
  expect(posts[1]).toMatchObject({ text: 'Keep the draft', revision: 1 })
})

it('separates native deliverables by execution and keeps task failure visible during preview', async () => {
  const current = { ...artifact('current'), metadata: { runId: 'attempt-original' } }
  const previous = { ...artifact('previous'), metadata: { runId: 'older' } }
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/native-sessions/native-id') return { data: { nativeSessionId: 'native-id', taskId: 'original' } }
    if (path.endsWith('/conversation')) return { data: { messages: [], before: null } }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [current, previous, { ...artifact('archive'), mimeType: 'application/zip' }] }
    return { data: { ...detail('original'), task: { ...task('original'), state: 'failed' }, delivery: { artifacts: [current], unavailable: [{ sourcePath: '/work/missing.pdf' }] } } }
  })
  render(<NativeSession id="native-id" node="selected" projects={[]} onChanged={vi.fn()} />)
  await screen.findByText('Goal original')
  fireEvent.click(screen.getByRole('tab', { name: 'agent.task.sessionTab.artifacts' }))
  await screen.findByText('agent.task.currentArtifacts')
  expect(screen.getByText('agent.task.previousArtifacts')).toBeTruthy()
  expect(screen.getByText('agent.task.otherArtifacts')).toBeTruthy()
  expect(screen.getAllByText('current.png')).toHaveLength(1)
  expect(screen.getByText('agent.task.artifactStatus agent.state.failed')).toBeTruthy()
  expect(screen.getByText('/work/missing.pdf')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'agent.task.downloadNamed archive.png' }).getAttribute('href')).toBe('/n/selected/api/agent/artifacts/archive/content?dl=1')
  expect(screen.queryByRole('button', { name: 'agent.task.previewNamed archive.png' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.previewNamed current.png' }))
  expect(screen.getByRole('img', { name: 'current.png' }).getAttribute('src')).toBe('/n/selected/api/agent/artifacts/current/content')
  fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})


it('opens a native project row directly without per-row detail requests', () => {
  render(<NativeProjectSessions projectId="project-a" entries={[{ nativeSessionId: 'native-list-entry', title: 'Review the delivery', taskState: 'waiting_user', createdAt: new Date().toISOString() }]} />)
  expect(screen.getByText('agent.state.waiting_user')).toBeTruthy()
  expect(screen.queryByText('agent.task.enterSession')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Review the delivery/ }))
  expect(decodeURIComponent(location.hash)).toContain('/native-list-entry')
  expect(api).not.toHaveBeenCalled()
})


it('does not present an earlier revision as the current delivery while continuation is queued', () => {
  const prior = { ...artifact('prior'), metadata: { runId: 'attempt-original' } }
  const snapshot = { ...detail('original'), task: { ...task('original', undefined, 2), state: 'queued' } }
  render(<NativeSessionArtifacts detail={snapshot as any} artifacts={[prior]} failed={false} retry={vi.fn()} />)
  expect(screen.queryByText('agent.task.currentArtifacts')).toBeNull()
  expect(screen.queryByText('Result original')).toBeNull()
  expect(screen.getByText('agent.task.previousArtifacts')).toBeTruthy()
  expect(screen.getByText('prior.png')).toBeTruthy()
})

it('shows existing reports and downloads while execution remains unconfirmed', async () => {
  const pending = { ...task('pending'), state: 'running', latestAttempt: { state: 'unknown', sessionId: 'work-session', executorKind: 'cli' } }
  const progress = { source: 'provider_transcript', summary: 'A source-bound research report', directory: '/workspace/research', observedMs: 123456 }
  const output = { id: 'report-html', name: 'index.html', mimeType: 'text/html', sizeBytes: 200, metadata: { runId: 'attempt-pending', sourceFile: '/workspace/research/index.html', sourcePath: '/workspace/research/index.html', provisional: true, reportedAliases: ['index.html'] } }
  const session = vi.fn()
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.includes('?conversationId=')) return { data: [pending] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [output] }
    return { data: { ...detail('pending'), task: pending, attempts: [{ id: 'attempt-pending', revision: 1, state: 'unknown', sessionId: 'work-session', result: null, progress }], delivery: { artifacts: [output], unavailable: [] } } }
  })
  render(<AgentTasks cid="conversation" onSession={session} onChanged={vi.fn()} />)
  await screen.findByText('agent.task.executionUnconfirmed')
  expect(screen.queryByText('agent.state.running')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.filter.attention' }))
  fireEvent.click(await screen.findByRole('button', { name: /Goal pending/ }))
  await screen.findByText('A source-bound research report')
  expect(screen.getByText('agent.task.executionUnconfirmedHint')).toBeTruthy()
  expect(screen.getByText('index.html')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'agent.task.download' }).getAttribute('href')).toBe('/n/selected/api/agent/artifacts/report-html/content')
  expect(screen.queryByRole('button', { name: 'agent.task.accept' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.openSession' }))
  expect(session).toHaveBeenCalledWith('work-session')
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.viewRecord' }))
  await screen.findByText('agent.task.reportUnconfirmed')
  expect(screen.getAllByText('A source-bound research report').length).toBe(2)
})

it('accepts closing a running session and shows asynchronous cleanup failures with a retry action', async () => {
  let phase = 'running'
  const professional = { ...task('one'), state: 'running', intent_json: JSON.stringify({ goal: 'Goal one', executor: 'codex' }), latestAttempt: { executorKind: 'cli', sessionId: 'original-codex', agentConversationId: 'original-context' } }
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') { phase = 'closing'; return { data: { state: 'closing' } } }
    if (path.includes('?conversationId=')) return { data: [professional] }
    if (path.endsWith('/resources')) return { data: controls() }
    if (path.startsWith('/agent/artifacts')) return { data: [] }
    return { data: { ...detail('one'), task: { ...professional, state: phase === 'failed' ? 'cancelled' : 'running' }, sessionClosure: phase === 'running' ? null : { state: phase, error_code: phase === 'failed' ? 'WORKTREE_DIRTY' : null }, attempts: [{ ...detail('one').attempts[0], sessionId: 'original-codex' }] } }
  })
  const view = render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'agent.task.closeSession' }))
  fireEvent.click(screen.getByRole('button', { name: 'agent.task.completeAndClose' }))
  await screen.findByText('agent.task.sessionClosing')
  expect(screen.getByRole('button', { name: 'agent.task.closeSession' }).hasAttribute('disabled')).toBe(true)
  view.unmount(); clearAgentDataCache(); phase = 'failed'
  render(<AgentTasks cid="conversation" onSession={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Goal one/ }))
  await screen.findByText('agent.task.cleanupDirty')
  expect(screen.getByRole('button', { name: 'agent.task.closeSession' }).hasAttribute('disabled')).toBe(false)
})
