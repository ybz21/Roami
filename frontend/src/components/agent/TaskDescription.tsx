import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'

export default function TaskDescription({ content, title = true }: { content: string; title?: boolean }) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false), [overflowing, setOverflowing] = useState(false)
  const text = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    const element = text.current
    if (!element) return
    const measure = () => { if (!expanded) setOverflowing(element.scrollHeight > element.clientHeight + 1) }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [content, expanded])
  return <section className={title ? 'agent-task-section' : 'agent-collapsed-message'}>{title && <h4>{t('agent.task.description')}</h4>}<p ref={text} className={'agent-task-description' + (expanded ? '' : ' clipped')}>{content || t('agent.task.noDetails')}</p>{(overflowing || expanded) && <button type="button" className="tt-act agent-task-disclosure" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{t(expanded ? 'agent.task.collapseContent' : 'agent.task.expandContent')}</button>}</section>
}
