import { assessIssues as assess, type CaseDefinition, type CaseStatus, type IssueAssessment, type IssueDefinition, type RunRecord } from '../src/components/agent/rsi-history'
export * from '../src/components/agent/rsi-history'
export const cases: CaseDefinition[] = [
  { id: 'CODE-SUMMARY', title: 'case.summary', group: 'authored' },
  { id: 'QUANT-03', title: 'case.backtest', group: 'authored' },
  { id: 'MEMORY-01', title: 'case.memory', group: 'public' },
  { id: 'BILLING-01', title: 'case.billing', group: 'mechanism' },
  { id: 'DOC-05', title: 'case.report', group: 'authored' },
  ...(['authored', 'public', 'mechanism'] as const).flatMap(group => Array.from({ length: group === 'authored' ? 17 : 19 }, (_, index) => ({ id: group.toUpperCase() + '-' + String(index + 1).padStart(2, '0'), title: 'case.routine', group }))),
]
export const issues: IssueDefinition[] = [
  { id: 'RSI-001', title: 'issue.summary', type: 'fix', priority: 'P1', firstRun: 'R01', cases: ['CODE-SUMMARY'], fingerprint: 'delivery:missing-final-summary', reason: 'reason.summary', acceptance: 'accept.summary' },
  { id: 'RSI-002', title: 'issue.backtest', type: 'fix', priority: 'P1', firstRun: 'R01', cases: ['QUANT-03'], fingerprint: 'backtest:first-trade-offset', reason: 'reason.backtest', acceptance: 'accept.backtest' },
  { id: 'RSI-003', title: 'issue.memory', type: 'fix', priority: 'P1', firstRun: 'R01', cases: ['MEMORY-01'], fingerprint: 'memory:retrieval-incomplete', reason: 'reason.memory', acceptance: 'accept.memory' },
  { id: 'RSI-004', title: 'issue.billing', type: 'fix', priority: 'P0', firstRun: 'R01', cases: ['BILLING-01'], fingerprint: 'billing:unknown-charge-admission', reason: 'reason.billing', acceptance: 'accept.billing' },
  { id: 'RSI-005', title: 'issue.report', type: 'fix', priority: 'P2', firstRun: 'R01', cases: ['DOC-05'], fingerprint: 'report:missing-source-evidence', reason: 'reason.report', acceptance: 'accept.report' },
  { id: 'RSI-006', title: 'issue.coverage', type: 'feature', priority: 'P2', firstRun: 'R02', cases: [], fingerprint: 'coverage:cross-browser-acceptance', reason: 'reason.coverage', acceptance: 'accept.coverage' },
]
const common = { suite: 'demo-suite-v1', judge: 'demo-judge-v1', models: 'demo-model-profile-v1', machine: 'demo-container' }
function full(id: string, time: string, failed: string[], verified: string[]): RunRecord {
  return { ...common, id, time, mode: 'full', state: 'completed', scope: cases.map(c => c.id), results: Object.fromEntries(cases.map(c => [c.id, failed.includes(c.id) ? 'failed' : 'passed'])), verified, source: 'demo-source-' + id }
}
export const history: RunRecord[] = [
  full('R01', '2026-10-24 09:30', cases.slice(0, 5).map(c => c.id), []),
  full('R02', '2026-10-25 09:30', ['CODE-SUMMARY', 'MEMORY-01', 'DOC-05'], ['RSI-002', 'RSI-004']),
  full('R03', '2026-10-26 09:30', ['DOC-05'], ['RSI-001', 'RSI-002', 'RSI-003', 'RSI-004']),
  full('R04', '2026-10-27 09:30', ['QUANT-03', 'MEMORY-01', 'DOC-05'], ['RSI-001', 'RSI-004']),
]
const quickScope = ['CODE-SUMMARY', 'BILLING-01', 'DOC-05', ...cases.filter(c => c.id.startsWith('MECHANISM-')).slice(0, 7).map(c => c.id)]
history.push({ ...common, id: 'R05', time: '2026-10-27 10:30', mode: 'quick', state: 'partial', source: 'demo-source-R04', scope: quickScope, results: Object.fromEntries(quickScope.map(id => [id, id === 'DOC-05' ? 'pending' : 'passed'])), verified: [] })

export function scenarioRuns(scenario: string, progress: number, mode: string, demoRun: boolean, stopped = false): RunRecord[] {
  if (scenario === 'empty') return []
  const runs = history.map(run => ({ ...run, results: { ...run.results }, verified: [...run.verified] }))
  if (scenario === 'complete') {
    const run = runs.find(r => r.id === 'R04')!
    run.results = Object.fromEntries(run.scope.map(id => [id, 'passed']))
    run.verified = issues.filter(issue => issue.type === 'fix').map(issue => issue.id)
  }
  if (demoRun || ['running', 'limit', 'unknown'].includes(scenario)) {
    const scope = mode === 'quick' ? quickScope : history[3].scope
    const partial = stopped || ['running', 'limit', 'unknown'].includes(scenario)
    const results = Object.fromEntries(scope.map((id, index) => [id, partial && index >= progress ? 'not_run' : history[3].results[id]])) as Record<string, CaseStatus>
    runs.push({ ...common, id: 'R06', time: '2026-10-27 11:00', mode: mode === 'quick' ? 'quick' : 'full', state: stopped ? 'interrupted' : scenario === 'running' ? 'running' : ['limit', 'unknown'].includes(scenario) ? 'paused' : 'completed', source: 'demo-source-R04', scope, results, verified: [] })
  }
  return runs
}

export function assessIssues(runs: RunRecord[], runId: string): IssueAssessment[] { return assess(runs, runId, issues) }
