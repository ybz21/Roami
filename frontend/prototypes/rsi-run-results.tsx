import { useMemo } from 'react'
import RsiRunResults from '../src/components/agent/RsiRunResults'
import { cases, issues, scenarioRuns } from './rsi-run-history'
import type { ComponentProps } from 'react'
type Props = Omit<ComponentProps<typeof RsiRunResults>, 'runs' | 'cases' | 'issues' | 'demo'> & { mode: string; demoRun: boolean }
export default function PrototypeResults({ mode, demoRun, ...props }: Props) {
  const runs = useMemo(() => scenarioRuns(props.scenario, props.progress, mode, demoRun, props.stopped), [props.scenario, props.progress, mode, demoRun, props.stopped])
  return <RsiRunResults {...props} runs={runs} cases={cases} issues={issues} demo />
}
