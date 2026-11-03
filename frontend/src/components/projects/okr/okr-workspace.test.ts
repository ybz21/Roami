import { describe, expect, it } from 'vitest'
import { configurationOf, dailyHistory, keyResultEvidence, shanghaiDate, sourceObservations, type Observation, type Workspace } from './okr-workspace'

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
})

it('preserves server append order for mixed RFC3339 fractional precision within one date', () => {
  const observations = [observation('first', '2026-11-01', 10, '2026-11-01T01:00:00Z'), observation('later', '2026-11-01', 12, '2026-11-01T01:00:00.5Z')]
  const changed = { ...workspace, observations }
  const rows = dailyHistory(sourceObservations(changed, workspace.metrics[0]))
  expect(rows[0].latest.id).toBe('later')
  expect(keyResultEvidence(changed, workspace.keyResults[0]).baseline?.id).toBe('first')
})
