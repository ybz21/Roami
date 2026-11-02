import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Modal, Spin } from 'antd'
import { ArchiveIcon, CheckIcon, CodeIcon, FileTextIcon, FolderIcon, GearIcon, PaperclipIcon, PlusIcon } from '../../icons'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import AgentModelPicker from './AgentModelPicker'
import AgentContextUsage from './AgentContextUsage'
import type { useAgentModels } from './useAgentModels'

type SkillChoice = { name: string; description?: string; enabled: boolean }

export default function AgentComposerPlus({ models, disabled, canCompact, onFiles, onCompact, onCommands, onSkill, onTask, canDelegate = false, node = null, modelTrigger = false, contextUsage, onContext, mode, options }: {
  mode?: { task: boolean; onChange: (task: boolean) => void }; options?: ReactNode
  contextUsage?: { cid: string; model: string; revision: string; active: boolean }; onContext?: () => void
  models: ReturnType<typeof useAgentModels>; disabled: boolean; canCompact: boolean
  onFiles: () => void; onCompact: () => void; onCommands: () => void; modelTrigger?: boolean
  onSkill?: (name: string) => void; onTask?: () => void; canDelegate?: boolean; node?: string | null
}) {
  const { t } = useI18n(), [open, setOpen] = useState(false)
  const [skills, setSkills] = useState<SkillChoice[]>([]), [skillsLoading, setSkillsLoading] = useState(false), [skillsFailed, setSkillsFailed] = useState(false), [skillsVersion, setSkillsVersion] = useState(0)
  const showSkills = !!onSkill
  const trigger = useRef<HTMLButtonElement>(null), [geometry, setGeometry] = useState<{ left: number; width: number; bottom: number; height: number }>()
  const measure = useCallback(() => {
    if (!trigger.current) return
    const gap = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sp-4')) || 0
    const card = trigger.current.closest('.agent-compose-card')?.getBoundingClientRect()
    if (!card) return
    const viewport = window.visualViewport
    const top = viewport?.offsetTop || 0
    setGeometry({ left: card.left, width: card.width, bottom: document.documentElement.clientHeight - card.top + gap, height: Math.max(0, card.top - top - gap * 2) })
  }, [])
  useEffect(() => {
    if (!open) return
    measure()
    const viewport = window.visualViewport
    viewport?.addEventListener('resize', measure)
    window.addEventListener('resize', measure)
    return () => { viewport?.removeEventListener('resize', measure); window.removeEventListener('resize', measure) }
  }, [open, measure])
  useEffect(() => { setOpen(false); setSkills([]) }, [node])
  useEffect(() => {
    if (!open || !showSkills) return
    const abort = new AbortController()
    setSkills([]); setSkillsLoading(true); setSkillsFailed(false)
    void api('GET', '/agent/capability-settings', undefined, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) setSkills(data.skills.filter((skill: SkillChoice) => skill.enabled).map(({ name, description, enabled }: SkillChoice) => ({ name, description, enabled })))
    }).catch(() => { if (!abort.signal.aborted) setSkillsFailed(true) }).finally(() => { if (!abort.signal.aborted) setSkillsLoading(false) })
    return () => abort.abort()
  }, [open, node, showSkills, skillsVersion])
  const close = (action: () => void) => { setOpen(false); action() }
  const row = (label: string, icon: ReactNode, action: () => void, description?: string, blocked = false) => <button key={label} type="button" className="agent-plus-row agent-plus-action" role="menuitem" disabled={blocked} onClick={action}>{icon}<span><strong>{label}</strong>{description && <small>{description}</small>}</span></button>
  const show = () => { measure(); setOpen(true) }
  if (modelTrigger) return <AgentModelPicker models={models} disabled={disabled} node={node} />
  return <>
    <button ref={trigger} type="button" className="tt-pill ico agent-plus-trigger" aria-label={t('agent.composer.more')} disabled={disabled} aria-haspopup="dialog" aria-expanded={open} onClick={show}><PlusIcon size={20} /></button>
    <Modal open={open} onCancel={() => setOpen(false)} footer={null} title={null} closable={false} destroyOnClose maskClosable keyboard width={geometry?.width} className="agent-composer-dialog" wrapClassName="agent-composer-dialog-wrap" style={{ left: geometry?.left, bottom: geometry?.bottom, top: 'auto', margin: 0, padding: 0 }} afterClose={() => trigger.current?.focus({ preventScroll: true })}>
    <div className="agent-plus-menu" style={{ '--agent-menu-available': geometry ? geometry.height + 'px' : undefined } as CSSProperties} role="menu" aria-label={t('agent.composer.more')}>
      {mode && <><p className="agent-menu-section">{t('agent.composer.mode')}</p><div className="agent-plus-modes">{[false, true].map(task => <button type="button" key={String(task)} role="menuitemradio" aria-checked={mode.task === task} disabled={task && !canDelegate} onClick={() => mode.onChange(task)}><span>{t(task ? 'agent.composer.taskMode' : 'agent.composer.chatMode')}</span>{mode.task === task && <CheckIcon size={16} />}</button>)}</div>{mode.task && <div className="conversation-composer-options">{options}</div>}<div className="agent-menu-divider" /></>}
      {contextUsage?.cid && onContext && <><AgentContextUsage {...contextUsage} node={node} menuItem onOpen={() => close(onContext)} />{row(t('agent.compactNow'), <ArchiveIcon size={20} />, () => close(onCompact), t('agent.composer.compactHint'), !canCompact)}<div className="agent-menu-divider" /></>}
      <p className="agent-menu-section">{t('agent.composer.addSection')}</p>
      {row(t('agent.composer.addFiles'), <PaperclipIcon size={20} />, () => close(onFiles), t('agent.composer.filesHint'))}
      {!mode && onTask && row(t('agent.composer.taskMode'), <FolderIcon size={20} />, () => close(onTask), t('agent.composer.taskHint'), !canDelegate)}
      {showSkills && <>
        <p className="agent-menu-section">{t('agent.composer.skillsSection')}</p>
        {skillsLoading && <p className="agent-menu-note" role="status"><Spin size="small" /> {t('agent.composer.skillsLoading')}</p>}
        {skillsFailed ? <div className="agent-menu-note" role="alert">{t('agent.composer.skillsFailed')}<button type="button" className="tt-act" onClick={() => setSkillsVersion(value => value + 1)}>{t('agent.retry')}</button></div> : !skillsLoading && !skills.length && <p className="agent-menu-note">{t('agent.composer.skillsEmpty')}</p>}
        {skills.map(skill => row(skill.name, <FileTextIcon size={20} />, () => close(() => onSkill?.(skill.name)), ['roami', 'browser_use'].includes(skill.name) ? t('agent.capabilities.skillDescription.' + skill.name) : skill.description || t('agent.composer.skillHint')))}
      </>}
      <p className="agent-menu-section">{t('agent.composer.conversationSection')}</p>
      {(!contextUsage?.cid || !onContext) && row(t('agent.compactNow'), <ArchiveIcon size={20} />, () => close(onCompact), t('agent.composer.compactHint'), !canCompact)}
      {row(t('agent.commands'), <CodeIcon size={20} />, () => close(onCommands), t('agent.composer.commandsHint'))}
      {row(t('agent.composer.manageSkills'), <GearIcon size={20} />, () => close(() => { location.hash = '#/capabilities/skills' }), t('agent.composer.manageHint'))}
    </div></Modal>
  </>
}
