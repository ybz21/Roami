// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProjectOkr from './ProjectOkr'
import { type Workspace } from './okr-workspace'

vi.mock('./OkrMainChat', () => ({ default: ({ onUpdated }: { onUpdated: () => void }) => <button onClick={onUpdated}>Complete discussion</button> }))
vi.mock('./OkrTrend', () => ({ default: () => <div data-testid="trend" /> }))
vi.mock('./OkrProjectFiles', () => ({ default: ({ dir }: { dir: string }) => <div data-testid="project-files">{dir}</div> }))
vi.mock('../../swarm/useSwarmSnapshot', () => ({ useSwarmSnapshot: () => ({ data: null, error: false, refresh: vi.fn() }) }))
vi.mock('../../swarm/Swarm', () => ({ default: ({ initialSwarm }: { initialSwarm: string }) => <div data-testid="activities">{initialSwarm}</div> }))

function panel(key: string) {
  const choice = screen.queryByRole('radio', { name: 'okr.tab.' + ({ overview: 'okr', data: 'dashboard', review: 'status' }[key] || key) })
  if (choice) fireEvent.click(choice)
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
  state.phone = false
  state.api.mockReset()
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [{ id: 'sw-11111111111111111111111111111111', name: 'real-team' }] } : { data: initial })
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

it('keeps project navigation available and preserves a configuration draft across files', async () => {
  render(<ProjectOkr projectId="stable-project" projectDir="/project" />)
  fireEvent.click(await screen.findByRole('button', { name: 'okr.edit' }))
  fireEvent.change(screen.getByLabelText('okr.objective'), { target: { value: 'Unfinished goal edit' } })
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.files' }))
  expect(await screen.findByTestId('project-files')).toHaveProperty('textContent', '/project')
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.board' }))
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

it('records manual zero and real review input, uses each returned revision and links to the existing swarm', async () => {
  let revision = 3
  state.api.mockImplementation(async (method, path, body) => {
    if (path === '/agent/swarms') return { data: [{ id: 'sw-11111111111111111111111111111111', name: 'real-team' }] }
    if (method === 'POST') return { data: { ...initial, revision: ++revision, reviews: path.endsWith('/reviews') ? [{ id: 'review', ...body, evidenceRevision: revision - 1, date: '2026-11-03T01:00:00Z' }] : [] } }
    return { data: initial }
  })
  render(<ProjectOkr projectId="stable-project" />)
  await screen.findByText('Launch')
  expect(screen.queryByTestId('activities')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.activities' }))
  expect(await screen.findByTestId('activities')).toHaveProperty('textContent', 'sw-11111111111111111111111111111111')
  fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.board' }))
  panel('data')
  fireEvent.change(screen.getByLabelText('okr.value'), { target: { value: '0' } })
  fireEvent.change(screen.getByLabelText('okr.date'), { target: { value: '2026-11-02' } })
  fireEvent.change(screen.getByLabelText('okr.note'), { target: { value: 'Actual count' } })
  fireEvent.submit(screen.getByLabelText('okr.value').closest('form')!)
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/projects/stable-project/okr/observations', expect.objectContaining({ revision: 3, metricId: 'visits', value: 0, note: 'Actual count' })))
  await waitFor(() => expect((screen.getByLabelText('okr.note') as HTMLInputElement).value).toBe(''))
  panel('review')
  fireEvent.change(screen.getByLabelText('okr.reviewSummary'), { target: { value: 'Observed outcome' } })
  fireEvent.change(screen.getByLabelText('okr.reviewActions'), { target: { value: 'Next experiment' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.submitReview' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/projects/stable-project/okr/reviews', { revision: 4, summary: 'Observed outcome', actions: 'Next experiment' }))
  expect((await screen.findAllByText('Observed outcome')).length).toBeGreaterThan(0)
})

it('does not collect on template selection or page load; only collects saved sources on explicit action', async () => {
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [] } : { data: null })
  const view = render(<ProjectOkr projectId="new-project" />)
  fireEvent.click(await screen.findByRole('button', { name: 'okr.template.use' }))
  expect((screen.getByLabelText('okr.objective') as HTMLTextAreaElement).value).toBe('okr.template.objective')
  expect(state.api.mock.calls.every(call => call[0] === 'GET')).toBe(true)
  view.unmount()
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [] } : { data: initial })
  render(<ProjectOkr projectId="stable-project" />)
  await screen.findByText('Launch')
  panel('data')
  fireEvent.click(screen.getByRole('button', { name: 'okr.collect' }))
  await waitFor(() => expect(state.api).toHaveBeenCalledWith('POST', '/projects/stable-project/okr/collect', { revision: 3 }))
})

