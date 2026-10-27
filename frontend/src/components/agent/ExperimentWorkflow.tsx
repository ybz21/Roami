import { useI18n } from '../../i18n'
import './experiment-workflow.css'

export const EXPERIMENT_STAGES = ['evaluate', 'review', 'issue', 'repair', 'verify', 'publish', 'observe'] as const
export type ExperimentStage = typeof EXPERIMENT_STAGES[number]
export type ExperimentView = 'workflow' | 'runs' | 'issues'

export default function ExperimentWorkflow({ stage, view, onStage, onView, states, tabs = true, caption, stateLabel }: {
  stage: ExperimentStage
  view: ExperimentView
  onStage: (value: ExperimentStage) => void
  onView: (value: ExperimentView) => void
  states: Partial<Record<ExperimentStage, string>>
  tabs?: boolean
  caption?: string
  stateLabel?: (state: string) => string
}) {
  const { t } = useI18n()
  return <>
    {tabs && <div className="agent-experiment-tabs" aria-label={t('agent.experiment.title')}>
      {(['workflow', 'runs', 'issues'] as const).map(value => <button type="button" className="tt-act" key={value} aria-pressed={view === value} onClick={() => onView(value)}>{t('agent.experiment.' + value)}</button>)}
    </div>}
    {view === 'workflow' && <>
      <div className="agent-experiment-caption"><strong>{t('agent.experiment.pipeline')}</strong><span>{caption || t('agent.experiment.daily')}</span></div>
      <ol className={'agent-experiment-flow' + (!tabs ? ' agent-experiment-flow-compact' : '')} aria-label={t('agent.experiment.pipeline')}>
        {EXPERIMENT_STAGES.map((value, index) => <li key={value}>
          <button type="button" className="agent-experiment-node" aria-pressed={stage === value} onClick={() => onStage(value)}>
            <span className="agent-experiment-step">{index + 1}</span>
            <strong>{t('agent.experiment.stage.' + value)}</strong>
            <span>{t('agent.experiment.actor.' + value)}</span>
            <small data-state={states[value] || 'idle'}>{stateLabel ? stateLabel(states[value] || 'pending') : t(states[value] ? 'agent.rsi.state.' + states[value] : 'agent.experiment.idle')}</small>
          </button>
        </li>)}
      </ol>
      {tabs && <p className="agent-rsi-muted">{t('agent.experiment.selectHint')}</p>}
    </>}
  </>
}
