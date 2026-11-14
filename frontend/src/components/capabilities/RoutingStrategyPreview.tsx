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
export default function RoutingStrategyPreview({ model, sources, pools = [], onChange, disabled = false, showTitle = true }: {
  model: CatalogModel; sources: ModelSource[]; pools?: CatalogModel[]; onChange?: (patch: Partial<CatalogModel>) => void; disabled?: boolean; showTitle?: boolean
}) {
  const { t, locale } = useI18n(), [excluded, setExcluded] = useState('')
  const skip = model.candidates.some(row => candidateIdentity(row) === excluded) ? excluded : ''
  const rounds = previewRounds(model, skip), total = rounds?.length || 1
  const counts = rounds ? rounds.reduce<Record<string, number>>((result, key) => { result[key] = (result[key] || 0) + 1; return result }, {}) : undefined
  const editor = onChange && <AggregationMemberOrder model={model} sources={sources} pools={pools} disabled={disabled} onChange={onChange} counts={counts} skipped={skip} />
  const members = editor || <div className={rounds === null ? 'tt-strategy-member-map' : 'tt-strategy-distribution'}>
    {model.candidates.map((row, index) => {
      const id = candidateIdentity(row), count = counts?.[id] || 0
      return <div key={id}><span className="tt-strategy-member-index">{index + 1}</span>
        <div><strong>{row.model}</strong><small>{sources.find(source => source.id === row.sourceId)?.name || t('pool.groups')}</small>{rounds !== null && <div className="tt-strategy-meter"><span style={{ width: (count / total * 100) + '%' }} /></div>}</div>
        {id === skip ? <small>{t('pool.simulatedRest')}</small> : rounds !== null && <span>{new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(count / total)}</span>}
      </div>
    })}
  </div>
  return <section className="tt-strategy-preview" aria-label={t('pool.preview')}>
    <div className="tt-strategy-preview-head">{showTitle && <h3>{t('pool.preview')}</h3>}<span>{t('pool.previewExample')}</span></div>
    {!model.candidates.length ? <p className="agent-settings-hint">{t('pool.previewEmpty')}</p> : <div className="tt-strategy-preview-layout">
      <div className="tt-strategy-simulation">
        <ol className="tt-strategy-flow">{(signals[model.strategy] || []).map((key, index, steps) => <li key={key}><span>{index + 1}</span><strong>{t('pool.signal.' + key)}</strong>{index < steps.length - 1 && <ChevronRight />}</li>)}</ol>
        <label className="agent-settings-field">{t('pool.simulateRest')}<Select aria-label={t('pool.simulateRest')} value={skip} options={[{ value: '', label: t('pool.noRest') }, ...model.candidates.map(row => ({ value: candidateIdentity(row), label: row.model + ' · ' + (sources.find(source => source.id === row.sourceId)?.name || t('pool.groups')) }))]} onChange={setExcluded} /></label>
        {rounds === null ? <p className="agent-settings-hint">{t('pool.previewDynamic')}</p> : <>
          <p className="agent-settings-hint">{t('pool.previewRounds')}</p><ol className="tt-strategy-rounds">{rounds.map((id, index) => <li key={index}><small>{index + 1}</small><span>{model.candidates.findIndex(row => candidateIdentity(row) === id) + 1}</span></li>)}</ol>
          <p className="agent-settings-hint">{t('pool.previewCycle')}</p>
        </>}
      </div>
      <div className="tt-strategy-members">{members}</div>
    </div>}
  </section>
}
