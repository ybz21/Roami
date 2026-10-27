export type CaseStatus = 'passed' | 'failed' | 'pending' | 'not_run' | 'running' | 'blocked' | 'unknown' | 'cancelled'
export type CaseGroup = 'authored' | 'public' | 'mechanism'
export type IssueState = 'open' | 'recurred' | 'observing' | 'closed' | 'planned' | 'unverified'
export type IssueType = 'fix' | 'feature'
export type Priority = 'P0' | 'P1' | 'P2' | 'P3'
export type RunRecord = {
  id: string; time: string; mode: 'full' | 'quick'; state: 'completed' | 'partial' | 'running' | 'paused' | 'interrupted'
  verifiedSourcePairs?: string[]; closed?: string[]; verificationEvidence?: Record<string, unknown>; rawState?: string; blocker?: string | null; publication?: { url: string; number: number } | null
  scope: string[]; results: Record<string, CaseStatus>; verified: string[]
  source: string; suite: string; judge: string; models: string; machine: string
  sequence?: number; caseDefinitions?: CaseDefinition[]; caseEvidence?: Record<string, unknown>; caseHashes?: Record<string, string>; issueObservations?: Record<string, string>; workflow?: Record<string, { state: string; error?: string | null; artifacts: { id: string; name: string }[] }>
}
export type CaseDefinition = { id: string; title?: string; name?: string; description?: string; group: CaseGroup }
export type IssueDefinition = {
  analysisArtifact?: { id: string; name: string; runId: string } | null; signal?: string; originalRun?: string; historyTruncated?: boolean
  id: string; title?: string; name?: string; description?: string; type: IssueType; priority: Priority; firstRun: string
  cases: string[]; fingerprint: string; reason: string; acceptance: string; reasonText?: string; acceptanceText?: string
}
export type IssueAssessment = {
  issue: IssueDefinition; state: IssueState; coverage: CaseStatus | 'planned' | 'incomparable'
  failures: string[]; signalRuns: string[]; seen: string[]; passed: string[]; observations: number; verificationRun: string | null; lastVerificationRun: string | null
}
export function issueCoverage(issue: IssueDefinition, run: RunRecord): CaseStatus | 'planned' | 'incomparable' {
  if (issue.type === 'feature') return 'planned'
  if (run.issueObservations) return ({ present: 'failed', not_reproduced: 'passed', unverified: 'pending', not_tested: 'not_run', not_comparable: 'incomparable' } as const)[run.issueObservations[issue.id]] || 'not_run'
  if (issue.cases.some(id => run.results[id] === 'failed')) return 'failed'
  for (const status of ['blocked', 'unknown', 'cancelled'] as const) if (issue.cases.some(id => run.results[id] === status)) return status
  if (issue.cases.some(id => run.results[id] === 'pending')) return 'pending'
  if (issue.cases.some(id => run.results[id] === 'running')) return 'running'
  if (!issue.cases.every(id => run.scope.includes(id) && run.results[id] === 'passed')) return 'not_run'
  return 'passed'
}
export function comparable(a: RunRecord, b: RunRecord) {
  return ['suite', 'judge', 'models', 'machine'].every(key => a[key as keyof RunRecord] === b[key as keyof RunRecord])
}
export function assessIssues(runs: RunRecord[], runId: string, issues: IssueDefinition[]): IssueAssessment[] {
  const until = runs.findIndex(run => run.id === runId)
  if (until < 0) return []
  const past = runs.slice(0, until + 1)
  return issues.filter(issue => past.some(run => run.id === issue.firstRun)).map(issue => {
    let state: IssueState = issue.type === 'feature' ? 'planned' : 'open'
    const failures: string[] = [], seen: string[] = [], passed: string[] = []
    let verification: RunRecord | null = null, observations = 0, lastVerificationRun: string | null = null
    const first = past.findIndex(run => run.id === issue.firstRun)
    const origin = past[first]
    const signalRuns = past.filter((run, index) => index >= first && issueCoverage(issue, run) === 'failed').map(run => run.id)
    for (const [index, run] of past.entries()) {
      const sameCase = issue.cases.length > 0 && issue.cases.every(id => !!origin.caseHashes?.[id] && origin.caseHashes[id] === run.caseHashes?.[id])
      if (index < first || !comparable(origin, run) && !sameCase) continue
      const result = issueCoverage(issue, run)
      if (result !== 'not_run') seen.push(run.id)
      if (result === 'failed') {
        state = verification || passed.length ? 'recurred' : 'open'
        failures.push(run.id); verification = null; observations = 0
      } else if (result === 'passed') {
        passed.push(run.id)
        const qualified = (!issue.historyTruncated || run.closed?.includes(issue.id)) && run.mode === 'full' && run.state === 'completed' && run.scope.length === 60
        if (qualified && (comparable(origin, run) || run.verifiedSourcePairs?.includes(issue.id)) && run.verified.includes(issue.id)) {
          if (!verification) { verification = run; observations = 0; lastVerificationRun = run.id }
          else if (comparable(verification, run)) observations += 1
          state = run.closed ? run.closed.includes(issue.id) ? 'closed' : 'observing' : observations >= 2 ? 'closed' : 'observing'
        } else if (!verification && state !== 'recurred') state = 'unverified'
      }
    }
    return { issue, state, coverage: comparable(origin, past[past.length - 1]) || issue.cases.every(id => !!origin.caseHashes?.[id] && origin.caseHashes[id] === past[past.length - 1].caseHashes?.[id]) ? issueCoverage(issue, past[past.length - 1]) : 'incomparable', failures, signalRuns, seen, passed, observations, verificationRun: verification?.id || null, lastVerificationRun }
  })
}
export function caseCounts(run: RunRecord, ids = run.scope) {
  return ids.reduce((value, id) => { value[run.results[id] || 'not_run'] += 1; return value }, { passed: 0, failed: 0, pending: 0, not_run: 0, running: 0, blocked: 0, unknown: 0, cancelled: 0 })
}
export type IssueChange = 'new' | 'fixed' | 'closed' | 'stable' | 'recurred' | 'remaining' | 'unverified' | 'not_covered'
export function issueChange(current: IssueAssessment, baseline?: IssueAssessment): IssueChange {
  if (current.coverage === 'not_run') return 'not_covered'
  if (current.coverage === 'incomparable') return 'unverified'
  if (current.coverage === 'pending' || current.coverage === 'running' || current.coverage === 'blocked' || current.coverage === 'unknown' || current.coverage === 'cancelled') return 'unverified'
  if (current.state === 'unverified') return 'unverified'
  if (!baseline) return current.issue.historyTruncated ? 'unverified' : 'new'
  if (current.state === 'closed' && baseline.state !== 'closed') return 'closed'
  if (current.state === 'observing' || current.state === 'closed') return ['observing', 'closed'].includes(baseline.state) ? 'stable' : 'fixed'
  if (current.state === 'recurred') return 'recurred'
  return 'remaining'
}
export type ResultsViewState = {
  runId: string; baselineId: string; showRuns: boolean; expandedRuns: string[]; showCases: boolean; caseFilter: 'all' | CaseStatus
  issueFilter: 'all' | IssueChange; typeFilter: 'all' | IssueType; priorityFilter: 'all' | Priority
  expandedCases: string[]; expandedIssues: string[]
}
export const initialResultsView: ResultsViewState = { runId: 'R04', baselineId: 'R03', showRuns: false, expandedRuns: [], showCases: false, caseFilter: 'all', issueFilter: 'all', typeFilter: 'all', priorityFilter: 'all', expandedCases: [], expandedIssues: [] }
