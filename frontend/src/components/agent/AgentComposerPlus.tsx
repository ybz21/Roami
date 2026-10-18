import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Dropdown, Input, Spin } from 'antd'
import { ArchiveIcon, BotIcon, CheckIcon, ChevronLeft, ChevronRight, CodeIcon, GearIcon, PaperclipIcon, PlusIcon, RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { agentSettingsRoute, modelFailure } from './agent-models'
import type { useAgentModels } from './useAgentModels'

export default function AgentComposerPlus({ models, disabled, canCompact, onFiles, onCompact, onCommands }: {
  models: ReturnType<typeof useAgentModels>; disabled: boolean; canCompact: boolean
  onFiles: () => void; onCompact: () => void; onCommands: () => void
}) {
  const { t } = useI18n(), [open, setOpen] = useState(false), [page, setPage] = useState<'tools' | 'models'>('tools'), [query, setQuery] = useState('')
  const trigger = useRef<HTMLButtonElement>(null), [availableHeight, setAvailableHeight] = useState<number>()
  const measure = useCallback(() => {
    if (!trigger.current) return
    const gap = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sp-4')) || 0
    setAvailableHeight(Math.max(0, trigger.current.getBoundingClientRect().top - gap))
  }, [])
  useEffect(() => {
    if (!open) return
    measure()
    const viewport = window.visualViewport
    viewport?.addEventListener('resize', measure)
    window.addEventListener('resize', measure)
    return () => { viewport?.removeEventListener('resize', measure); window.removeEventListener('resize', measure) }
  }, [open, measure])
  const close = (action: () => void) => { setOpen(false); action() }
  const choose = async (name: string) => { if (await models.choose(name)) setOpen(false) }
  const row = (label: string, icon: ReactNode, action: () => void, value?: string, blocked = false) => <button type="button" className="agent-plus-row" role="menuitem" disabled={blocked} onClick={action}>{icon}<span>{label}</span>{value && <small>{value}</small>}</button>
  return <Dropdown trigger={['click']} placement="topLeft" open={open} onOpenChange={value => { if (value) measure(); setOpen(value); if (value) { setPage('tools'); setQuery('') } }} dropdownRender={() => <div className="agent-plus-menu" style={{ '--agent-menu-available': availableHeight === undefined ? undefined : availableHeight + 'px' } as CSSProperties} role="menu" aria-label={t('agent.composer.more')}>
    {page === 'tools' ? <>
      {row(t('agent.composer.addFiles'), <PaperclipIcon size={18} />, () => close(onFiles))}
      <div className="agent-menu-divider" />
      {row(t('agent.composer.model'), <BotIcon size={18} />, () => { setPage('models'); void models.load() }, models.settings?.main.model || t('agent.models.notConfigured'))}
      {row(t('agent.compactNow'), <ArchiveIcon size={18} />, () => close(onCompact), '/compact', !canCompact)}
      {row(t('agent.commands'), <CodeIcon size={18} />, () => close(onCommands))}
      <div className="agent-menu-divider" />
      {row(t('agent.models.settings'), <GearIcon size={18} />, () => close(() => { location.hash = agentSettingsRoute }))}
    </> : <>
      <button type="button" className="agent-plus-row agent-menu-back" onClick={() => setPage('tools')}><ChevronLeft size={16} /><span>{t('agent.composer.model')}</span>{models.loading && <Spin size="small" />}</button>
      <Input aria-label={t('agent.models.search')} placeholder={t('agent.models.search')} value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && query.trim()) void choose(query) }} />
      <div className="agent-model-list">{models.models.filter(name => name.toLowerCase().includes(query.toLowerCase())).map(name => <button type="button" className="agent-plus-row" role="menuitemradio" aria-checked={models.settings?.main.model === name} key={name} disabled={models.busy} onClick={() => { void choose(name) }}><span>{name}</span>{models.settings?.main.model === name && <CheckIcon size={16} />}</button>)}</div>
      {!!query.trim() && row(t('agent.models.use', { name: query.trim() }), <ChevronRight size={16} />, () => { void choose(query) }, undefined, models.busy)}
      {models.error && <p className="agent-menu-error" role="alert">{modelFailure(models.error, t)}</p>}
      {!models.models.length && !models.loading && <p className="agent-menu-note">{t('agent.models.manual')}</p>}
      {row(t('agent.retry'), <RefreshIcon size={16} />, () => { void models.load() }, undefined, models.loading || models.busy)}
    </>}
  </div>}><button ref={trigger} type="button" className="tt-pill ico agent-plus-trigger" aria-label={t('agent.composer.more')} disabled={disabled} aria-haspopup="menu"><PlusIcon size={20} /></button></Dropdown>
}
