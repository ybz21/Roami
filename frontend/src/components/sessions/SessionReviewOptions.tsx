import { useId, useState } from 'react'
import { Dropdown } from 'antd'
import type { AgentDefinition } from '../../agent-registry'
import { agentLaunch } from '../../agent-command'
import type { Preferences } from '../../preferences'
import { AgentLogo, ChevronDown } from '../../icons'
import { useI18n } from '../../i18n'
import type { ReviewIntent } from './session-lifecycle'
import './session-review.css'

export function useReviewDraft(author: string, agents: AgentDefinition[], eligible: boolean) {
  const [enabled, setEnabled] = useState(false)
  const [choice, setChoice] = useState('')
  const [trigger, setTrigger] = useState<ReviewIntent['trigger']>('submit')
  const suggested = agents.find(item => item.kind === (author === 'codex' ? 'claude' : 'codex'))
    || agents.find(item => item.kind !== author) || agents[0]
  const selected = agents.find(item => item.kind === choice) || suggested
  const available = eligible && author !== 'none' && author !== 'native' && !!selected
  const open = available && enabled
  return {
    agents, available, open, selected, trigger, setTrigger, setChoice,
    toggle: () => setEnabled(value => !value),
    reset: () => { setEnabled(false); setChoice(''); setTrigger('submit') },
    intent: (prefs: Preferences): ReviewIntent | undefined => open && selected
      ? { agent: selected.kind, command: agentLaunch(selected.kind, prefs, undefined, selected.command), trigger }
      : undefined,
  }
}

type ReviewDraft = ReturnType<typeof useReviewDraft>

export function useSessionReviewControls(draft: ReviewDraft) {
  const id = useId()
  const { t } = useI18n()
  const triggerLabel = (value: ReviewIntent['trigger']) => t(value === 'idle' ? 'session.review.idle' : 'session.review.submit')
  return {
    toggle: draft.available && <button type="button" className={`tt-pill tt-review-toggle${draft.open ? ' on' : ''}`} aria-expanded={draft.open} aria-controls={id} onClick={draft.toggle}>
      {t('session.review.toggle')}<ChevronDown />
    </button>,
    row: <div id={id} className="tt-review-row" hidden={!draft.open}>
      <div className="tt-review-agents" role="group" aria-labelledby={id + '-label'}>
        <strong id={id + '-label'}>{t('session.review.reviewer')}</strong>
        {draft.agents.map(item => <button key={item.kind} type="button" className={`tt-pill ico${draft.selected?.kind === item.kind ? ' on' : ''}`}
          title={item.displayName} aria-label={item.displayName} aria-pressed={draft.selected?.kind === item.kind} onClick={() => draft.setChoice(item.kind)}>
          <AgentLogo kind={item.kind} size={16} />
        </button>)}
      </div>
      <Dropdown trigger={['click']} menu={{ selectedKeys: [draft.trigger], selectable: true,
        items: (['submit', 'idle'] as const).map(key => ({ key, label: triggerLabel(key), onClick: () => draft.setTrigger(key) })),
      }}>
        <button type="button" className="tt-pill sel tt-review-trigger" aria-haspopup="menu" title={t('session.review.trigger')}>
          {triggerLabel(draft.trigger)}<ChevronDown size={10} />
        </button>
      </Dropdown>
    </div>,
  }
}
