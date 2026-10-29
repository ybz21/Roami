import { useId, useState } from 'react'
import { Button, Input, Select } from 'antd'
import { ChevronDown, PlusIcon, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { hasPrice, priceFields, validPriceDraft, type ModelProxyDraft, type PriceDraft } from './model-proxy-settings'

type Props = {
  value: ModelProxyDraft
  models: string[]
  catalog: string[] | null
  loadingCatalog: boolean
  catalogError: string
  loadCatalog: () => void
  disabled: boolean
  onChange: (value: ModelProxyDraft) => void
}

export function ModelPriceSettings({ value, models, catalog, loadingCatalog, catalogError, loadCatalog, disabled, onChange }: Props) {
  const { t } = useI18n(), id = useId()
  const [query, setQuery] = useState(''), [expanded, setExpanded] = useState<string | null>(null)
  const [adding, setAdding] = useState(false), [modelQuery, setModelQuery] = useState('')
  const names = Array.from(new Set([...models, ...Object.keys(value.prices)])).filter(Boolean)
  const visible = names.filter(model => model.toLowerCase().includes(query.trim().toLowerCase()))
  const candidates = (catalog || []).filter(model => !names.includes(model) && model.toLowerCase().includes(modelQuery.trim().toLowerCase()))
  const options = candidates.slice(0, 50).map(model => ({ value: model, label: model, title: model }))
  const full = Object.keys(value.prices).length >= 200
  const custom = modelQuery.trim()
  if (custom && !names.includes(custom) && !(catalog || []).includes(custom)) options.push({ value: custom, label: t('agent.models.use', { name: custom }), title: custom })
  const add = (model: string) => {
    onChange({ ...value, prices: { ...value.prices, [model]: { currency: value.currency, input: '', output: '', cacheRead: '' } } })
    setExpanded(model); setQuery(''); setAdding(false); setModelQuery('')
  }
  return <fieldset className="agent-price-settings" disabled={disabled}>
    <p className="agent-settings-hint">{t('agent.proxy.priceHint')}</p>
    <div className="agent-price-toolbar">
      <Input aria-label={t('agent.prices.search')} placeholder={t('agent.prices.search')} prefix={<SearchIcon />} value={query} disabled={disabled} onChange={event => setQuery(event.target.value)} onPressEnter={event => event.preventDefault()} />
      <Button icon={<PlusIcon />} disabled={disabled || full} onClick={() => { setAdding(true); setModelQuery('') }}>{t('agent.prices.add')}</Button>
    </div>
    {full && <p className="agent-settings-hint">{t('agent.prices.limit')}</p>}
    {adding && <div className="agent-price-add">
      <Select aria-label={t('agent.prices.choose')} placeholder={t('agent.prices.choose')} showSearch virtual={false} filterOption={false} disabled={disabled} loading={loadingCatalog} value={undefined} searchValue={modelQuery} options={options} classNames={{ popup: { root: 'agent-model-settings-options' } }} onSearch={query => setModelQuery(query.slice(0, 200))} onOpenChange={open => { if (open && catalog === null) loadCatalog() }} onChange={add} notFoundContent={t('agent.models.catalogEmpty')} />
      <Button disabled={disabled} onClick={() => setAdding(false)}>{t('common.cancel')}</Button>
      {catalogError && <p className="agent-settings-error" role="alert">{catalogError}</p>}
      {candidates.length > 50 && <p className="agent-settings-hint">{t('agent.prices.narrowSearch')}</p>}
    </div>}
    <div className="agent-proxy-prices">{visible.map(model => {
      const index = names.indexOf(model), open = expanded === model
      const price = value.prices[model] || { currency: value.currency, input: '', output: '', cacheRead: '' }
      const configured = hasPrice(price)
      const update = (patch: Partial<PriceDraft>) => onChange({ ...value, prices: { ...value.prices, [model]: { ...price, ...patch } } })
      return <div className="agent-proxy-price" key={model}>
        <button type="button" className="agent-price-toggle" disabled={disabled} aria-expanded={open} aria-controls={`${id}-${index}`} onClick={() => setExpanded(open ? null : model)}>
          <strong>{model}</strong><span>{t(configured ? validPriceDraft(price) ? 'agent.prices.configured' : 'agent.prices.incomplete' : 'agent.proxy.notSet')}</span><ChevronDown />
        </button>
        {open && <div id={`${id}-${index}`} className="agent-price-editor">
          <div className="agent-proxy-price-fields">
            {priceFields.map(key => <div className="agent-settings-field" key={key}><label htmlFor={`agent-price-${index}-${key}`}>{t('agent.proxy.price.' + key)}</label><Input id={`agent-price-${index}-${key}`} aria-label={t('agent.proxy.priceLabel', { model, kind: t('agent.proxy.price.' + key) })} type="number" min={0} max={1000000} step="any" value={price[key]} disabled={disabled} placeholder={t(key === 'cacheRead' ? 'agent.gateway.zeroPrice' : 'agent.proxy.notSet')} onChange={event => update({ [key]: event.target.value })} /></div>)}
          </div>
          {(configured || !models.includes(model)) && <button type="button" className="tt-act danger" disabled={disabled} aria-label={t('agent.proxy.removePrice', { model })} onClick={() => { const prices = { ...value.prices }; delete prices[model]; onChange({ ...value, prices }) }}>{t('agent.proxy.remove')}</button>}
        </div>}
      </div>
    })}</div>
    {visible.length === 0 && <p className="agent-settings-hint">{t('agent.prices.empty')}</p>}
  </fieldset>
}
