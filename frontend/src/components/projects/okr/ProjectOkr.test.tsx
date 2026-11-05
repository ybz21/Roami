// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProjectOkr from './ProjectOkr'
import { type Workspace } from './okr-workspace'

vi.mock('./OkrMainChat', () => ({ default: ({ onUpdated }: { onUpdated: () => void }) => <button onClick={onUpdated}>Complete discussion</button> }))
vi.mock('./OkrTrend', () => ({ default: () => <div data-testid="trend" /> }))
vi.mock('./OkrProjectFiles', () => ({ default: ({ dir, bundleRoot }: { dir: string; bundleRoot?: string }) => <div data-testid="project-files" data-bundle-root={bundleRoot}>{dir}</div> }))
vi.mock('../../swarm/useSwarmSnapshot', () => ({ useSwarmSnapshot: () => ({ data: null, error: false, refresh: vi.fn() }) }))
vi.mock('../../swarm/Swarm', () => ({ default: ({ initialSwarm }: { initialSwarm: string }) => <div data-testid="activities">{initialSwarm}</div> }))

function panel(key: string) {
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.' + ({ overview: 'okr', data: 'dashboard' }[key] || key) }))
}

const state = vi.hoisted(() => ({ phone: false, api: vi.fn() }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: state.phone }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string, vars?: object) => key + (vars ? JSON.stringify(vars) : '') }) }))

const initial: Workspace = {
  projectId: 'stable-project', revision: 3, objective: 'Launch', startDate: '2026-11-01', endDate: '2026-11-30',
  metrics: [{ id: 'visits', name: 'Visits', unit: 'people', source: 'manual' }, { id: 'stars', name: 'Stars', unit: '', source: 'github', repo: 'owner/repo', field: 'stars' }],
  keyResults: [{ id: 'kr1', title: 'Reach people', metricId: 'visits', horizon: 'short', target: 100, mode: 'atLeast', dueDate: '2026-11-30' }],
  swarm: 'sw-11111111111111111111111111111111', autoCollect: false, observations: [], reviews: [], updatedAt: '2026-11-03T00:00:00Z',
}
beforeEach(() => {
  localStorage.clear()
  state.phone = false
  state.api.mockReset()
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [{ id: 'sw-11111111111111111111111111111111', name: 'real-team' }] } : { data: initial })
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

it.each([false, true])('restores the project view after leaving the workspace (phone=%s)', async phone => {
  state.phone = phone
  const first = render(<ProjectOkr projectId="stable-project" />)
  await screen.findByRole('button', { name: 'okr.edit' })
  panel('data')
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.files' }))
  await screen.findByTestId('project-files')
  first.unmount()
  render(<ProjectOkr projectId="stable-project" />)
  expect(await screen.findByTestId('project-files')).toBeTruthy()
  expect(screen.getByRole('tab', { name: 'okr.tab.files' }).getAttribute('aria-selected')).toBe('true')
  panel('data')
  expect(screen.getByRole('tab', { name: 'okr.tab.dashboard' }).getAttribute('aria-selected')).toBe('true')
  cleanup()
  render(<ProjectOkr projectId="another-project" />)
  await screen.findByRole('button', { name: 'okr.edit' })
  expect(screen.getByRole('tab', { name: 'okr.tab.okr' }).getAttribute('aria-selected')).toBe('true')
})

