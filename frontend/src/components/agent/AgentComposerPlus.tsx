import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Modal, Input, Spin } from 'antd'
import { ArchiveIcon, CheckIcon, ChevronDown, ChevronRight, CodeIcon, FileTextIcon, FolderIcon, GearIcon, PaperclipIcon, PlusIcon, RefreshIcon } from '../../icons'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { agentSettingsRoute, modelFailure, modelLabel } from './agent-models'
import { genericReasoningEfforts, reasoningChoices, reasoningValue } from './agent-reasoning'
import type { useAgentModels } from './useAgentModels'

type SkillChoice = { name: string; description?: string; enabled: boolean }

export default function AgentComposerPlus({ models, disabled, canCompact, onFiles, onCompact, onCommands, onSkill, onTask, canDelegate = false, node = null, modelTrigger = false }: {
  models: ReturnType<typeof useAgentModels>; disabled: boolean; canCompact: boolean
  onFiles: () => void; onCompact: () => void; onCommands: () => void; modelTrigger?: boolean
  onSkill?: (name: string) => void; onTask?: () => void; canDelegate?: boolean; node?: string | null
}) {
  const { t } = useI18n(), [open, setOpen] = useState(false), [page, setPage] = useState<'tools' | 'models'>('tools'), [query, setQuery] = useState('')
  const [skills, setSkills] = useState<SkillChoice[]>([]), [skillsLoading, setSkillsLoading] = useState(false), [skillsFailed, setSkillsFailed] = useState(false), [skillsVersion, setSkillsVersion] = useState(0)
  const [selection, setSelection] = useState<{ model: string; effort: string } | null>(null)
  const effortGroup = useId(), showSkills = !!onSkill
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
    if (!open || page !== 'tools' || !showSkills) return
    const abort = new AbortController()
    setSkills([]); setSkillsLoading(true); setSkillsFailed(false)
    void api('GET', '/agent/capability-settings', undefined, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) setSkills(data.skills.filter((skill: SkillChoice) => skill.enabled).map(({ name, description, enabled }: SkillChoice) => ({ name, description, enabled })))
    }).catch(() => { if (!abort.signal.aborted) setSkillsFailed(true) }).finally(() => { if (!abort.signal.aborted) setSkillsLoading(false) })
    return () => abort.abort()
  }, [open, page, node, showSkills, skillsVersion])
  useEffect(() => {
    if (open && page === 'models' && models.settings && !selection) setSelection({ model: models.settings.main.model, effort: reasoningValue(models.settings.main.reasoningEffort) })
  }, [open, page, models.settings, selection])
  const close = (action: () => void) => { setOpen(false); action() }
  const choose = (name: string) => setSelection(current => ({ model: name, effort: current?.model === name ? current.effort : 'default' }))
  const apply = async () => { if (selection && await models.apply(selection.model, selection.effort)) setOpen(false) }
  const row = (label: string, icon: ReactNode, action: () => void, description?: string, blocked = false) => <button key={label} type="button" className="agent-plus-row agent-plus-action" role="menuitem" disabled={blocked} onClick={action}>{icon}<span><strong>{label}</strong>{description && <small>{description}</small>}</span></button>
  const effort = reasoningValue(models.settings?.main.reasoningEffort)
  const currentModel = models.settings?.main.model || t('agent.models.notConfigured')
  const options = selection?.model === models.settings?.main.model ? reasoningChoices(models.settings?.main) : ['default', ...(models.efforts[selection?.model || ''] || genericReasoningEfforts)]
  useEffect(() => { if (selection && !options.includes(selection.effort)) setSelection(current => current ? { ...current, effort: 'default' } : current) }, [selection, models.efforts, models.settings])
  const changed = selection && (selection.model !== models.settings?.main.model || selection.effort !== effort)
  const show = () => { measure(); setSelection(models.settings ? { model: models.settings.main.model, effort } : null); setOpen(true); setPage(modelTrigger ? 'models' : 'tools'); setQuery(''); if (modelTrigger) void models.load() }
  return <>
    <button ref={trigger} type="button" className={modelTrigger ? "tt-pill agent-model-trigger" : "tt-pill ico agent-plus-trigger"} aria-label={modelTrigger ? t('agent.reasoning.trigger', { name: currentModel, effort: t('agent.reasoning.' + effort) }) : t('agent.composer.more')} disabled={disabled} aria-haspopup="dialog" aria-expanded={open} onClick={show}>{modelTrigger ? <><span>{modelLabel(models.settings?.main.model || t('agent.composer.model'))}</span>{models.settings && <small className="agent-reasoning-label">{t('agent.reasoning.' + effort)}</small>}<ChevronDown size={14} /></> : <PlusIcon size={20} />}</button>
    <Modal open={open} onCancel={() => setOpen(false)} footer={null} title={null} closable={false} destroyOnClose maskClosable keyboard width={geometry?.width} className="agent-composer-dialog" wrapClassName="agent-composer-dialog-wrap" style={{ left: geometry?.left, bottom: geometry?.bottom, top: 'auto', margin: 0, padding: 0 }} afterClose={() => trigger.current?.focus({ preventScroll: true })}>
    <div className="agent-plus-menu" style={{ '--agent-menu-available': geometry ? geometry.height + 'px' : undefined } as CSSProperties} role="menu" aria-label={t(page === 'models' ? 'agent.composer.model' : 'agent.composer.more')}>
    {page === 'tools' ? <>
      <p className="agent-menu-section">{t('agent.composer.addSection')}</p>
      {row(t('agent.composer.addFiles'), <PaperclipIcon size={20} />, () => close(onFiles), t('agent.composer.filesHint'))}
      {onTask && row(t('agent.composer.taskMode'), <FolderIcon size={20} />, () => close(onTask), t('agent.composer.taskHint'), !canDelegate)}
      {showSkills && <>
        <p className="agent-menu-section">{t('agent.composer.skillsSection')}</p>
        {skillsLoading && <p className="agent-menu-note" role="status"><Spin size="small" /> {t('agent.composer.skillsLoading')}</p>}
        {skillsFailed ? <div className="agent-menu-note" role="alert">{t('agent.composer.skillsFailed')}<button type="button" className="tt-act" onClick={() => setSkillsVersion(value => value + 1)}>{t('agent.retry')}</button></div> : !skillsLoading && !skills.length && <p className="agent-menu-note">{t('agent.composer.skillsEmpty')}</p>}
        {skills.map(skill => row(skill.name, <FileTextIcon size={20} />, () => close(() => onSkill?.(skill.name)), ['roami-dispatch', 'web-research'].includes(skill.name) ? t('agent.capabilities.skillDescription.' + skill.name) : skill.description || t('agent.composer.skillHint')))}
      </>}
      <p className="agent-menu-section">{t('agent.composer.conversationSection')}</p>
      {row(t('agent.compactNow'), <ArchiveIcon size={20} />, () => close(onCompact), t('agent.composer.compactHint'), !canCompact)}
      {row(t('agent.commands'), <CodeIcon size={20} />, () => close(onCommands), t('agent.composer.commandsHint'))}
      {row(t('agent.composer.manageSkills'), <GearIcon size={20} />, () => close(() => { location.hash = '#/settings/agent/skills' }), t('agent.composer.manageHint'))}
    </> : <>
      <div className="agent-model-current"><small>{t('agent.composer.modelSelection')}</small><code>{selection?.model || currentModel}</code></div>
      <fieldset className="agent-effort-options" disabled={models.busy || !selection}><legend>{t('agent.reasoning.title')}</legend><div>{options.map(value => <label key={value} data-checked={selection?.effort === value}><input type="radio" name={effortGroup} checked={selection?.effort === value} value={value} onChange={() => setSelection(current => current ? { ...current, effort: value } : current)} />{t('agent.reasoning.' + value)}</label>)}</div></fieldset>
      <div className="agent-menu-divider" />
      <Input aria-label={t('agent.models.search')} placeholder={t('agent.models.search')} value={query} onChange={e => setQuery(e.target.value)} disabled={models.busy} onKeyDown={e => { if (e.key === 'Enter' && query.trim()) choose(query.trim()) }} />
      <div className="agent-model-list">{models.models.filter(name => name.toLowerCase().includes(query.toLowerCase())).map(name => <button type="button" className="agent-plus-row" role="menuitemradio" aria-checked={selection?.model === name} aria-label={name} title={name} key={name} disabled={models.busy} onClick={() => choose(name)}><span>{modelLabel(name)}</span>{selection?.model === name && <CheckIcon size={16} />}</button>)}</div>
      {!!query.trim() && !models.models.includes(query.trim()) && row(t('agent.models.use', { name: query.trim() }), <ChevronRight size={16} />, () => choose(query.trim()), undefined, models.busy)}
      {models.error && <p className="agent-menu-error" role="alert">{modelFailure(models.error, t)}</p>}
      {!models.models.length && !models.loading && <p className="agent-menu-note">{t('agent.models.manual')}</p>}
      {models.loading && <p className="agent-menu-note" role="status"><Spin size="small" /></p>}
      <div className="agent-model-footer"><button type="button" className="tt-act" aria-label={t('agent.retry')} disabled={models.loading || models.busy} onClick={() => { void models.load() }}><RefreshIcon size={16} /></button><button type="button" className="tt-act" onClick={() => close(() => { location.hash = agentSettingsRoute })}>{t('agent.models.settings')}</button><span /><button type="button" className="tt-act" disabled={models.busy} onClick={() => setOpen(false)}>{t('common.cancel')}</button><button type="button" className="tt-act ok" disabled={models.busy || !changed} onClick={() => { void apply() }}>{models.busy ? <Spin size="small" /> : t('agent.composer.applyModel')}</button></div>
    </>}
    </div></Modal>
  </>
}
