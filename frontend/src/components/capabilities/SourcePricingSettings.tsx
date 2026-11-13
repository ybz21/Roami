import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Checkbox, Input, InputNumber, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { PlusIcon, SearchIcon } from '../../icons'
import BackButton from '../BackButton'
import MobileSubPage from '../MobileSubPage'
import type { PriceRule, SourcePricing, RoutingStrategy } from './model-routing-api'
import './source-pricing.css'
export type RuleDraft = { mode: PriceRule['mode']; confirmed: boolean; input: string; output: string; cache: string }
export type SourcePriceDraft = { accountStrategy: RoutingStrategy; rule: RuleDraft; models: Record<string, RuleDraft>; multiplier: number; timeRule: SourcePricing['timeRule'] }
type Effective = { model: string; origin: string; rule: PriceRule; price: PriceRule['price']; known: boolean; multiplier: number; exits?: Effective[] }
type Snapshot = { data: SourcePricing; currency: string; effective: Effective[]; summary: Effective }
const draftRule = (rule?: PriceRule): RuleDraft => ({ mode: rule?.mode || 'inherit', confirmed: rule?.confirmed || false, input: String(rule?.price?.input_per_million ?? 0), output: String(rule?.price?.output_per_million ?? 0), cache: String(rule?.price?.cache_read_per_million ?? 0) })
const fromPolicy = (policy: SourcePricing): SourcePriceDraft => ({ accountStrategy: policy.accountStrategy || 'smart', rule: draftRule(policy.default), models: Object.fromEntries(Object.entries(policy.models || {}).map(([name, rule]) => [name, draftRule(rule)])), multiplier: policy.multiplier || 1, timeRule: policy.timeRule || '' })
const priceRule = (rule: RuleDraft): PriceRule => ({ mode: rule.mode, confirmed: rule.confirmed, price: { input_per_million: rule.mode==='tokens'?Number(rule.input):0, output_per_million: rule.mode==='tokens'?Number(rule.output):0, cache_read_per_million: rule.mode==='tokens'?Number(rule.cache):0 } })
const validRule = (rule: RuleDraft) => rule.mode === 'free' ? rule.confirmed : rule.mode !== 'tokens' || [rule.input, rule.output, rule.cache].every(value => value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 1000000)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
export const sourcePriceDraftChanged = (draft?:SourcePriceDraft, policy?:SourcePricing) => !!draft && !same(draft,fromPolicy(policy || {default:{mode:'inherit',price:{input_per_million:0,output_per_million:0,cache_read_per_million:0}}}))
export default function SourcePricingSettings({ sourceId, models, draft, onChange, view = 'prices', onGlobal, onAddModels, onSaved }: { sourceId: string; models: string[]; draft?: SourcePriceDraft; onChange: (value: SourcePriceDraft) => void; view?: string; onGlobal?: () => void; onAddModels?: () => void; onSaved?: (sourceId: string, value: SourcePricing) => void }) {
  const { t, locale } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null), [failed, setFailed] = useState(false), [busy, setBusy] = useState(false), [retry, setRetry] = useState(0)
  const [editing, setEditing] = useState(''), [query, setQuery] = useState('')
  const latest = useRef(draft); latest.current = draft
  const editButton = useRef<HTMLElement | null>(null)
  const path = '/agent/model-gateway/settings/sources/' + encodeURIComponent(sourceId)
  useEffect(() => {
    const abort = new AbortController()
    void api('GET', path, undefined, { signal: abort.signal }).then(result => {
      if (abort.signal.aborted) return
      setSnapshot(result); setFailed(false)
      if (!latest.current) onChange(fromPolicy(result.data))
    }).catch(() => { if (!abort.signal.aborted) setFailed(true) })
    return () => abort.abort()
  }, [path, retry])
  const close = () => { setEditing(''); setTimeout(()=>editButton.current?.focus({preventScroll:true}),0) }
  useEffect(()=>{if(view !== 'prices')setEditing('')},[view])
  useEffect(()=>{const handler=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!busy)close()};addEventListener('keydown',handler);return()=>removeEventListener('keydown',handler)},[busy])
  if (!snapshot || !draft) return failed ? <Alert type="error" role="alert" message={t('pricing.failed')} action={<Button onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</Button>} /> : <Spin />
  const saved = fromPolicy(snapshot.data), defaultDirty = !same([draft.rule,draft.multiplier,draft.timeRule],[saved.rule,saved.multiplier,saved.timeRule])
  const accountDirty = draft.accountStrategy !== saved.accountStrategy
  const validDefault = validRule(draft.rule) && Number.isFinite(draft.multiplier) && draft.multiplier > 0 && draft.multiplier <= 1000
  const changedModel = (name: string) => !same(draft.models[name] || draftRule(), saved.models[name] || draftRule())
  const save = async (scope: 'default' | 'model' | 'account', model = '') => {
    if (busy) return
    setBusy(true); setFailed(false)
    const body: SourcePricing = { ...snapshot.data }
    if (scope === 'default') { if(!validDefault){setBusy(false);return}; body.default=priceRule(draft.rule);body.multiplier=draft.multiplier;body.timeRule=draft.timeRule }
    if (scope === 'account') body.accountStrategy=draft.accountStrategy
    if (scope === 'model') { const rule=draft.models[model] || draftRule();if(!validRule(rule)){setBusy(false);return};body.models={...snapshot.data.models,[model]:priceRule(rule)} }
    try {
      const result: Snapshot = await api('PUT', path + '?scope=' + scope + (model ? '&model=' + encodeURIComponent(model) : ''), body)
      const accepted=fromPolicy(result.data), current=latest.current || draft
      setSnapshot(result)
      onChange(scope==='default'?{...current,rule:accepted.rule,multiplier:accepted.multiplier,timeRule:accepted.timeRule}:scope==='account'?{...current,accountStrategy:accepted.accountStrategy}:{...current,models:{...current.models,[model]:accepted.models[model] || draftRule()}})
      onSaved?.(sourceId,result.data);message.success(t('pricing.saved'));if(scope==='model')close()
    } catch { setFailed(true) } finally { setBusy(false) }
  }
  const format = (value: number) => new Intl.NumberFormat(locale,{maximumFractionDigits:9}).format(value)
  const priceKeys = [['input','input_per_million'],['cache','cache_read_per_million'],['output','output_per_million']] as const
  const effective = (value?: Effective) => !value ? <span>{t('pricing.unknown')}</span> : <div className="source-effective"><span>{t('pricing.origin.'+value.origin)}</span><strong>{t('pricing.'+(value.rule.mode || 'unknown'))}</strong>{value.known && value.rule.mode==='tokens' ? <><div>{priceKeys.map(([key,field])=><span key={key}>{t('pricing.'+key)} {format(value.price[field])}</span>)}</div><small>{snapshot.currency} / {t('pricing.million')}</small></> : !value.known && <small>{t('pricing.pricePending')}</small>}</div>
  const ruleFields = (rule: RuleDraft, change: (rule: RuleDraft) => void, model = '') => <div className="source-rule-fields">
    <label className="agent-settings-field"><span>{t('pricing.method')}</span><Select virtual={false} aria-label={t('pricing.method')} disabled={busy} value={rule.mode || 'inherit'} options={['inherit','tokens','free','quota','unknown'].map(value=>({value,label:t(value==='inherit'?(model?'pricing.followSource':'pricing.followGlobal'):'pricing.'+value)}))} onChange={mode=>change({...rule,mode,confirmed:mode==='free'&&rule.mode==='free'?rule.confirmed:false})}/></label>
    {rule.mode==='tokens' && <><p className="agent-settings-hint">{t('pricing.base')} · {snapshot.currency} / {t('pricing.million')}</p><div className="tt-source-price-fields">{priceKeys.map(([key])=><label className="agent-settings-field" key={key}><span>{t('pricing.'+key)}</span><Input type="number" aria-label={t('pricing.'+key)} min={0} max={1000000} step="any" disabled={busy} value={rule[key]} onChange={event=>change({...rule,[key]:event.target.value})}/></label>)}</div></>}
    {rule.mode==='free' && <><Checkbox checked={rule.confirmed} disabled={busy} onChange={event=>change({...rule,confirmed:event.target.checked})}>{t('pricing.confirm')}</Checkbox><p className="agent-settings-hint">{t('pricing.freeHint')}</p></>}
    {rule.mode==='quota' && <p className="agent-settings-hint">{t('pricing.quotaHint')}</p>}
    {rule.mode==='unknown' && <p className="agent-settings-hint">{t('pricing.pricePending')}</p>}
    {(rule.mode==='inherit'||!rule.mode) && <p className="agent-settings-hint">{t(model?'pricing.followSource':'pricing.followGlobal')}{!model && onGlobal && <Button type="link" onClick={onGlobal}>{t('pricing.viewGlobal')}</Button>}</p>}
    {!validRule(rule) && <p className="agent-settings-error" role="status">{t(rule.mode==='free'?'pricing.confirmRequired':'pricing.invalid')}</p>}
  </div>
  const modelRule=editing?(draft.models[editing]||draftRule()):null, currentPrice=snapshot.effective?.find(row=>row.model===editing)
  const editor=modelRule && <div className="source-price-editor"><div className="source-price-editor-scroll"><h3>{editing}</h3>{ruleFields(modelRule,rule=>onChange({...draft,models:{...draft.models,[editing]:rule}}),editing)}<section><h3>{t('pricing.effective')}</h3>{effective(currentPrice)}{currentPrice?.rule.mode==='tokens'&&<p className="agent-settings-hint">{t('pricing.factorNow',{value:format(currentPrice.multiplier)})}</p>}<p className="agent-settings-hint">{t('pricing.savedPreview')}</p></section></div><footer><Button disabled={busy||!changedModel(editing)} onClick={()=>onChange({...draft,models:{...draft.models,[editing]:saved.models[editing]||draftRule()}})}>{t('agent.models.discard')}</Button><Button type="primary" disabled={!changedModel(editing)||!validRule(modelRule)} loading={busy} onClick={()=>void save('model',editing)}>{t('pricing.save')}</Button></footer></div>
  return <div className="source-pricing-workspace"><div className="source-pricing-scroll">
    {failed && <Alert type="error" role="alert" message={t('pricing.failed')} action={<Button onClick={()=>setRetry(value=>value+1)}>{t('agent.retry')}</Button>}/>}
    {view==='routing'?<section className="source-routing"><h3>{t('pricing.section.routing')}</h3><p className="agent-settings-hint">{t('pricing.routingHint')}</p><label className="agent-settings-field"><span>{t('pricing.accountStrategy')}</span><Select virtual={false} aria-label={t('pricing.accountStrategy')} disabled={busy} value={draft.accountStrategy} options={(['smart','order','drain','rotate','usage','pace','fast'] as const).map(value=>({value,label:t('pool.strategy.'+value)}))} onChange={accountStrategy=>onChange({...draft,accountStrategy})}/></label><Button type="primary" loading={busy} disabled={!accountDirty} onClick={()=>void save('account')}>{t('pricing.saveRouting')}</Button></section>:<div className="source-pricing-columns"><section className="source-pricing-default"><div className="model-usage-heading"><h3>{t('pricing.default')}</h3>{defaultDirty&&<span>{t('agent.models.unsaved')}</span>}</div><p className="agent-settings-hint">{t('pricing.defaultHint')}</p>{ruleFields(draft.rule,rule=>onChange({...draft,rule}))}<details><summary>{t('pricing.multipliers')}</summary><label className="agent-settings-field"><span>{t('pricing.multiplier')}</span><InputNumber aria-label={t('pricing.multiplier')} min={0.001} max={1000} value={draft.multiplier} disabled={busy} onChange={value=>onChange({...draft,multiplier:value??0})}/></label><label className="agent-settings-field"><span>{t('pricing.timeRule')}</span><Select virtual={false} aria-label={t('pricing.timeRule')} value={draft.timeRule} disabled={busy} options={['','deepseek','ollama-deepseek'].map(value=>({value,label:t('pricing.time.'+(value||'none'))}))} onChange={timeRule=>onChange({...draft,timeRule})}/></label><p className="agent-settings-hint">{t('pool.timePriceHint')}</p></details>{!validDefault && <p className="agent-settings-error" role="status">{t('pricing.invalid')}</p>}<div className="source-price-actions"><Button disabled={busy||!defaultDirty} onClick={()=>onChange({...draft,rule:saved.rule,multiplier:saved.multiplier,timeRule:saved.timeRule})}>{t('agent.models.discard')}</Button><Button type="primary" disabled={!defaultDirty||!validDefault} loading={busy} onClick={()=>void save('default')}>{t('pricing.save')}</Button></div><h3>{t('pricing.effectiveDefault')}</h3>{effective(snapshot.summary)}</section>
    <section className="source-pricing-models"><div className="model-usage-heading"><h3>{t('pricing.models')}</h3>{onAddModels&&<Button icon={<PlusIcon/>} onClick={onAddModels}>{t('hub.directory.updateModels')}</Button>}</div><p className="agent-settings-hint">{t('pricing.effectiveHint',{currency:snapshot.currency})}</p><Input aria-label={t('pricing.search')} placeholder={t('pricing.search')} prefix={<SearchIcon/>} value={query} onChange={event=>setQuery(event.target.value)}/><div className="source-pricing-table-wrap"><table className="source-pricing-table"><thead><tr>{['model','origin','input','cache','output','action'].map(key=><th key={key}>{t('pricing.column.'+key)}</th>)}</tr></thead><tbody>{models.filter(model=>model.toLowerCase().includes(query.toLowerCase())).map(model=>{const price=snapshot.effective?.find(row=>row.model===model);return <tr key={model}><td><strong>{model}</strong><small>{t('pricing.'+(price?.rule.mode||'unknown'))}</small>{changedModel(model)&&<small className="source-price-dirty">{t('agent.models.unsaved')}</small>}{price?.exits?.length ? <details><summary>{t('pricing.exitOverrides')}</summary>{price.exits.map(exit=><div key={exit.model}><strong>{exit.model}</strong>{effective(exit)}</div>)}</details>:null}</td><td>{price?t('pricing.origin.'+price.origin):t('pricing.unknown')}</td>{price?.known&&(price.rule.mode==='tokens'||price.rule.mode==='free')?priceKeys.map(([key,field])=><td key={key} data-label={t('pricing.'+key)}>{format(price.price[field])}</td>):<td colSpan={3}>{t(price?.rule.mode==='quota'?'pricing.quota':'pricing.pricePending')}</td>}<td><Button aria-label={t('pricing.editModel',{model})} onClick={event=>{editButton.current=event.currentTarget;setEditing(model)}}>{t('capabilities.edit')}</Button></td></tr>})}</tbody></table></div>{!models.some(model=>model.toLowerCase().includes(query.toLowerCase()))&&<p className="agent-settings-hint">{t(models.length?'pricing.noMatches':'hub.empty.catalog')}</p>}<p className="agent-settings-hint">{t('modelUsage.costHint')}</p></section></div>}
  </div>{editing && view==='prices' && (phone?<MobileSubPage title={t('pricing.editTitle')} onBack={()=>{if(!busy)close()}} search={false}>{editor}</MobileSubPage>:<aside className="source-price-inspector"><header><BackButton onClick={()=>{if(!busy)close()}}/><h3>{t('pricing.editTitle')}</h3></header>{editor}</aside>)}</div>
}
