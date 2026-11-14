import AggregationMemberOrder from './AggregationMemberOrder'
import { useState } from 'react'
import { Select } from 'antd'
import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelSource } from './model-hub-api'
import { candidateIdentity, previewRounds } from './routing-preview'

const signals: Record<string, string[]> = {
  smart: ['available', 'reset', 'expiry', 'rest'],
  order: ['position', 'fallback'], drain: ['sticky', 'fallback'], rotate: ['turn', 'fallback'],
  usage: ['remaining', 'rest'], pace: ['pace', 'reserve', 'rest'],
  weight: ['weight', 'fallback'], fast: ['latency', 'explore', 'rest'], cheap: ['price', 'unknownPrice', 'rest'],
}
export default function RoutingStrategyPreview({ model, sources, pools = [], onChange, disabled = false }: { model: CatalogModel; sources: ModelSource[]; pools?: CatalogModel[]; onChange?: (patch: Partial<CatalogModel>) => void; disabled?: boolean }) {
  const { t, locale } = useI18n(), [excluded, setExcluded] = useState('')
  const skip = model.candidates.some(row => candidateIdentity(row) === excluded) ? excluded : ''
  const rounds = previewRounds(model, skip), total = rounds?.length || 1
  const counts = rounds ? rounds.reduce<Record<string, number>>((result, key) => { result[key] = (result[key] || 0) + 1; return result }, {}) : undefined
  const editor = onChange && <AggregationMemberOrder model={model} sources={sources} pools={pools} disabled={disabled} onChange={onChange} counts={counts} skipped={skip} />
  return <section className="tt-strategy-preview" aria-label={t('pool.preview')}>
    <div className="tt-strategy-preview-head"><h3>{t('pool.preview')}</h3><span>{t('pool.previewExample')}</span></div>
    <ol className="tt-strategy-flow">{(signals[model.strategy] || []).map((key, index) => <li key={key}><span>{index + 1}</span><strong>{t('pool.signal.' + key)}</strong>{index < signals[model.strategy].length - 1 && <ChevronRight />}</li>)}</ol>
    {!model.candidates.length ? <p className="agent-settings-hint">{t('pool.previewEmpty')}</p> : <>
      <label className="agent-settings-field">{t('pool.simulateRest')}<Select aria-label={t('pool.simulateRest')} value={skip} options={[{ value: '', label: t('pool.noRest') }, ...model.candidates.map(row => ({ value: candidateIdentity(row), label: row.model + ' · ' + (sources.find(source => source.id === row.sourceId)?.name || t('pool.groups')) }))]} onChange={setExcluded} /></label>
      {rounds === null ? <><p className="agent-settings-hint">{t('pool.previewDynamic')}</p>{editor || <div className="tt-strategy-member-map">{model.candidates.map((row, index) => <div key={candidateIdentity(row)}><span className="tt-strategy-member-index">{index + 1}</span><div><strong>{row.model}</strong><small>{sources.find(source => source.id === row.sourceId)?.name || t('pool.groups')}</small></div>{candidateIdentity(row) === skip && <small>{t('pool.simulatedRest')}</small>}</div>)}</div>}</> : <>
        <p className="agent-settings-hint">{t('pool.previewRounds')}</p><ol className="tt-strategy-rounds">{rounds.map((id, index) => <li key={index}><small>{index + 1}</small><span>{model.candidates.findIndex(row => candidateIdentity(row) === id) + 1}</span></li>)}</ol>
        {editor || <div className="tt-strategy-distribution">{model.candidates.map((row, index) => { const id = candidateIdentity(row), count = rounds.filter(value => value === id).length; return <div key={id}><span className="tt-strategy-member-index">{index + 1}</span><div><strong>{row.model}</strong><small>{sources.find(source => source.id === row.sourceId)?.name || t('pool.groups')}</small><div className="tt-strategy-meter"><span style={{ width: (count / total * 100) + '%' }} /></div></div><span>{id === skip ? t('pool.simulatedRest') : new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(count / total)}</span></div> })}</div>}
        <p className="agent-settings-hint">{t('pool.previewCycle')}</p>
      </>}
    </>}
  </section>
}
