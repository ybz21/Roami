import { useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import type { AgentQuestion as Question } from './agent-protocol'

export default function AgentQuestion({ question, disabled, answer }: { question: Question; disabled: boolean; answer?: (text: string) => Promise<boolean> }) {
  const { t } = useI18n(), [selected, setSelected] = useState(''), [busy, setBusy] = useState(false), clicked = useRef(false)
  return <section className="agent-question" aria-label={t('agent.question.options')}>
    <p>{question.prompt}</p>
    {question.options.map(option => <button key={option.label} type="button" className="agent-question-option" disabled={disabled || busy || !!selected || !answer} onClick={async () => {
      if (clicked.current || disabled || !answer) return
      clicked.current = true; setBusy(true)
      try { if (await answer(option.label)) setSelected(option.label) }
      finally { clicked.current = false; setBusy(false) }
    }}><span>{option.label}</span>{option.description && <small>{option.description}</small>}</button>)}
  </section>
}
