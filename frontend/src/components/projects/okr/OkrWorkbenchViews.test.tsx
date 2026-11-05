// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OkrDashboard from './OkrDashboard'
import OkrCurrentStatus from './OkrCurrentStatus'
import OkrTeamMemory from './OkrTeamMemory'
import type { Workspace } from './okr-workspace'

const state = vi.hoisted(() => ({ api: vi.fn(), snapshot: null as unknown, refresh: vi.fn(), error: false }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string, vars?: object) => key + (vars ? JSON.stringify(vars) : '') }) }))
vi.mock('../../swarm/useSwarmSnapshot', () => ({ useSwarmSnapshot: () => ({ data: state.snapshot, error: state.error, refresh: state.refresh }) }))
vi.mock('./OkrTrend', () => ({ default: ({ title, workspace }: { title?: string; workspace: Workspace }) => <section>{title}<span>{workspace.metrics.map(metric => metric.name).join(',')}</span></section> }))

const workspace: Workspace = {
  projectId: 'project', objective: 'Reach developers', revision: 4, startDate: '2026-11-01', endDate: '2026-11-30', swarm: 'team', autoCollect: false, updatedAt: '2026-11-03T00:00:00Z',
  metrics: [{ id: 'clicks', name: 'X clicks', source: 'manual', unit: '' }, { id: 'watch', name: 'Video watch time', source: 'manual', unit: 'seconds' }],
  keyResults: [{ id: 'reach', title: 'Reach people', horizon: 'short', metricId: 'clicks', mode: 'atLeast', target: 100, dueDate: '2026-11-30' }], observations: [], reviews: [],
  projectFiles: { root: '.roami/okr', revision: 4, schemaVersion: 1, teamMemoryFile: 'memory/team.md', teamMemory: 'Existing memory', teamMemorySha256: 'old-hash' },
}
beforeEach(() => {
  state.api.mockReset(); state.snapshot = null; state.error = false
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(cleanup)

it('renders only configured known widgets and restricts metric trends to their declared metrics', () => {
  render(<OkrDashboard workspace={{ ...workspace, dashboard: { schemaVersion: 1, widgets: [{ id: 'watch', type: 'metricTrend', title: 'Video evidence', metricIds: ['watch'] }] } }} />)
  expect(screen.getByText('Video evidence')).toBeTruthy()
  expect(screen.getByText('Video evidence').closest('section')?.textContent).toBe('Video evidenceVideo watch time')
  expect(screen.getAllByText('Video watch time')).toHaveLength(1)
  expect(screen.queryByText('X clicks')).toBeNull()
  expect(screen.queryByText('okr.nextAction')).toBeNull()
})

it('gives each configured metric its own trend card with no other metric data', () => {
  render(<OkrDashboard workspace={{ ...workspace, dashboard: { schemaVersion: 1, widgets: [{ id: 'trends', type: 'metricTrend', title: 'All metrics', metricIds: ['clicks', 'watch'] }] } }} />)
  const cards = screen.getByLabelText('okr.tab.dashboard').querySelectorAll('.okr-trend-grid > section')
  expect(cards).toHaveLength(2)
  expect(cards[0].textContent).toBe('X clicksX clicks')
  expect(cards[1].textContent).toBe('Video watch timeVideo watch time')
  expect(screen.queryByText('All metrics')).toBeNull()
})

it('does not reserve a blank key-results section above the trend cards', () => {
  render(<OkrDashboard workspace={{ ...workspace, keyResults: [] }} />)
  expect(screen.queryByText('okr.keyResults')).toBeNull()
  expect(screen.getByLabelText('okr.tab.dashboard').querySelectorAll('.okr-trend-grid > section')).toHaveLength(2)
})

it('does not invent a trend card when the configured metric is missing', () => {
  render(<OkrDashboard workspace={{ ...workspace, dashboard: { schemaVersion: 1, widgets: [{ id: 'missing', type: 'metricTrend', metricIds: ['removed-metric'] }] } }} />)
  expect(screen.getByText('okr.noWidgets')).toBeTruthy()
  expect(screen.queryByText('X clicks')).toBeNull()
})

it('keeps task state authoritative and separates stored media, acceptance, external receipts and executor claims', () => {
  state.snapshot = {
    id: 'team', name: 'Promotion team', state: 'failed', mainState: 'idle', work: [{
      id: 'video', title: 'Publish tutorial', member_name: 'creator', task_id: 'task-video', state: 'failed', dispatch_error: null, dependencies: [],
      attempt: { summary: 'Everything was published successfully' },
      evidence: { artifacts: [{ id: 'actual-video', name: 'tutorial.mp4', mimeType: 'video/mp4', sizeBytes: 2048 }], verification: { kind: 'declared_deliverables', state: 'awaiting_acceptance', externalAction: 'unconfirmed' } },
    }],
  }
  render(<OkrCurrentStatus swarm="team" onActivities={vi.fn()} onConfigure={vi.fn()} />)
  expect(screen.getAllByText('swarm.managed.state.failed')).toHaveLength(2)
  expect(screen.getByRole('link', { name: /tutorial.mp4/ }).getAttribute('href')).toContain('actual-video')
  const player = screen.getByLabelText('tutorial.mp4') as HTMLVideoElement
  expect(player.tagName).toBe('VIDEO')
  expect(player.controls).toBe(true)
  expect(player.getAttribute('src')).toContain('actual-video/content')
  expect(screen.getByText('okr.verification.awaiting_acceptance')).toBeTruthy()
  expect(screen.getByText('okr.externalUnconfirmed')).toBeTruthy()
  expect(screen.queryByText('okr.verification.accepted')).toBeNull()
  expect(screen.getByText('Everything was published successfully').closest('details')?.open).toBe(false)
})

it('does not promote an executor summary into missing delivery evidence', () => {
  state.snapshot = { id: 'team', name: 'Team', state: 'waiting_user', work: [{ id: 'task', title: 'Make video', member_name: 'maker', state: 'waiting_user', dependencies: [], attempt: { summary: 'Video done' } }] }
  render(<OkrCurrentStatus swarm="team" onActivities={vi.fn()} onConfigure={vi.fn()} />)
  expect(screen.getByText('okr.noTaskEvidence')).toBeTruthy()
  expect(screen.getByText('okr.verificationUnknown')).toBeTruthy()
  expect(screen.queryByRole('link')).toBeNull()
})

it('offers explicit team relinking when an old or unavailable source team cannot load', () => {
  const configure = vi.fn(), history = vi.fn()
  state.error = true
  render(<OkrCurrentStatus swarm="legacy-promotion-team" onActivities={history} onConfigure={configure} />)
  expect(screen.getByRole('alert').textContent).toBe('okr.statusUnavailable')
  fireEvent.click(screen.getByRole('button', { name: 'okr.viewTeamHistory' }))
  expect(history).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: 'inbox.retry' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'okr.changeTeam' }))
  expect(configure).toHaveBeenCalledOnce()
  expect(state.api).not.toHaveBeenCalled()
})

