import { sourceObservations, type Workspace } from './okr-workspace'

export type DashboardDataset = {
  id: string; name: string; unit: string; snapshotId: string; revision: number
  latest: { value: number | null; date: string | null; capturedAt: string | null }
  points: { date: string; value: number }[]
  source: { kind: string; identity: string; resource?: string }
  asOf: string | null; quality: 'observed' | 'unknown'; lastError: null
}

export function dashboardDatasets(workspace: Workspace, ids: string[]): Record<string, DashboardDataset> {
  return Object.fromEntries(ids.flatMap(id => {
    const metric = workspace.metrics.find(metric => metric.id === id)
    if (!metric) return []
    const observations = sourceObservations(workspace, metric)
    const days = new Map(observations.map(point => [point.date, point]))
    const latest = observations[observations.length - 1]
    return [[id, {
      id, name: metric.name, unit: metric.unit, snapshotId: String(workspace.revision), revision: workspace.revision,
      latest: { value: latest?.value ?? null, date: latest?.date ?? null, capturedAt: latest?.capturedAt ?? null },
      points: [...days.values()].map(point => ({ date: point.date, value: point.value })),
      source: { kind: metric.source, identity: metric.sourceKey || (metric.source === 'manual' ? 'manual:' + metric.id : ''), ...(metric.repo ? { resource: metric.repo } : {}) },
      asOf: latest?.date ?? null, quality: latest ? 'observed' : 'unknown', lastError: null,
    } satisfies DashboardDataset]]
  }))
}
