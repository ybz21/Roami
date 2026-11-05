export type Metric = { id: string; name: string; unit: string; source: 'manual' | 'github'; repo?: string; field?: 'stars' | 'forks'; sourceKey?: string }
export type KeyResult = { id: string; title: string; horizon: 'long' | 'short'; metricId: string; target: number; mode: 'increase' | 'atLeast' | 'atMost'; dueDate: string }
export type Initiative = { id: string; title: string; channel: string; keyResultIds: string[]; description: string; acceptance: string }
export type DashboardWidget = { id: string; type: 'keyResults' | 'metricTrend' | 'nextAction'; keyResultIds?: string[]; metricIds?: string[]; title?: string }
export type Dashboard = { schemaVersion: 1; widgets: DashboardWidget[] }
export type TeamDefinition = { schemaVersion: 1; roles: { id: string; memberId?: string; name: string; executor: 'native' | 'codex' | 'claude' | 'opencode' | 'pi'; duty: string }[] }
export type Configuration = { objective: string; startDate: string; endDate: string; keyResults: KeyResult[]; metrics: Metric[]; swarm: string; autoCollect: boolean; initiatives?: Initiative[]; dashboard?: Dashboard; team?: TeamDefinition }
export type Observation = { id: string; metricId: string; date: string; value: number; source: 'manual' | 'github'; sourceKey: string; capturedAt: string; note: string }
export type Review = { id: string; summary: string; actions: string; date: string; evidenceRevision: number }
export type Workspace = Configuration & { revision: number; projectId: string; observations: Observation[]; reviews: Review[]; updatedAt: string; projectFiles?: { root: string; schemaVersion: 1; revision: number; mainInstructionsFile?: string; teamMemoryFile?: string; mainInstructions?: string; teamMemory?: string; teamMemorySha256?: string; pendingChanges?: boolean; skills?: { id: string; path: string; content: string; sha256: string }[] } }
export type EvidencePoint = { date: string; value: number }
export type ResultOverview = KeyResult & { unit: string; baseline: EvidencePoint | null; latest: EvidencePoint | null; delta: number | null }
export type OkrOverview = Pick<Workspace, 'projectId' | 'objective' | 'startDate' | 'endDate' | 'updatedAt' | 'revision'> & { projectName: string; keyResults: ResultOverview[] }

export function workspaceUpdated(current: Workspace | null, next: Workspace | null): next is Workspace {
  return !!next && (!current || next.revision > current.revision || next.revision === current.revision && JSON.stringify(next.projectFiles) !== JSON.stringify(current.projectFiles))
}

export function resultAttainment(kr: KeyResult, baseline?: EvidencePoint | null, latest?: EvidencePoint | null) {
  const achieved = latest ? kr.mode === 'increase' ? baseline ? latest.value - baseline.value : null : latest.value : null
  if (achieved === null) return { achieved: null, percent: null, met: false }
  const met = kr.mode === 'atMost' ? achieved <= kr.target : achieved >= kr.target
  const percent = kr.mode !== 'atMost' && kr.target > 0 ? Math.max(0, Math.min(100, achieved / kr.target * 100)) : met ? 100 : 0
  return { achieved, percent, met }
}

export function resultOverview(workspace: Workspace, kr: KeyResult): ResultOverview {
  const { baseline, latest } = keyResultEvidence(workspace, kr)
  const metric = workspace.metrics.find(m => m.id === kr.metricId)
  const days = metric ? dailyHistory(sourceObservations(workspace, metric).filter(o => o.date >= workspace.startDate && o.date <= kr.dueDate)) : []
  return { ...kr, unit: metric?.unit || '', baseline: baseline || null, latest: latest || null, delta: days[0]?.delta ?? null }
}

export function shanghaiDate(now = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}
export function dateOffset(date: string, days: number): string {
  const value = new Date(date + 'T00:00:00Z')
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}
export function emptyConfiguration(): Configuration {
  const startDate = shanghaiDate()
  return { objective: '', startDate, endDate: dateOffset(startDate, 30), metrics: [], keyResults: [], swarm: '', autoCollect: false }
}
// Explicit projection keeps server-owned history and derived source identities out of PUT.
export function configurationOf(value: Configuration): Configuration {
  return {
    objective: value.objective, startDate: value.startDate, endDate: value.endDate,
    metrics: value.metrics.map(({ id, name, unit, source, repo, field }) => ({ id, name, unit, source, ...(source === 'github' ? { repo, field } : {}) })),
    keyResults: value.keyResults.map(kr => ({ ...kr })), swarm: value.swarm, autoCollect: value.autoCollect,
    ...(value.team ? { team: { schemaVersion: 1 as const, roles: value.team.roles.map(({ id, name, executor, duty, memberId }) => ({ id, name, executor, duty, ...(memberId !== undefined ? { memberId } : {}) })) } } : {}),
    ...(value.initiatives ? { initiatives: value.initiatives.map(({ id, title, channel, keyResultIds, description, acceptance }) => ({ id, title, channel, keyResultIds: [...keyResultIds], description, acceptance })) } : {}),
    ...(value.dashboard ? { dashboard: { schemaVersion: 1 as const, widgets: value.dashboard.widgets.map(({ id, type, title, keyResultIds, metricIds }) => ({ id, type, ...(title !== undefined ? { title } : {}), ...(keyResultIds ? { keyResultIds: [...keyResultIds] } : {}), ...(metricIds ? { metricIds: [...metricIds] } : {}) })) } } : {}),
  }
}
export function dashboardOf(value: Configuration): Dashboard {
  return value.dashboard || { schemaVersion: 1, widgets: [{ id: 'key-results', type: 'keyResults' }, { id: 'metric-trend', type: 'metricTrend' }, { id: 'next-action', type: 'nextAction' }] }
}
export function stableId(prefix: string): string {
  return prefix + Array.from(crypto.getRandomValues(new Uint32Array(2)), n => n.toString(16).padStart(8, '0')).join('')
}
export function sourceObservations(workspace: Workspace, metric: Metric): Observation[] {
  const key = metric.sourceKey || (metric.source === 'manual' ? 'manual:' + metric.id : '')
  if (!key) return []
  // Same-day versions retain server append order, including mixed timestamp precision.
  return (workspace.observations || []).filter(o => o.metricId === metric.id && o.source === metric.source && o.sourceKey === key && Number.isFinite(o.value))
    .sort((a, b) => a.date.localeCompare(b.date))
}
export function dailyHistory(observations: Observation[]) {
  const byDate = new Map<string, Observation[]>()
  for (const observation of observations) byDate.set(observation.date, [...(byDate.get(observation.date) || []), observation])
  return [...byDate.entries()].map(([date, versions]) => {
    const latest = versions[versions.length - 1]
    const previous = byDate.get(dateOffset(date, -1))?.slice(-1)[0]
    return { date, latest, versions, delta: previous ? latest.value - previous.value : null }
  }).reverse()
}
export function keyResultEvidence(workspace: Workspace, kr: KeyResult) {
  const metric = workspace.metrics.find(m => m.id === kr.metricId)
  const observations = metric ? sourceObservations(workspace, metric).filter(o => o.date >= workspace.startDate && o.date <= kr.dueDate) : []
  const baseline = observations[0]
  const latest = observations[observations.length - 1]
  return { baseline, latest, change: baseline && latest ? latest.value - baseline.value : null }
}
export function projectPath(projectId: string, okr = false): string {
  return 'projects/' + encodeURIComponent(projectId) + (okr ? '/okr' : '')
}
