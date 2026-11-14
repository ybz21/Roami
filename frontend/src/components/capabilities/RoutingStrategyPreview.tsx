import AggregationMemberOrder from './AggregationMemberOrder'
import { useState, type ReactNode } from 'react'
import { Select } from './model-controls'
import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelSource } from './model-hub-api'
import type { MemberFact } from './model-member-facts'
import { candidateIdentity, previewRounds } from './routing-preview'
const signals: Record<string, string[]> = {
  smart: ['available', 'reset', 'expiry', 'rest'], order: ['position', 'fallback'], drain: ['sticky', 'fallback'], rotate: ['turn', 'fallback'],
  usage: ['remaining', 'rest'], pace: ['pace', 'reserve', 'rest'], weight: ['weight', 'fallback'], fast: ['latency', 'explore', 'rest'], cheap: ['price', 'unknownPrice', 'rest'],
}
export default function RoutingStrategyPreview({ model, sources, pools = [], onChange, disabled = false, configuration, facts = {} }: {
  model: CatalogModel; sources: ModelSource[]; pools?: CatalogModel[]; onChange?: (patch: Partial<CatalogModel>) => void; disabled?: boolean; configuration?: ReactNode; facts?: Record<string, MemberFact>
}) {
  const { t } = useI18n(), [excluded, setExcluded] = useState('')
  const skip = model.candidates.some(row => candidateIdentity(row) === excluded) ? excluded : ''
  const rounds = previewRounds(model, skip)
  const counts = rounds?.reduce<Record<string, number>>((result, key) => { result[key] = (result[key] || 0) + 1; return result }, {})
  return <section className="tt-strategy-preview" aria-label={t('pool.preview')}>
    <div className="tt-routing-config-card">
      <div className="tt-routing-config-fields">{configuration}</div>
      <div className="tt-strategy-simulation"><div className="tt-strategy-preview-head"><h3>{t('pool.preview')}</h3><span>{t('pool.previewExample')}</span></div>
        <ol className="tt-strategy-flow">{(signals[model.strategy] || []).map((key, index, steps) => <li key={key}><strong>{t('pool.signal.' + key)}</strong>{index < steps.length - 1 && <ChevronRight />}</li>)}</ol>
        {!!model.candidates.length && <div className="tt-strategy-preview-controls"><label className="agent-settings-field">{t('pool.simulateRest')}<Select<string> aria-label={t('pool.simulateRest')} disabled={disabled} value={skip} options={[{ value: '', label: t('pool.noRest') }, ...model.candidates.map(row => ({ value: candidateIdentity(row), label: row.model + ' · ' + (sources.find(source => source.id === row.sourceId)?.name || t('pool.groups')) }))]} onChange={setExcluded} /></label>{rounds && <ol className="tt-strategy-rounds" aria-label={t('pool.previewRounds')}>{rounds.map((id, index) => <li key={index}><span>{model.candidates.findIndex(row => candidateIdentity(row) === id) + 1}</span></li>)}</ol>}</div>}
        <p className="agent-settings-hint">{t(!model.candidates.length ? 'pool.previewEmpty' : rounds === null ? 'orchestration.dynamicHint' : 'orchestration.previewHint')}</p>
      </div>
    </div>
    {onChange && <AggregationMemberOrder model={model} sources={sources} pools={pools} disabled={disabled} onChange={onChange} counts={counts} skipped={skip} facts={facts} />}
  </section>
}
