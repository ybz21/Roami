import { useId, useRef, useState } from 'react'
import { Button, Dropdown, InputNumber } from 'antd'
import { ArrowDown, ArrowUp, ChevronDown, CloseIcon, DragHandleIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCandidate, ModelSource } from './model-hub-api'
import { candidateIdentity } from './routing-preview'
import { useAggregationMemberDrag } from './use-aggregation-member-drag'

export default function AggregationMemberOrder({ model, sources, pools, disabled, onChange, counts, skipped }: { model: CatalogModel; sources: ModelSource[]; pools: CatalogModel[]; disabled: boolean; onChange: (patch: Partial<CatalogModel>) => void; counts?: Record<string, number>; skipped?: string }) {
  const { t, locale } = useI18n(), list = useRef<HTMLOListElement>(null), hint = useId()
  const [announcement, setAnnouncement] = useState('')
  const name = (candidate: ModelCandidate) => candidate.sourceId === '@group' ? pools.find(pool => pool.id === candidate.model)?.name || candidate.model : candidate.model
  const sourceName = (candidate: ModelCandidate) => candidate.sourceId === '@group' ? t('pool.groups') : sources.find(source => source.id === candidate.sourceId)?.name || candidate.sourceId
  const reorder = (key: string, target: string) => {
    if (disabled) return
    const from = model.candidates.findIndex(row => candidateIdentity(row) === key), to = model.candidates.findIndex(row => candidateIdentity(row) === target)
    if (from < 0 || to < 0 || from === to) return
    const candidates = [...model.candidates], [moved] = candidates.splice(from, 1)
    candidates.splice(to, 0, moved)
    onChange({ candidates })
    setAnnouncement(t('pool.memberMoved', { model: name(moved), position: to + 1, count: candidates.length }))
  }
  const total = Object.values(counts || {}).reduce((sum, value) => sum + value, 0) || 1
  const order = JSON.stringify(model.candidates.map(candidateIdentity))
  const { drag, start, move, finish, cancel } = useAggregationMemberDrag(list, order, disabled, reorder)
  const step = (index: number, to: number) => { if (to >= 0 && to < model.candidates.length) reorder(candidateIdentity(model.candidates[index]), candidateIdentity(model.candidates[to])) }
  const organize = (by: string) => {
    if (disabled) return
    const compare = new Intl.Collator(locale, { numeric: true, sensitivity: 'base' })
    const candidates = [...model.candidates].sort((a, b) => by === 'source' ? compare.compare(sourceName(a), sourceName(b)) : compare.compare(name(a), name(b)))
    onChange({ candidates }); setAnnouncement(t('pool.organized.' + by))
  }
  const from = model.candidates.findIndex(row => candidateIdentity(row) === drag?.key), to = model.candidates.findIndex(row => candidateIdentity(row) === drag?.target)
  return <section className="tt-member-order" aria-label={t('pool.memberOrder')}>
    <div className="tt-member-order-head"><strong>{t('pool.memberOrder')}</strong><span>{t('pool.strategy.' + model.strategy)}</span><Dropdown disabled={disabled || model.candidates.length < 2} trigger={['click']} menu={{ items: ['source', 'model'].map(key => ({ key, label: t('pool.organize.' + key) })), onClick: ({ key }) => organize(key) }}><Button disabled={disabled || model.candidates.length < 2}>{t('pool.organize')}<ChevronDown /></Button></Dropdown></div>
    <p className="agent-settings-hint">{t('pool.orderEffect.' + model.strategy)}</p><p className="agent-settings-hint" id={hint}>{t('pool.dragHint')}</p>
    <ol className="tt-routing-members" ref={list}>{model.candidates.map((candidate, index) => {
      const key = candidateIdentity(candidate)
      return <li data-member-key={key} className={(drag?.key === key ? 'is-dragging ' : '') + (drag?.target === key && from !== to ? from > to ? 'is-drop-before' : 'is-drop-after' : '')} key={key}>
        <button type="button" className="tt-act tt-member-drag" aria-label={t('pool.dragMember', { model: name(candidate) })} aria-describedby={hint} disabled={disabled || model.candidates.length < 2} onPointerDown={event => start(event, key)} onPointerMove={move} onPointerUp={finish} onPointerCancel={cancel} onLostPointerCapture={cancel} onKeyDown={event => {
          if (event.key === 'Escape') { event.preventDefault(); cancel(); return }
          if (drag) return
          const next = event.key === 'ArrowUp' ? index - 1 : event.key === 'ArrowDown' ? index + 1 : event.key === 'Home' ? 0 : event.key === 'End' ? model.candidates.length - 1 : null
          if (next !== null) { event.preventDefault(); step(index, next) }
        }}><DragHandleIcon /></button><span className="tt-strategy-member-index">{index + 1}</span><div className="tt-member-identity"><strong>{name(candidate)}</strong><small>{sourceName(candidate)}</small>{counts && <div className="tt-strategy-meter"><span style={{ width: ((counts[key] || 0) / total * 100) + '%' }} /></div>}</div>
        <div className="tt-member-controls">{skipped === key ? <small>{t('pool.simulatedRest')}</small> : counts && <small>{new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format((counts[key] || 0) / total)}</small>}{model.strategy === 'weight' && <label className="agent-settings-field tt-member-weight">{t('pool.weight')}<InputNumber aria-label={t('pool.weight') + ' ' + candidate.model} disabled={disabled} min={1} max={1000} precision={0} value={Number.isNaN(model.weights?.[key]) ? null : model.weights?.[key] ?? 1} onChange={value => onChange({ weights: { ...model.weights, [key]: value ?? NaN } })} /></label>}
          <button type="button" className="tt-act" aria-label={t('pool.up') + ' ' + candidate.model} disabled={disabled || index === 0} onClick={() => step(index, index - 1)}><ArrowUp /></button><button type="button" className="tt-act" aria-label={t('pool.down') + ' ' + candidate.model} disabled={disabled || index === model.candidates.length - 1} onClick={() => step(index, index + 1)}><ArrowDown /></button><button type="button" className="tt-act" aria-label={t('pool.remove') + ' ' + candidate.model} disabled={disabled} onClick={() => { const weights = { ...model.weights }; delete weights[key]; onChange({ candidates: model.candidates.filter((_, row) => row !== index), weights }) }}><CloseIcon /></button>
        </div>
      </li>
    })}</ol><p role="status" aria-live="polite" className="agent-settings-hint">{announcement}</p>
  </section>
}
