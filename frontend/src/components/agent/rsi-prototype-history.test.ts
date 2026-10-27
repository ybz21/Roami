import { describe, expect, it } from 'vitest'
import { assessIssues, caseCounts, cases, comparable, history, issueChange, scenarioRuns } from '../../../prototypes/rsi-run-history'

const at = (id: string, issue: string, runs = history) => assessIssues(runs, id).find(value => value.issue.id === issue)!
describe('RSI result prototype history', () => {
  it('keeps the 20/20/20 case composition and derives totals from individual results', () => {
    for (const group of ['authored', 'public', 'mechanism']) expect(cases.filter(c => c.group === group)).toHaveLength(20)
    expect(caseCounts(history[0])).toEqual({ passed: 55, failed: 5, pending: 0, not_run: 0, running: 0, blocked: 0, unknown: 0, cancelled: 0 })
    expect(caseCounts(history[3]).passed).toBe(57)
  })
  it('does not leak later failures or verifications into an earlier run', () => {
    expect(at('R02', 'RSI-001').verificationRun).toBeNull()
    expect(at('R02', 'RSI-002').failures).toEqual(['R01'])
    expect(at('R02', 'RSI-002').state).toBe('observing')
  })
  it('closes only after two later complete comparable observations', () => {
    expect(at('R03', 'RSI-004')).toMatchObject({ state: 'observing', observations: 1 })
    expect(at('R04', 'RSI-004')).toMatchObject({ state: 'closed', observations: 2 })
    expect(at('R04', 'RSI-001')).toMatchObject({ state: 'observing', observations: 1 })
  })
  it('reopens verified repairs when the same issue fails again', () => {
    expect(at('R04', 'RSI-002')).toMatchObject({ state: 'recurred', failures: ['R01', 'R04'], observations: 0, verificationRun: null, lastVerificationRun: 'R02' })
    expect(at('R04', 'RSI-003').failures).toEqual(['R01', 'R02', 'R04'])
  })
  it('distinguishes new repairs, continuing passes, recurrence and leftovers', () => {
    expect(issueChange(at('R02', 'RSI-002'), at('R01', 'RSI-002'))).toBe('fixed')
    expect(issueChange(at('R04', 'RSI-001'), at('R03', 'RSI-001'))).toBe('stable')
    expect(issueChange(at('R04', 'RSI-002'), at('R03', 'RSI-002'))).toBe('recurred')
    expect(issueChange(at('R04', 'RSI-004'), at('R03', 'RSI-004'))).toBe('closed')
    expect(issueChange(at('R04', 'RSI-005'), at('R03', 'RSI-005'))).toBe('remaining')
  })
  it('does not treat uncovered quick-check cases as repaired', () => {
    expect(issueChange(at('R05', 'RSI-002'), at('R04', 'RSI-002'))).toBe('not_covered')
    expect(at('R05', 'RSI-002').state).toBe('recurred')
    expect(at('R05', 'RSI-005').coverage).toBe('pending')
    expect(issueChange(at('R05', 'RSI-005'), at('R04', 'RSI-005'))).toBe('unverified')
    expect(at('R05', 'RSI-001').observations).toBe(1)
  })
  it('keeps features separate from fix assertions and case failure totals', () => {
    expect(at('R04', 'RSI-006')).toMatchObject({ state: 'planned', failures: [], verificationRun: null })
    expect(at('R04', 'RSI-006').issue.type).toBe('feature')
    expect(assessIssues(history, 'R01')).toHaveLength(5)
  })
  it('requires a verification receipt rather than a passing case alone', () => {
    const runs = history.map(run => ({ ...run, verified: [] }))
    expect(at('R02', 'RSI-004', runs)).toMatchObject({ state: 'unverified', verificationRun: null, observations: 0 })
  })
  it('does not count an incomplete full run as an observation', () => {
    const runs = history.map(run => run.id === 'R03' ? { ...run, state: 'partial' as const } : run)
    expect(at('R04', 'RSI-004', runs)).toMatchObject({ state: 'observing', observations: 1 })
  })
  it('separates incompatible graders instead of declaring fixes across them', () => {
    const runs = history.map(run => run.id === 'R04' ? { ...run, judge: 'demo-judge-v2' } : run)
    expect(comparable(runs[2], runs[3])).toBe(false)
    expect(at('R04', 'RSI-002', runs)).toMatchObject({ state: 'observing', coverage: 'incomparable', failures: ['R01'] })
  })
  it('preserves recorded outcomes when switching demonstration scenes', () => {
    const before = JSON.stringify(history)
    expect(caseCounts(scenarioRuns('complete', 0, 'full', false)[3]).passed).toBe(60)
    expect(JSON.stringify(history)).toBe(before)
  })
  it('keeps paused runs incomplete and preserves executed failures', () => {
    const runs = scenarioRuns('limit', 18, 'full', false)
    const run = runs[runs.length - 1]
    expect(run.state).toBe('paused')
    expect(caseCounts(run)).toMatchObject({ failed: 3, not_run: 42 })
    expect(assessIssues([run], run.id)).toEqual([])
  })
})

it('does not auto-verify or close issues when the history window is incomplete', async () => {
  const { assessIssues: assess } = await import('./rsi-history')
  const { issues } = await import('../../../prototypes/rsi-run-history')
  const result = assess(history, 'R04', issues.map(issue => ({ ...issue, historyTruncated: true })))
  expect(result.every(value => !['observing', 'closed'].includes(value.state))).toBe(true)
})
it('uses the recorded signal observation when another problem fails the same case', async () => {
  const { issueCoverage } = await import('./rsi-history')
  const { issues } = await import('../../../prototypes/rsi-run-history')
  expect(issueCoverage(issues[0], { ...history[0], issueObservations: { [issues[0].id]: 'unverified' } })).toBe('pending')
  expect(issueCoverage(issues[0], { ...history[0], issueObservations: { [issues[0].id]: 'not_tested' } })).toBe('not_run')
})
it('keeps live issues observing until the host supplies a closure receipt', () => {
  const runs = history.map(run => ({ ...run, closed: [] as string[] }))
  expect(at('R04', 'RSI-004', runs).state).toBe('observing')
  runs[3].closed = ['RSI-004']
  expect(at('R04', 'RSI-004', runs).state).toBe('closed')
})
