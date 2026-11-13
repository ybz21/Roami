import React from 'react'
import { useI18n } from '../../../../frontend/src/i18n'
export type PriceMode = 'inherit' | 'tokens' | 'free' | 'quota' | 'unknown'
export type PriceRule = { mode: PriceMode; input: string; cache: string; output: string; confirmed: boolean }
export type SourcePrices = { currency: string; global: PriceRule; defaults: Record<string, PriceRule>; models: Record<string, PriceRule> }
export const emptyRule = (): PriceRule => ({ mode: 'inherit', input: '3', cache: '0.3', output: '15', confirmed: false })
export const initialSourcePrices = (): SourcePrices => ({ currency: 'USD', global: { ...emptyRule(), mode: 'tokens' }, defaults: { work: { ...emptyRule(), mode: 'quota' }, freea: { ...emptyRule(), mode: 'free', confirmed: true }, freeb: { ...emptyRule(), mode: 'free', confirmed: true } }, models: {} })
export function resolvePrice(prices: SourcePrices, source: string, model: string): PriceRule {
 const modelRule=prices.models[JSON.stringify([source,model])]
 if(modelRule&&modelRule.mode!=='inherit')return modelRule
 const sourceRule=prices.defaults[source]
 if(sourceRule&&sourceRule.mode!=='inherit')return sourceRule
 return prices.global
}
export function validSourcePrices(value: SourcePrices, source: string, models: string[]) {
 const rules=[value.defaults[source]||emptyRule(),...models.map(model=>value.models[JSON.stringify([source,model])]).filter(Boolean)]
 return rules.every(rule=>rule.mode!=='tokens'||[rule.input,rule.cache,rule.output].every(text=>text.trim()!==''&&Number.isFinite(Number(text))&&Number(text)>=0&&Number(text)<=1_000_000))
}
const copy = {
 'zh-CN': {title:'默认定价策略',inherit:'继承全局默认',tokens:'按 Token 计价',free:'已确认免费',quota:'套餐额度',unknown:'价格未知',input:'普通输入',cache:'缓存读取',output:'输出',unit:'{currency} / 百万 Token',confirm:'我已核对该来源的免费条件',freeHint:'免费标记需与来源条件一致；填写 0 元不会自动加入免费池。',quotaHint:'套餐额度与货币费用分别记录，额度耗尽时停止使用。',override:'模型定价覆盖',follow:'继承源默认策略',priority:'模型覆盖价优先，其次源默认策略，最后全局默认策略。',needsConfirm:'尚未确认免费条件',invalid:'请输入有效的非负单价。'},
 'en-US': {title:'Default pricing policy',inherit:'Use global default',tokens:'Per-token pricing',free:'Confirmed free',quota:'Plan allowance',unknown:'Price unknown',input:'Uncached input',cache:'Cache reads',output:'Output',unit:'{currency} / million tokens',confirm:'I checked this source’s free-use conditions',freeHint:'Free status must match the source’s terms. A zero price alone does not add a model to the free pool.',quotaHint:'Plan credits are tracked separately from monetary charges. Stop using a source when its allowance is exhausted.',override:'Model price overrides',follow:'Use source default',priority:'Model overrides take precedence, followed by the source policy, then the global default.',needsConfirm:'Free-use conditions not confirmed',invalid:'Enter valid non-negative prices.'},
}
export function SourcePricing({sourceId,models,value,onChange}:{sourceId:string;models:string[];value:SourcePrices;onChange:(value:SourcePrices)=>void}) {
 const {locale}=useI18n(),t=(key:string)=>copy[locale][key]
 const defaultRule=value.defaults[sourceId]||emptyRule()
 const editRule=(rule:PriceRule,onEdit:(rule:PriceRule)=>void,override=false)=><>
 <label className="field"><span>{t(override?'override':'title')}</span><select aria-label={t(override?'override':'title')} value={rule.mode} onChange={event=>onEdit({...rule,mode:event.target.value as PriceMode,confirmed:event.target.value==='free'&&rule.mode==='free'?rule.confirmed:false})}>{(['inherit','tokens','free','quota','unknown'] as const).map(mode=><option value={mode} key={mode}>{mode==='inherit'&&override?t('follow'):t(mode)}</option>)}</select></label>
 {rule.mode==='tokens'&&<div className="price-fields">{(['input','cache','output'] as const).map(key=><label className="field" key={key}><span>{t(key)} · {t('unit').replace('{currency}',value.currency)}</span><input type="number" min={0} step="any" value={rule[key]} onChange={event=>onEdit({...rule,[key]:event.target.value})}/></label>)}</div>}
 {rule.mode==='free'&&<><label className="model-checkbox"><input type="checkbox" checked={rule.confirmed} onChange={event=>onEdit({...rule,confirmed:event.target.checked})}/><span>{t('confirm')}</span></label><p className="hint">{t('freeHint')}</p></>}
 {rule.mode==='quota'&&<p className="hint">{t('quotaHint')}</p>}
 </>
 return <section className="source-pricing"><h3>{t('title')}</h3>{editRule(defaultRule,rule=>onChange({...value,defaults:{...value.defaults,[sourceId]:rule}}))}<p className="hint">{t('priority')}</p>{!validSourcePrices(value,sourceId,models)&&<p className="error">{t('invalid')}</p>}<details><summary>{t('override')}</summary>{models.map(model=>{const key=JSON.stringify([sourceId,model]);return <div className="source-model-price" key={model}><strong>{model}</strong>{editRule(value.models[key]||emptyRule(),rule=>onChange({...value,models:{...value.models,[key]:rule}}),true)}</div>})}</details></section>
}