it('keeps manual and review input on conflicts and never displays invented progress', async () => {
  state.api.mockImplementation(async (method, path) => {
    if (path === '/agent/swarms') return { data: [] }
    if (method === 'POST') throw Object.assign(new Error('OKR_CONFLICT'), { status: 409 })
    return { data: initial }
  })
  render(<ProjectOkr projectId="stable-project" />)
  await screen.findByText('Launch')
  expect(screen.queryByText('okr.periodChange')).toBeNull()
  panel('data')
  fireEvent.change(screen.getByLabelText('okr.value'), { target: { value: '5' } })
  fireEvent.change(screen.getByLabelText('okr.note'), { target: { value: 'Kept note' } })
  panel('review')
  fireEvent.change(screen.getByLabelText('okr.reviewSummary'), { target: { value: 'Kept review' } })
  fireEvent.change(screen.getByLabelText('okr.reviewActions'), { target: { value: 'Kept actions' } })
  fireEvent.submit(screen.getByLabelText('okr.value').closest('form')!)
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'okr.loadLatest' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect((screen.getByLabelText('okr.value') as HTMLInputElement).value).toBe('5')
  expect((screen.getByLabelText('okr.note') as HTMLInputElement).value).toBe('Kept note')
  expect((screen.getByLabelText('okr.reviewSummary') as HTMLTextAreaElement).value).toBe('Kept review')
  expect((screen.getByLabelText('okr.reviewActions') as HTMLTextAreaElement).value).toBe('Kept actions')
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

it('keeps a removed manual metric unselected after conflict instead of moving the draft to another metric', async () => {
  let changed = false
  state.api.mockImplementation(async (method, path) => {
    if (path === '/agent/swarms') return { data: [] }
    if (method === 'POST') { changed = true; throw Object.assign(new Error('OKR_CONFLICT'), { status: 409 }) }
    return { data: changed ? { ...initial, revision: 8, metrics: [{ id: 'another', name: 'Another metric', source: 'manual', unit: '' }], keyResults: [{ ...initial.keyResults[0], metricId: 'another' }] } : initial }
  })
  render(<ProjectOkr projectId="stable-project" />)
  await screen.findByText('Launch')
  panel('data')
  fireEvent.change(screen.getByLabelText('okr.value'), { target: { value: '5' } })
  fireEvent.change(screen.getByLabelText('okr.note'), { target: { value: 'Original metric note' } })
  fireEvent.submit(screen.getByLabelText('okr.value').closest('form')!)
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'okr.loadLatest' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  fireEvent.submit(screen.getByLabelText('okr.value').closest('form')!)
  expect(state.api.mock.calls.filter(c => c[0] === 'POST')).toHaveLength(1)
  expect((screen.getByLabelText('okr.note') as HTMLInputElement).value).toBe('Original metric note')
  panel('data')
  expect((screen.getByRole('button', { name: 'okr.record' }) as HTMLButtonElement).disabled).toBe(true)
})

it('keeps removed-metric history traceable and marks reviews only after a subsequent revision', async () => {
  const historical = { ...initial, revision: 4, reviews: [{ id: 'review', summary: 'Saved review', actions: '', date: '2026-11-03T01:00:00Z', evidenceRevision: 3 }], observations: [{ id: 'old', metricId: 'removed', date: '2026-11-01', value: 6, note: 'Retained evidence', source: 'manual', sourceKey: 'manual:removed', capturedAt: '2026-11-01T01:00:00Z' }] }
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [] } : { data: historical })
  const view = render(<ProjectOkr projectId="stable-project" />)
  expect(await screen.findByText('Retained evidence')).toBeTruthy()
  expect(screen.queryByText('okr.reviewUpdated')).toBeNull()
  view.unmount()
  state.api.mockImplementation(async (_method, path) => path === '/agent/swarms' ? { data: [] } : { data: { ...historical, revision: 5 } })
  render(<ProjectOkr projectId="stable-project" />)
  expect(await screen.findByText('okr.reviewUpdated')).toBeTruthy()
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

it('discards a poll when editing starts in flight and preserves manual or review drafts with their original revision', async () => {
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
  panel('data')
  fireEvent.change(screen.getByLabelText('okr.value'), { target: { value: '0' } })
  next = { ...initial, revision: 5, objective: 'External revision five' }
  await advance(60_000)
  expect(reads()).toHaveLength(3)
  expect((screen.getByLabelText('okr.value') as HTMLInputElement).value).toBe('0')
  panel('data')
  fireEvent.change(screen.getByLabelText('okr.value'), { target: { value: '' } })
  await advance(30_000)
  expect(screen.getByText('External revision five')).toBeTruthy()
  panel('review')
  fireEvent.change(screen.getByLabelText('okr.reviewSummary'), { target: { value: 'My review draft' } })
  fireEvent.change(screen.getByLabelText('okr.reviewActions'), { target: { value: 'My actions' } })
  next = { ...initial, revision: 6, objective: 'External revision six' }
  await advance(60_000)
  expect(reads()).toHaveLength(4)
  expect(screen.queryByText('External revision six')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'okr.submitReview' }))
  await advance(0)
  expect(state.api).toHaveBeenCalledWith('POST', '/projects/stable-project/okr/reviews', { revision: 5, summary: 'My review draft', actions: 'My actions' })
  expect((screen.getByLabelText('okr.reviewSummary') as HTMLTextAreaElement).value).toBe('My review draft')
  expect(screen.getByRole('alert').textContent).toContain('okr.conflict')
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
  expect(screen.getByRole('radio', { name: 'okr.tab.okr' })).toBeTruthy()
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