it('preserves a memory draft after conflict, compares the latest text and retries with its hash', async () => {
  const updated = vi.fn(), dirty = vi.fn()
  let writes = 0
  state.api.mockImplementation(async method => {
    if (method === 'PUT' && ++writes === 1) throw Object.assign(new Error('STALE_MEMORY'), { status: 409 })
    return { data: { ...workspace, projectFiles: { ...workspace.projectFiles, teamMemory: 'Remote edit', teamMemorySha256: 'latest-hash' } } }
  })
  render(<OkrTeamMemory workspace={workspace} onUpdated={updated} onFiles={vi.fn()} onDraftChange={dirty} />)
  fireEvent.click(screen.getByRole('button', { name: 'okr.edit' }))
  fireEvent.change(screen.getByLabelText('okr.teamMemory'), { target: { value: 'My preserved draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'okr.saveMemory' }))
  expect((await screen.findByRole('alert')).textContent).toBe('okr.memoryConflict')
  expect((screen.getByLabelText('okr.teamMemory') as HTMLTextAreaElement).value).toBe('My preserved draft')
  fireEvent.click(screen.getByRole('button', { name: 'okr.compareMemory' }))
  await screen.findByText('Remote edit')
  expect((screen.getByLabelText('okr.teamMemory') as HTMLTextAreaElement).value).toBe('My preserved draft')
  fireEvent.click(screen.getByRole('button', { name: 'okr.saveMemory' }))
  await waitFor(() => expect(state.api).toHaveBeenLastCalledWith('PUT', '/projects/project/okr/memory', { content: 'My preserved draft', expectedSha256: 'latest-hash' }))
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false))
})
