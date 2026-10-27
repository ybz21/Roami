import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { ChevronRight, FileTextIcon } from '../../icons'

const stages = ['evaluate', 'review', 'issue', 'repair', 'verify', 'publish', 'observe'] as const
export type WorkflowStage = typeof stages[number]
type Stage = WorkflowStage
export type StageState = 'done' | 'active' | 'pending' | 'blocked' | 'waiting' | 'failed' | 'skipped'
export type WorkflowSnapshot = { id: string; runId?: string; source: string; suite: string; judge: string; phases: Record<Stage, { state: StageState; summary: string; produced: boolean; error?: string | null; artifacts?: { id: string; name: string }[] }> }
export type WorkflowArtifact = { name: string; text?: string; artifactId?: string; runId?: string }
const filenames: Record<Stage, string> = {
  evaluate: 'evaluation-report.md', review: 'review-notes.md', issue: 'issue-summary.md',
  repair: 'repair-log.md', verify: 'verification-report.md', publish: 'pull-request-draft.md', observe: 'observation-log.md',
}

export default function RsiWorkflow({ scenario, total, progress, idPrefix, onArtifact, selectedStage, onStage, snapshot }: {
  scenario: string; total: number; progress: number; idPrefix: string
  onArtifact: (artifact: WorkflowArtifact) => void
  selectedStage: Stage | null; onStage: (stage: Stage) => void; snapshot?: WorkflowSnapshot
}) {
  const { t } = useI18n(), { phone } = useLayout()
  const initialStage: Stage = scenario === 'repairing' ? 'repair' : scenario === 'complete' ? 'publish' : 'evaluate'
  const selected = selectedStage ?? (snapshot ? stages.find(stage => snapshot.phases[stage].state === 'active' || snapshot.phases[stage].state === 'failed' || snapshot.phases[stage].state === 'pending') || 'evaluate' : initialStage)

  const phase = (stage: Stage) => {
    const index = stages.indexOf(stage)
    let state: StageState = 'waiting'
    if (scenario === 'complete') state = index < 5 ? 'done' : index === 5 ? 'active' : 'waiting'
    else if (scenario === 'repairing') state = index < 3 ? 'done' : index === 3 ? 'active' : 'waiting'
    else if (index === 0) state = scenario === 'running' ? 'active' : ['limit', 'unknown'].includes(scenario) ? 'blocked' : total === 10 ? 'done' : 'pending'
    if (snapshot) state = snapshot.phases[stage].state
    const group = state === 'done' ? 'done' : state === 'active' ? 'running' : 'waiting'
    let summary = stage === 'evaluate'
      ? state === 'blocked' ? 'blocked' : state === 'pending' ? 'pending' : group
      : stage === 'review' || stage === 'issue'
        ? state === 'done' && scenario === 'complete' ? 'clean' : group
        : group
    if (stage === 'publish' && summary === 'running') summary = 'done'
    const stateLabel = state === 'skipped' ? 'skipped' : state === 'failed' ? 'failed' : state === 'done' ? 'completed' : state === 'pending' ? 'pendingScore' : state === 'blocked' ? 'paused' : state === 'active' ? stage === 'publish' ? 'awaitingReview' : stage === 'repair' ? 'repairing' : stage === 'observe' ? 'observe' : 'running' : 'queued'
    return {
      state, stateLabel,
      summary: snapshot?.phases[stage].summary ?? t('agent.rsiPrototype.flow.' + stage + '.' + summary, { total, count: progress }),
      hasOutput: snapshot ? snapshot.phases[stage].produced : state === 'done' || state === 'active' || stage === 'evaluate' && state === 'pending',
    }
  }
  const panel = () => {
    const value = phase(selected)
    return <div className="rsi-phase-detail" id={idPrefix + '-phase'} role="region" aria-labelledby={idPrefix + '-' + selected}>
      {!phone && <div className="rsi-section-heading"><h4>{t('agent.rsiPrototype.stage.' + selected)}</h4><span className="rsi-status" data-stage-state={value.state}>{t('agent.rsiPrototype.flow.' + value.stateLabel)}</span></div>}
      {!phone && <p className="rsi-phase-conclusion">{value.summary}</p>}
      <dl className="rsi-phase-facts"><div><dt>{t('agent.rsiPrototype.flow.actor')}</dt><dd>{t('agent.rsiPrototype.flow.actor.' + selected)}</dd></div><div><dt>{t('agent.rsiPrototype.flow.input')}</dt><dd>{t('agent.rsiPrototype.flow.' + selected + '.input')}</dd></div></dl>
      <h4>{t('agent.rsiPrototype.' + (['waiting', 'skipped'].includes(value.state) ? 'flow.plan' : 'flow.work'))}</h4><p>{t('agent.rsiPrototype.flow.' + selected + '.action')}</p>
      <h4>{t('agent.rsiPrototype.flow.outputs')}</h4>{snapshot?.phases[selected].artifacts ? snapshot.phases[selected].artifacts!.length ? snapshot.phases[selected].artifacts!.map(artifact => <button type="button" className="rsi-phase-output" key={artifact.id} onClick={() => onArtifact({ name: artifact.name, artifactId: artifact.id, runId: snapshot.runId })}><FileTextIcon size={17} /><span>{artifact.name}</span><ChevronRight size={15} /></button>) : <p className="rsi-muted">{t('agent.rsiPrototype.flow.noOutputs')}</p> : value.hasOutput ? <button type="button" className="rsi-phase-output" onClick={() => onArtifact({ name: (snapshot ? snapshot.id + '-' : '') + filenames[selected], text: [snapshot ? [snapshot.id, snapshot.source, snapshot.suite, snapshot.judge].join(' / ') : '', t('agent.rsiPrototype.stage.' + selected), value.summary, t('agent.rsiPrototype.flow.' + selected + '.action'), t('agent.rsiPrototype.flow.recordsHint')].join('\n\n') })}><FileTextIcon size={17} /><span>{snapshot ? snapshot.id + '-' : ''}{filenames[selected]}</span><ChevronRight size={15} /></button> : <p className="rsi-muted">{t('agent.rsiPrototype.flow.noOutputs')}</p>}
      <h4>{t('agent.rsiPrototype.flow.next')}</h4><p>{t(value.state === 'skipped' ? 'agent.rsiPrototype.flow.skippedNext' : 'agent.rsiPrototype.flow.' + selected + '.next')}</p>
      <details className="rsi-disclosure"><summary>{t('agent.rsiPrototype.flow.records')}<ChevronRight size={15} /></summary><p className="rsi-footnote">{t('agent.rsiPrototype.flow.recordsHint')}</p><p className="rsi-footnote">{value.summary}</p>{snapshot?.phases[selected].error && <code>{snapshot.phases[selected].error}</code>}</details>
    </div>
  }
  return <section className="rsi-section rsi-workflow" aria-label={t('agent.rsiPrototype.flow.title')}>
    <div className="rsi-section-heading"><h3>{t('agent.rsiPrototype.flow.title')}</h3><span className="rsi-footnote">{snapshot ? snapshot.id : t('agent.rsiPrototype.flow.context')}</span></div>
    <div className="rsi-workflow-layout">
      <ol className="rsi-workflow-stages">{stages.map((stage, index) => {
        const value = phase(stage)
        return <li key={stage} data-stage-state={value.state}>
          <button type="button" id={idPrefix + '-' + stage} className="rsi-phase-button" aria-pressed={selected === stage} aria-expanded={phone ? selected === stage : undefined} aria-controls={selected === stage ? idPrefix + '-phase' : undefined} onClick={() => onStage(stage)}>
            <span className="rsi-phase-number">{index + 1}</span><span className="rsi-phase-copy"><span><strong>{t('agent.rsiPrototype.stage.' + stage)}</strong><small>{t('agent.rsiPrototype.flow.' + value.stateLabel)}</small></span><span>{value.summary}</span></span><ChevronRight size={15} />
          </button>
          {phone && selected === stage && panel()}
        </li>
      })}</ol>
      {!phone && panel()}
    </div>
  </section>
}
