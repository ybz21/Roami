import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { Input, Modal, Spin, type InputRef } from 'antd'
import { CheckIcon, ChevronDown, CloseIcon, GearIcon, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import MobileSubPage from '../MobileSubPage'
import { useBackDismiss } from '../shell/useBackDismiss'
import { agentSettingsRoute, modelFailure } from './agent-models'
import { reasoningChoices, reasoningValue } from './agent-reasoning'
import type { useAgentModels } from './useAgentModels'
import './agent-model-picker.css'

type Panel = 'model' | 'reasoning'
type Choice = { model: string; effort: string }

export default function AgentModelPicker({ models, disabled, node }: {
  models: ReturnType<typeof useAgentModels>; disabled: boolean; node: string | null
}) {
  const { t } = useI18n(), { phone } = useLayout()
  const [open, setOpen] = useState<Panel | null>(null), [query, setQuery] = useState('')
  const [pending, setPending] = useState<Choice | null>(null)
  const [geometry, setGeometry] = useState<{ left: number; bottom: number; width: number; height: number }>()
  const modelTrigger = useRef<HTMLButtonElement>(null), effortTrigger = useRef<HTMLButtonElement>(null)
  const search = useRef<InputRef>(null), returnFocus = useRef<HTMLButtonElement | null>(null)
  const retry = useRef<Choice | null>(null), saving = useRef(false), saveSequence = useRef(0)
  const roleKey = models.role || 'main', role = models.settings?.[roleKey], model = role?.model || '', effort = reasoningValue(role?.reasoningEffort)
  const options = reasoningChoices(role)
  const close = () => setOpen(null)
  useBackDismiss(phone && open === 'reasoning', close)
  useEffect(() => { close(); retry.current = null; saving.current = false; saveSequence.current++; setPending(null) }, [node])
  useEffect(() => {
    if (open) return
    returnFocus.current?.focus({ preventScroll: true })
  }, [open])
  useEffect(() => {
    if (!open || (phone && open === 'model')) return
    const measure = () => {
      const button = returnFocus.current, card = button?.closest('.agent-compose-card')
      if (!button || !card) return
      const gap = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sp-4')) || 0
      const width = Math.min(gap * 24, document.documentElement.clientWidth - gap * 2)
      const top = card.getBoundingClientRect().top
      setGeometry({ width, left: Math.max(gap, Math.min(button.getBoundingClientRect().right - width, document.documentElement.clientWidth - width - gap)), bottom: document.documentElement.clientHeight - top + gap, height: Math.max(0, top - (window.visualViewport?.offsetTop || 0) - gap * 2) })
    }
    measure(); window.addEventListener('resize', measure); window.visualViewport?.addEventListener('resize', measure)
    return () => { window.removeEventListener('resize', measure); window.visualViewport?.removeEventListener('resize', measure) }
  }, [open, phone])
  const show = (panel: Panel) => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    returnFocus.current = (panel === 'model' ? modelTrigger : effortTrigger).current
    retry.current = null; models.clearError(); setPending(null); setQuery(''); setOpen(panel)
    if (panel === 'model') void models.load()
  }
  const choose = async (choice: Choice) => {
    if (saving.current || models.busy) return
    if (choice.model === model && choice.effort === effort) { close(); return }
    const sequence = ++saveSequence.current
    saving.current = true; retry.current = choice; setPending(choice)
    try { if (await models.apply(choice.model, choice.effort) && sequence === saveSequence.current) close() }
    finally { if (sequence === saveSequence.current) { saving.current = false; setPending(null) } }
  }
  const chooseModel = (name: string) => { void choose({ model: name, effort: name === model ? effort : 'default' }) }
  const settings = () => { if (!phone) close(); location.hash = agentSettingsRoute }
  const names = [...new Set([model, ...models.models].filter(Boolean))].filter(name => name.toLowerCase().includes(query.trim().toLowerCase()))
  const title = t(open === 'reasoning' ? 'agent.reasoning.title' : 'agent.composer.model')
  const move = (event: KeyboardEvent<HTMLElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')]
    if (!buttons.length) return
    event.preventDefault()
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length].focus()
  }
  const content = <div className="agent-model-picker-body" aria-busy={models.busy}>
    <p className="agent-menu-note">{t(roleKey === 'worker' ? 'composer.nativeModelHint' : 'composer.mainModelHint')}</p>
    {open === 'model' && <Input ref={search} allowClear prefix={<SearchIcon size={16} />} aria-label={t('agent.models.search')} placeholder={t('agent.models.search')} value={query} disabled={models.busy}
      onChange={event => setQuery(event.target.value)} onKeyDown={event => {
        if (event.key === 'Enter' && (names.length || query.trim())) { event.preventDefault(); chooseModel(names[0] || query.trim()) }
        if (event.key === 'ArrowDown') { event.preventDefault(); event.currentTarget.closest('.agent-model-picker-body')?.querySelector<HTMLButtonElement>('[role="option"]')?.focus() }
      }} />}
    {models.error && <div className="agent-model-picker-error" role="alert"><span>{modelFailure(models.error, t)}</span><button type="button" className="tt-act" disabled={models.busy || models.loading} onClick={() => { if (retry.current) void choose(retry.current); else void models.load() }}>{t('agent.retry')}</button></div>}
    {open === 'model' && models.loading && <div className="agent-model-picker-loading" role="status" aria-label={t('common.loading')}><Spin size="small" /></div>}
    <div className="agent-model-picker-list" role={open === 'model' ? 'listbox' : 'menu'} aria-label={title} onKeyDown={move}>
      {open === 'model' ? <>
        {names.map(name => <button type="button" role="option" aria-selected={name === model} key={name} disabled={models.busy || !role} onClick={() => chooseModel(name)}>
          <span>{name}</span>{pending?.model === name ? <Spin size="small" /> : name === model && <CheckIcon size={18} />}
        </button>)}
        {!names.length && !!query.trim() && <button type="button" role="option" aria-selected={false} disabled={models.busy || !role} onClick={() => chooseModel(query.trim())}><span>{t('agent.models.use', { name: query.trim() })}</span>{pending && <Spin size="small" />}</button>}
        {!names.length && !query.trim() && !models.loading && !models.error && <p className="agent-menu-note">{t('agent.models.manual')}</p>}
      </> : options.map(value => <button type="button" role="menuitemradio" aria-checked={effort === value} key={value} disabled={models.busy || !role} onClick={() => { void choose({ model, effort: value }) }}>
        <span>{t('agent.reasoning.' + value)}</span>{pending?.effort === value ? <Spin size="small" /> : effort === value && <CheckIcon size={18} />}
      </button>)}
    </div>
  </div>
  return <>
    <button type="button" ref={modelTrigger} className="tt-pill agent-model-trigger" disabled={disabled || models.busy} aria-label={t('agent.models.trigger', { name: model || t('agent.models.notConfigured') })} aria-haspopup="dialog" aria-expanded={open === 'model'} onClick={() => show('model')}><span>{model || t('agent.composer.model')}</span><ChevronDown size={14} /></button>
    {role && options.length > 1 && <button type="button" ref={effortTrigger} className="tt-pill agent-thinking-trigger" disabled={disabled || models.busy} aria-label={t('agent.reasoning.picker', { effort: t('agent.reasoning.' + effort) })} aria-haspopup="dialog" aria-expanded={open === 'reasoning'} onClick={() => show('reasoning')}><span>{t('composer.effort.' + effort)}</span></button>}
    {phone && open === 'model' ? <MobileSubPage title={title} dialogLabel={title} onBack={close} search={false} action={{ label: t('agent.models.settings'), icon: <GearIcon size={20} />, onClick: settings }}>
      <section className="agent-model-picker-page" aria-label={title}>{content}</section>
    </MobileSubPage> : <Modal open={!!open} onCancel={close} footer={null} title={<div className="agent-model-picker-head"><strong>{title}</strong>{open === 'model' && <button type="button" className="tt-act" aria-label={t('agent.models.settings')} onClick={settings}><GearIcon size={18} /></button>}<button type="button" className="tt-act" aria-label={t('common.close')} onClick={close}><CloseIcon size={18} /></button></div>} closable={false} destroyOnClose focusTriggerAfterClose={false}
      width={geometry?.width} className="agent-model-picker-dialog" wrapClassName="agent-model-picker-wrap" style={phone ? undefined : { left: geometry?.left, bottom: geometry?.bottom }}
      afterOpenChange={visible => { if (visible && !phone && open === 'model') search.current?.focus() }}>
      <div className="agent-model-picker-content" style={{ '--agent-picker-available': geometry ? geometry.height + 'px' : undefined } as CSSProperties}>{content}</div>
    </Modal>}
  </>
}