it('keeps project navigation available and preserves a configuration draft across files', async () => {
  render(<ProjectOkr projectId="stable-project" projectDir="/project" />)
  fireEvent.click(await screen.findByRole('button', { name: 'okr.edit' }))
  fireEvent.change(screen.getByLabelText('okr.objective'), { target: { value: 'Unfinished goal edit' } })
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.files' }))
  expect(await screen.findByTestId('project-files')).toHaveProperty('textContent', '/project')
  expect(screen.getByTestId('project-files').getAttribute('data-bundle-root')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.okr' }))
  expect((screen.getByLabelText('okr.objective') as HTMLTextAreaElement).value).toBe('Unfinished goal edit')
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})

it('keeps an edited objective across 409, reloads revision and saves only configuration', async () => {
  let conflicted = false
  state.api.mockImplementation(async (method, path, body) => {
    if (path === '/agent/swarms') return { data: [{ id: 'sw-11111111111111111111111111111111', name: 'real-team' }] }
    if (method === 'PUT' && !conflicted) { conflicted = true; throw Object.assign(new Error('OKR_CONFLICT'), { status: 409 }) }
    if (method === 'PUT') return { data: { ...initial, ...body, revision: 9 } }
    return { data: { ...initial, revision: conflicted ? 8 : 3 } }
  })
  render(<ProjectOkr projectId="stable-project" />)
  fireEvent.click(await screen.findByRole('button', { name: 'okr.edit' }))
  fireEvent.change(screen.getByLabelText('okr.objective'), { target: { value: 'My edited objective' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.save' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('okr.conflict'))
  expect((screen.getByLabelText('okr.objective') as HTMLTextAreaElement).value).toBe('My edited objective')
  fireEvent.click(screen.getByRole('button', { name: 'okr.loadLatest' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect((screen.getByLabelText('okr.objective') as HTMLTextAreaElement).value).toBe('My edited objective')
  fireEvent.click(screen.getByRole('button', { name: 'okr.save' }))
  await waitFor(() => expect(state.api.mock.calls.filter(c => c[0] === 'PUT')).toHaveLength(2))
  const body = state.api.mock.calls.filter(c => c[0] === 'PUT')[1][2]
  expect(body).toMatchObject({ revision: 8, objective: 'My edited objective' })
  expect(body).not.toHaveProperty('observations')
  expect(body).not.toHaveProperty('reviews')
})

it('uses a URL-backed phone page without pushing overlay history and returns to the stable project', async () => {
  state.phone = true
  history.replaceState(null, '', '#/projects/stable-project/okr?node=remote')
  const push = vi.spyOn(history, 'pushState')
  render(<ProjectOkr projectId="stable-project" />)
  await screen.findByText('Launch')
  expect(push).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'common.back' }))
  expect(location.hash).toBe('#/projects/stable-project?node=remote')
  push.mockRestore()
})

it('creates a workspace with an arbitrary manual metric and key result at revision zero', async () => {
  state.api.mockImplementation(async (method, path, body) => {
    if (path === '/agent/swarms') return { data: [] }
    if (method === 'PUT') return { data: { ...body, projectId: 'new-project', revision: 1, observations: [], reviews: [], updatedAt: '2026-11-03T01:00:00Z' } }
    return { data: null }
  })
  render(<ProjectOkr projectId="new-project" />)
  fireEvent.change(await screen.findByLabelText('okr.objective'), { target: { value: 'Meet the community' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.addMetric' }))
  fireEvent.change(screen.getByLabelText('okr.metricName'), { target: { value: 'Event attendees' } })
  fireEvent.change(screen.getByLabelText('okr.unit'), { target: { value: 'people' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.addKr' }))
  fireEvent.change(screen.getByLabelText('okr.krTitle'), { target: { value: 'Welcome attendees' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.save' }))
  await screen.findByRole('button', { name: 'okr.edit' })
  const body = state.api.mock.calls.find(call => call[0] === 'PUT')![2]
  expect(body).toMatchObject({ revision: 0, objective: 'Meet the community', metrics: [{ name: 'Event attendees', unit: 'people', source: 'manual' }], keyResults: [{ title: 'Welcome attendees', metricId: body.metrics[0].id, target: 1 }] })
  expect(body).not.toHaveProperty('observations')
  expect(state.api.mock.calls.some(call => call[1].endsWith('/collect'))).toBe(false)
})

it('updates visible snapshots every 30 seconds without loops, backs off errors and aborts hidden or unmounted reads', async () => {
  vi.useFakeTimers()
  let hidden = false
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  let next = initial, fail = false, hold = false
  let finish!: (response: { data: Workspace }) => void
  state.api.mockImplementation(async (_method, path) => {
    if (path === '/agent/swarms') return { data: [] }
    if (fail) { fail = false; throw new Error('Offline') }
    if (hold) { hold = false; return new Promise(resolve => { finish = resolve }) }
    return { data: { ...next } }
  })
  const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
  const reads = () => state.api.mock.calls.filter(call => call[1] === '/projects/stable-project/okr')
  const view = render(<ProjectOkr projectId="stable-project" />)
  await advance(0)
  expect(reads()).toHaveLength(1)
  next = { ...initial, objective: 'Ignored unchanged revision' }
  await advance(29_999)
  expect(reads()).toHaveLength(1)
  await advance(1)
  expect(reads()).toHaveLength(2)
  expect(screen.getByText('Launch')).toBeTruthy()
  next = { ...initial, revision: 4, objective: 'Automatic update' }
  await advance(30_000)
  expect(screen.getByText('Automatic update')).toBeTruthy()
  expect(reads()).toHaveLength(3)
  await advance(0)
  expect(reads()).toHaveLength(3)
  fail = true
  await advance(30_000)
  expect(reads()).toHaveLength(4)
  await advance(30_000)
  expect(reads()).toHaveLength(4)
  await advance(30_000)
  expect(reads()).toHaveLength(5)
  hold = true
  await advance(30_000)
  expect(reads()).toHaveLength(6)
  const signal = reads()[5][3].signal as AbortSignal
  hidden = true
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(signal.aborted).toBe(true)
  await advance(60_000)
  expect(reads()).toHaveLength(6)
  hidden = false
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(reads()).toHaveLength(7)
  await act(async () => { finish({ data: { ...initial, revision: 99, objective: 'Aborted response' } }) })
  expect(screen.queryByText('Aborted response')).toBeNull()
  hold = true
  await advance(30_000)
  const lastSignal = reads()[7][3].signal as AbortSignal
  view.unmount()
  expect(lastSignal.aborted).toBe(true)
  await advance(60_000)
  expect(reads()).toHaveLength(8)
})

it('discards a poll when editing starts in flight and preserves the configuration draft', async () => {
  vi.useFakeTimers()
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  let next = initial, hold = false
  let finish!: (response: { data: Workspace }) => void
  state.api.mockImplementation(async (method, path) => {
    if (path === '/agent/swarms') return { data: [] }
    if (method === 'POST') throw Object.assign(new Error('OKR_CONFLICT'), { status: 409 })
    if (hold) { hold = false; return new Promise(resolve => { finish = resolve }) }
    return { data: next }
  })
  const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
  const reads = () => state.api.mock.calls.filter(call => call[0] === 'GET' && call[1] === '/projects/stable-project/okr')
  render(<ProjectOkr projectId="stable-project" />)
  await advance(0)
  hold = true
  await advance(30_000)
  fireEvent.click(screen.getByRole('button', { name: 'okr.edit' }))
  fireEvent.change(screen.getByLabelText('okr.objective'), { target: { value: 'My configuration draft' } })
  next = { ...initial, revision: 4, objective: 'External revision four' }
  await act(async () => { finish({ data: next }) })
  await advance(60_000)
  expect(reads()).toHaveLength(2)
  expect(screen.queryByText('External revision four')).toBeNull()
  expect((screen.getByLabelText('okr.objective') as HTMLTextAreaElement).value).toBe('My configuration draft')
  fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
  await advance(30_000)
  expect(screen.getByText('External revision four')).toBeTruthy()

})


it.each([false, true])('adopts a goal saved by the discussion without silently overwriting a dirty builder (%s)', async dirty => {
  let saved = false
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [] } : { data: saved ? { ...initial, revision: 1 } : null })
  render(<ProjectOkr projectId="new-project" />)
  await screen.findByLabelText('okr.objective')
  if (dirty) fireEvent.change(screen.getByLabelText('okr.objective'), { target: { value: 'My unsaved goal' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.chatOpen' }))
  const complete = await screen.findByRole('button', { name: 'Complete discussion' })
  saved = true
  fireEvent.click(complete)
  if (dirty) {
    await screen.findByText('okr.discussionUpdated')
    expect((screen.getByLabelText('okr.objective') as HTMLTextAreaElement).value).toBe('My unsaved goal')
    fireEvent.click(screen.getByRole('button', { name: 'okr.adoptUpdate' }))
  }
  await waitFor(() => expect(screen.queryByLabelText('okr.objective')).toBeNull())
  expect(screen.getByText('Launch')).toBeTruthy()
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})

it('keeps the inner navigation during editing and saves initiatives with KR bindings and dashboard definitions', async () => {
  const configured: Workspace = { ...initial,
    initiatives: [{ id: 'x-posts', title: 'X posts', channel: 'x', keyResultIds: ['kr1'], description: 'Share real examples', acceptance: 'Keep public receipts' }],
    dashboard: { schemaVersion: 1, widgets: [{ id: 'visits', type: 'metricTrend', metricIds: ['visits'], title: 'Observed visits' }] },
  }
  state.api.mockImplementation(async (method, path, body) => path === '/agent/swarms' ? { data: [] } : { data: method === 'PUT' ? { ...configured, ...body, revision: 4 } : configured })
  render(<ProjectOkr projectId="stable-project" />)
  fireEvent.click(await screen.findByRole('button', { name: 'okr.edit' }))
  fireEvent.change(screen.getByLabelText('okr.initiativeTitle'), { target: { value: 'Weekly X walkthroughs' } })
  panel('data')
  expect(screen.getByRole('tab', { name: 'okr.tab.okr' })).toBeTruthy()
  panel('overview')
  expect((screen.getByLabelText('okr.initiativeTitle') as HTMLInputElement).value).toBe('Weekly X walkthroughs')
  fireEvent.click(screen.getByRole('button', { name: 'okr.save' }))
  await waitFor(() => expect(state.api.mock.calls.some(call => call[0] === 'PUT')).toBe(true))
  const saved = state.api.mock.calls.find(call => call[0] === 'PUT')![2]
  expect(saved.initiatives).toEqual([{ ...configured.initiatives![0], title: 'Weekly X walkthroughs' }])
  expect(saved.dashboard).toEqual(configured.dashboard)
  expect(saved).not.toHaveProperty('observations')
})

it('keeps a configuration draft on pending-file conflicts and offers file confirmation instead of a reload loop', async () => {
  let pending = true
  state.api.mockImplementation(async (method, path, body) => {
    if (path === '/agent/swarms') return { data: [] }
    if (method === 'PUT' && pending) throw Object.assign(new Error('OKR_FILES_PENDING'), { status: 409 })
    if (path.endsWith('/sync')) pending = false
    return { data: { ...initial, ...(method === 'PUT' ? body : {}), revision: pending ? 3 : 4 } }
  })
  render(<ProjectOkr projectId="stable-project" />)
  fireEvent.click(await screen.findByRole('button', { name: 'okr.edit' }))
  fireEvent.change(screen.getByLabelText('okr.objective'), { target: { value: 'Preserved GUI draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.save' }))
  expect((await screen.findByRole('alert')).textContent).toContain('okr.filesPendingConflict')
  expect(screen.queryByRole('button', { name: 'okr.loadLatest' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'okr.confirmFiles' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect((screen.getByLabelText('okr.objective') as HTMLTextAreaElement).value).toBe('Preserved GUI draft')
  fireEvent.click(screen.getByRole('button', { name: 'okr.save' }))
  await waitFor(() => expect(state.api.mock.calls.filter(call => call[0] === 'PUT')).toHaveLength(2))
  expect(state.api.mock.calls.filter(call => call[0] === 'PUT')[1][2]).toMatchObject({ revision: 4, objective: 'Preserved GUI draft' })
})

it('opens the project root and exposes memory separately without configuration or review pages', async () => {
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [] } : { data: { ...initial, projectFiles: { root: '.roami/okr', schemaVersion: 1, revision: 3 } } })
  render(<ProjectOkr projectId="stable-project" projectDir="/project" />)
  await screen.findByText('Launch')
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.files' }))
  expect((await screen.findByTestId('project-files')).textContent).toBe('/project')
  fireEvent.click(screen.getByRole('tab', { name: 'okr.teamMemory' }))
  expect((await screen.findAllByTestId('project-files')).some(item => item.textContent === '/project/.roami/okr/memory')).toBe(true)
  expect(screen.queryByRole('tab', { name: 'okr.tab.status' })).toBeNull()
  expect(screen.queryByText('okr.projectConfiguration')).toBeNull()
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})


it('keeps data as a read-only dashboard and leaves reflection in project files', async () => {
  render(<ProjectOkr projectId="stable-project" projectDir="/project" />)
  await screen.findByText('Launch')
  panel('data')
  expect(await screen.findAllByTestId('trend')).toHaveLength(2)
  for (const label of ['okr.reviewSummary', 'okr.value', 'okr.note']) expect(screen.queryByLabelText(label)).toBeNull()
  expect(screen.queryByRole('button', { name: 'okr.collect' })).toBeNull()
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
})


it('restores the former dashboard choice without restoring removed review navigation', async () => {
  localStorage.setItem('roam.okr.view:' + JSON.stringify([null, 'stable-project']), JSON.stringify({ mainPanel: 'board', panel: 'data' }))
  render(<ProjectOkr projectId="stable-project" />)
  await screen.findByRole('tab', { name: 'okr.tab.dashboard', selected: true })
  expect(screen.getByRole('tab', { name: 'okr.tab.dashboard' }).getAttribute('aria-selected')).toBe('true')
  expect(screen.queryByRole('tab', { name: 'okr.tab.review' })).toBeNull()
})
