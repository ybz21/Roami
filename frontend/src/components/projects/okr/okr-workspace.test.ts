import { describe, expect, it } from 'vitest'
import { configurationOf, dailyHistory, keyResultEvidence, shanghaiDate, sourceObservations, workspaceUpdated, type Observation, type Workspace } from './okr-workspace'

const observation = (id: string, date: string, value: number, capturedAt = date + 'T01:00:00Z', sourceKey = 'github:42:stars'): Observation => ({ id, metricId: 'stars', date, value, capturedAt, sourceKey, source: 'github', note: '' })
const workspace: Workspace = {
  revision: 8, projectId: 'project', objective: 'Launch', startDate: '2026-11-01', endDate: '2026-11-30',
  metrics: [{ id: 'stars', name: 'Stars', unit: '', source: 'github', repo: 'owner/repo', field: 'stars', sourceKey: 'github:42:stars' }],
  keyResults: [{ id: 'kr', title: 'Interest', horizon: 'short', metricId: 'stars', target: 10, mode: 'increase', dueDate: '2026-11-30' }],
  swarm: 'team', autoCollect: false, reviews: [], updatedAt: '2026-11-03T01:00:00Z',
  observations: [observation('old', '2026-11-01', 999, undefined, 'github:99:stars'), observation('a', '2026-11-01', 10), observation('b', '2026-11-01', 12, '2026-11-01T02:00:00Z'), observation('c', '2026-11-02', 9), observation('d', '2026-11-04', 20)],
}

describe('OKR evidence', () => {
  it('keeps same-day versions, takes the latest daily value, allows negative deltas and leaves date gaps unknown', () => {
    const rows = dailyHistory(sourceObservations(workspace, workspace.metrics[0]))
    expect(rows.map(row => [row.date, row.latest.value, row.delta, row.versions.length])).toEqual([
      ['2026-11-04', 20, null, 1], ['2026-11-02', 9, -3, 1], ['2026-11-01', 12, null, 2],
    ])
    expect(keyResultEvidence(workspace, workspace.keyResults[0])).toMatchObject({ baseline: { id: 'a', value: 10 }, latest: { id: 'd', value: 20 }, change: 10 })
  })
  it('does not guess an identity before GitHub collection, or reuse observations from a replaced repository', () => {
    expect(sourceObservations(workspace, { ...workspace.metrics[0], sourceKey: undefined })).toEqual([])
    expect(sourceObservations(workspace, { ...workspace.metrics[0], sourceKey: 'github:100:stars' })).toEqual([])
    expect(keyResultEvidence({ ...workspace, observations: [] }, workspace.keyResults[0])).toEqual({ baseline: undefined, latest: undefined, change: null })
  })
  it('keeps manual zero values and isolates baseline by period and key-result due date', () => {
    const metric = { ...workspace.metrics[0], source: 'manual' as const, sourceKey: undefined }
    const observations = [observation('a', '2026-10-31', 30), observation('b', '2026-11-01', 0), observation('c', '2026-11-04', 10)].map(o => ({ ...o, source: 'manual' as const, sourceKey: 'manual:stars' }))
    const evidence = keyResultEvidence({ ...workspace, metrics: [metric], observations }, { ...workspace.keyResults[0], dueDate: '2026-11-02' })
    expect(evidence.baseline?.value).toBe(0)
    expect(evidence.latest?.value).toBe(0)
  })
  it('only sends configuration, leaving all histories and source identities to the server', () => {
    const body = configurationOf(workspace)
    expect(body).not.toHaveProperty('observations')
    expect(body).not.toHaveProperty('reviews')
    expect(body).not.toHaveProperty('revision')
    expect(body.metrics[0]).not.toHaveProperty('sourceKey')
    expect(workspace.observations).toHaveLength(5)
  })
  it('uses the collection timezone across UTC midnight boundaries', () => {
    expect(shanghaiDate(new Date('2026-11-02T16:00:00Z'))).toBe('2026-11-03')
  })
  it('preserves editable initiatives and dashboard definitions without sharing draft references or sending project metadata', () => {
    const configured: Workspace = { ...workspace,
      initiatives: [{ id: 'video', title: 'Daily videos', channel: 'bilibili', keyResultIds: ['kr'], description: 'Narrated tips', acceptance: 'Playable media and publication receipts' }],
      dashboard: { schemaVersion: 1, widgets: [{ id: 'interest', type: 'keyResults', keyResultIds: ['kr'] }] },
      team: { schemaVersion: 1, roles: [{ id: 'editor', name: 'Editor', executor: 'codex', duty: 'Prepare reviewed drafts' }] },
      projectFiles: { root: '.roami/okr', schemaVersion: 1, revision: 8, teamMemory: 'Context' },
    }
    const draft = configurationOf(configured)
    expect(draft.initiatives).toEqual(configured.initiatives)
    expect(draft.dashboard).toEqual(configured.dashboard)
    expect(draft.team).toEqual(configured.team)
    expect(draft).not.toHaveProperty('projectFiles')
    draft.initiatives![0].keyResultIds.length = 0
    draft.dashboard!.widgets[0].keyResultIds!.length = 0
    draft.team!.roles[0].duty = 'Changed draft'
    expect(configured.initiatives![0].keyResultIds).toEqual(['kr'])
    expect(configured.dashboard!.widgets[0].keyResultIds).toEqual(['kr'])
    expect(configured.team!.roles[0].duty).toBe('Prepare reviewed drafts')
  })
})

