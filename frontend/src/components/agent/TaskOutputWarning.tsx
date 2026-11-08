import { useId, useState } from 'react'
import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import type { TaskDetail } from './agent-task-protocol'
import './task-output-warning.css'

type UnavailableOutputs = NonNullable<TaskDetail['delivery']>['unavailable']

export default function TaskOutputWarning({ unavailable }: { unavailable?: UnavailableOutputs }) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const detailsId = useId()
  if (!unavailable?.length) return null

  return <div className="agent-task-note task-output-warning">
    <p role="status">{t('agent.task.outputsUnavailable')}</p>
    <button type="button" className="tt-act task-output-warning-toggle" aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded(!expanded)}><ChevronRight />{t('agent.task.outputDetails')}</button>
    <ul id={detailsId} className="task-output-warning-list" hidden={!expanded}>{unavailable.map((item, index) => <li key={item.runId + ':' + item.sourcePath + ':' + index}><code>{item.sourcePath}</code></li>)}</ul>
  </div>
}
