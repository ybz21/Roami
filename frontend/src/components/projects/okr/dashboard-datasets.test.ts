import { expect, it } from 'vitest'
import { dashboardDatasets } from './dashboard-datasets'
import type { Workspace } from './okr-workspace'

const workspace: Workspace = {
 projectId: 'project', objective: 'Reach developers', revision: 9, startDate: '2026-11-01', endDate: '2026-11-30', swarm: '', autoCollect: false, updatedAt: 'now', keyResults: [], reviews: [],
 metrics: [{ id: 'users', name: 'Users', unit: 'people', source: 'manual', sourceKey: 'manual:users' }, { id: 'stars', name: 'Stars', unit: '', source: 'github', sourceKey: 'github:new', repo: 'owner/new', field: 'stars' }],
 observations: [
 { id: 'one', metricId: 'users', source: 'manual', sourceKey: 'manual:users', date: '2026-11-02', value: 8, capturedAt: '2026-11-02T01:00:00Z', note: '' },
 { id: 'two', metricId: 'users', source: 'manual', sourceKey: 'manual:users', date: '2026-11-02', value: 0, capturedAt: '2026-11-02T01:00:00.000Z', note: '' },
 { id: 'old', metricId: 'stars', source: 'github', sourceKey: 'github:old', date: '2026-11-03', value: 15, capturedAt: 'now', note: '' },
 ],
}
it('passes only declared metrics, retains observed zero and uses the current source identity', () => {
 const datasets = dashboardDatasets(workspace, ['users', 'stars', 'missing'])
 expect(Object.keys(datasets)).toEqual(['users', 'stars'])
 expect(datasets.users.latest.value).toBe(0)
 expect(datasets.users.points).toEqual([{ date: '2026-11-02', value: 0 }])
 expect(datasets.users.quality).toBe('observed')
 expect(datasets.users.revision).toBe(9)
 expect(datasets.stars.latest.value).toBeNull()
 expect(datasets.stars.points).toEqual([])
 expect(datasets.stars.quality).toBe('unknown')
 expect(datasets.stars.source.identity).toBe('github:new')
 expect(datasets.stars.source.resource).toBe('owner/new')
})
it('does not discard the last successful observation when a later collection has no new fact', () => {
 const before = dashboardDatasets(workspace, ['users']).users
 const after = dashboardDatasets({ ...workspace, revision: 10 }, ['users']).users
 expect(after.latest).toEqual(before.latest)
 expect(after.points).toEqual(before.points)
 expect(after.revision).toBe(10)
})