it('preserves server append order for mixed RFC3339 fractional precision within one date', () => {
  const observations = [observation('first', '2026-11-01', 10, '2026-11-01T01:00:00Z'), observation('later', '2026-11-01', 12, '2026-11-01T01:00:00.5Z')]
  const changed = { ...workspace, observations }
  const rows = dailyHistory(sourceObservations(changed, workspace.metrics[0]))
  expect(rows[0].latest.id).toBe('later')
  expect(keyResultEvidence(changed, workspace.keyResults[0]).baseline?.id).toBe('first')
})

it('counts a met threshold as achieved while growth uses only the net increase', async () => {
  const { resultAttainment } = await import('./okr-workspace')
  const kr = { id: 'k', metricId: 'm', title: 'Goal', horizon: 'short' as const, target: 2, mode: 'atLeast' as const, dueDate: '2026-11-03' }
  const point = { date: '2026-11-03', value: 2 }
  expect(resultAttainment(kr, point, point)).toMatchObject({ achieved: 2, percent: 100, met: true })
  expect(resultAttainment({ ...kr, mode: 'increase', target: 100 }, point, point)).toMatchObject({ achieved: 0, percent: 0, met: false })
  expect(resultAttainment(kr, null, null).percent).toBeNull()
  expect(resultAttainment({ ...kr, mode: 'atMost', target: 3 }, point, point).met).toBe(true)
})


it('accepts live project memory and pending file changes at the same revision without reusing stale history', () => {
  const current = { ...workspace, projectFiles: { root: '.roami/okr', schemaVersion: 1 as const, revision: 8, teamMemorySha256: 'old', mainInstructions: 'Existing instructions' } }
  expect(workspaceUpdated(current, { ...current })).toBe(false)
  expect(workspaceUpdated(current, { ...current, projectFiles: { ...current.projectFiles, teamMemorySha256: 'new' } })).toBe(true)
  expect(workspaceUpdated(current, { ...current, projectFiles: { ...current.projectFiles, mainInstructions: 'New instructions' } })).toBe(true)
  expect(workspaceUpdated(current, { ...current, projectFiles: { ...current.projectFiles, pendingChanges: true } })).toBe(true)
  expect(workspaceUpdated(current, { ...current, revision: 7, projectFiles: { ...current.projectFiles, teamMemorySha256: 'new' } })).toBe(false)
  expect(workspaceUpdated(current, { ...current, observations: [] })).toBe(false)
})

it('round-trips explicit member bindings including clears without inventing bindings', () => {
  for (const memberId of [undefined, '', '0123456789abcdef0123456789abcdef']) {
    const team = { schemaVersion: 1 as const, roles: [{ id: 'editor', name: 'Editor', executor: 'codex' as const, duty: 'Write', ...(memberId !== undefined ? { memberId } : {}) }] }
    expect(configurationOf({ ...workspace, team }).team).toEqual(team)
  }
})
