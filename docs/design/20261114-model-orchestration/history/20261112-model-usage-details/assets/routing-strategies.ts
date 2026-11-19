export const strategies = ['smart','order','drain','rotate','usage','pace','weight','fast','cheap'] as const
export type RoutingStrategy = typeof strategies[number]
export type RoutingTarget = {
 id:string; member:string; label:string; kind:'account'|'key'|'group'; weight:number
 remaining:number|null; capacity:number|null; resetAt:number|null; credits:{remaining:number;expiresAt:number}[]
 recentTokens:number; cooldownUntil:number; exhausted:boolean
 speed?:{ttft:number;tps:number;measuredAt:number}; price?:{input:number;output:number;currency:string}
}
export type RoutingMemory = {anchor?:string;turn:number;weights:Record<string,number>;tokens:Record<string,number>;speed:Record<string,NonNullable<RoutingTarget['speed']>>}
export const emptyRoutingMemory=():RoutingMemory=>({turn:0,weights:{},tokens:{},speed:{}})
const resetTime=(target:RoutingTarget,now:number)=>target.resetAt&&target.resetAt>now?target.resetAt:Infinity
const creditTime=(target:RoutingTarget,now:number)=>Math.min(Infinity,...target.credits.filter(value=>value.remaining>0&&value.expiresAt>now).map(value=>value.expiresAt))
export function paceRate(target:RoutingTarget,now:number) {
 const reset=resetTime(target,now),expiry=creditTime(target,now)
 const base=target.remaining!==null&&Number.isFinite(reset)?target.remaining/((reset-now)/3600000):0
 const credits=expiry<reset?target.credits.filter(value=>value.expiresAt===expiry).reduce((sum,value)=>sum+value.remaining,0)/((expiry-now)/3600000):0
 return Math.max(base,credits)
}
export function effectivePrice(target:RoutingTarget) {
 return target.price?(target.price.input+target.price.output)/2:Infinity
}
const speedCost=(target:RoutingTarget)=>target.speed?target.speed.ttft+100000/Math.max(1,target.speed.tps):Infinity
export function rankTargets(strategy:RoutingStrategy,targets:RoutingTarget[],now:number,memory:RoutingMemory):RoutingTarget[] {
 const entries=targets.map(value=>({...value,recentTokens:memory.tokens[value.id]??value.recentTokens,speed:memory.speed[value.id]??value.speed}))
 const stable=(compare:(a:RoutingTarget,b:RoutingTarget)=>number)=>[...entries].sort((a,b)=>compare(a,b)||targets.findIndex(value=>value.id===a.id)-targets.findIndex(value=>value.id===b.id))
 let ordered=entries
 if(strategy==='smart')ordered=stable((a,b)=>(a.remaining===0?1:0)-(b.remaining===0?1:0)||(Math.min(resetTime(a,now),a.resetAt?Infinity:creditTime(a,now))-Math.min(resetTime(b,now),b.resetAt?Infinity:creditTime(b,now)))||(creditTime(a,now)-creditTime(b,now)))
 if(strategy==='usage')ordered=stable((a,b)=>(b.remaining??-Infinity)-(a.remaining??-Infinity))
 if(strategy==='pace')ordered=stable((a,b)=>{
  const reserve=(value:RoutingTarget)=>value.kind!=='key'&&value.remaining!==null&&!!value.capacity&&value.remaining/value.capacity<=.1?1:0
  return reserve(a)-reserve(b)||(a.kind==='key'&&b.kind==='key'?a.recentTokens-b.recentTokens:a.kind==='key'?1:b.kind==='key'?-1:paceRate(b,now)-paceRate(a,now))
 })
 if(strategy==='drain'&&memory.anchor){const index=ordered.findIndex(value=>value.id===memory.anchor);if(index>=0)ordered=[...ordered.slice(index),...ordered.slice(0,index)]}
 if(strategy==='rotate'&&entries.length){const offset=memory.turn%entries.length;ordered=[...entries.slice(offset),...entries.slice(0,offset)]}
 if(strategy==='weight'){
  const members=[...new Set(entries.filter(value=>!value.exhausted&&value.cooldownUntil<=now).map(value=>value.member))]
  const scores=members.map(member=>({member,score:(memory.weights[member]||0)+(entries.find(value=>value.member===member)?.weight||1)})).sort((a,b)=>b.score-a.score)
  ordered=scores.flatMap(({member})=>rankTargets('smart',entries.filter(value=>value.member===member),now,emptyRoutingMemory())).concat(entries.filter(value=>!members.includes(value.member)))
 }
 if(strategy==='fast'){
  ordered=[]
  for(const target of entries){const cost=speedCost(target);const index=ordered.findIndex(value=>cost<speedCost(value)*.9);if(index<0)ordered.push(target);else ordered.splice(index,0,target)}
  if(memory.turn%5===4){const stale=entries.filter(value=>!value.speed||now-value.speed.measuredAt>=3600000);const probe=stale[Math.floor(memory.turn/5)%Math.max(1,stale.length)];if(probe)ordered=[probe,...ordered.filter(value=>value.id!==probe.id)]}
 }
 if(strategy==='cheap')ordered=stable((a,b)=>effectivePrice(a)-effectivePrice(b))
 return ordered.filter(value=>!value.exhausted&&value.cooldownUntil<=now).concat(ordered.filter(value=>value.exhausted||value.cooldownUntil>now))
}
export function recordSelection(strategy:RoutingStrategy,targets:RoutingTarget[],target:RoutingTarget,now:number,memory:RoutingMemory,streaming=true):RoutingMemory {
 const next={...memory,turn:memory.turn+1,weights:{...memory.weights},tokens:{...memory.tokens,[target.id]:(memory.tokens[target.id]??target.recentTokens)+1000},speed:{...memory.speed}}
 if(strategy==='drain'&&(!memory.anchor||!targets.some(value=>value.id===memory.anchor)||targets.find(value=>value.id===memory.anchor)?.exhausted))next.anchor=target.id
 if(strategy==='rotate')next.turn=targets.findIndex(value=>value.id===target.id)+1
 if(strategy==='weight'){
  const active=[...new Set(targets.filter(value=>!value.exhausted&&value.cooldownUntil<=now).map(value=>value.member))]
  const total=active.reduce((sum,member)=>sum+(targets.find(value=>value.member===member)?.weight||1),0)
  for(const member of active)next.weights[member]=(memory.weights[member]||0)+(targets.find(value=>value.member===member)?.weight||1)-(member===target.member?total:0)
 }
 if(streaming){const sample=target.speed||{ttft:500,tps:50,measuredAt:now},old=memory.speed[target.id];next.speed[target.id]={ttft:old?old.ttft*.3+sample.ttft*.7:sample.ttft,tps:old?old.tps*.3+sample.tps*.7:sample.tps,measuredAt:now}}
 return next
}
export const strategyCopy = {
 'zh-CN': {
 smart:{name:'智能',summary:'默认。优先使用最早重置或积分最早到期的账号。',detail:'成员的账号和 Key 一起排序，嵌套路由组算一个。订阅看周额度重置；只有 5 小时额度的看该窗口重置。没有重置时间的积分包看剩余积分最早到期时间；同一重置时间再比积分到期时间。仅选择还有余量的渠道，失败休息的排最后。'},
 order:{name:'按顺序',summary:'先用第一个成员，不能回答时再用下一个。',detail:'保持编辑器中的成员顺序。失败休息期间跳过，恢复后仍按原有顺序选择。'},
 drain:{name:'用完再换',summary:'一个账号或 Key 用完额度后换下一个，之后继续用它。',detail:'前面的额度恢复也不切回。限流或出错只在休息期间暂时跳过；临时切换不改变当前持续使用的账号。'},
 rotate:{name:'轮流',summary:'会话每一轮交给下一个成员的账号或 Key。',detail:'按会话轮次推进，均摊负载；同一轮中的重试不算新一轮。'},
 usage:{name:'最少使用',summary:'剩余额度最多的账号或 Key 优先。',detail:'展示来源提供的剩余额度；未知余额不当作无限额度。失败休息的排最后。'},
 pace:{name:'到期前用完',summary:'优先使用距重置或到期时损失额度最多的账号。',detail:'周剩余额度 ÷ 距重置小时数；仅有 5 小时窗口时按该窗口算。若更早到期的最先一批积分 ÷ 距到期小时数更高，则用该值。使用达到 90% 的账号最后兜底。Key 按最近发送的 Token 数从少到多排。'},
 weight:{name:'按权重',summary:'每个模型按权重均匀分配请求，默认权重为 1。',detail:'权重 1–1000；例如 3:1 均匀穿插分配，不成批。模型内部使用提供方自己的账号 / Key 路由，嵌套路由组算一个成员。休息成员退出本轮，失败时下一成员接上。'},
 fast:{name:'速度优先',summary:'优先使用近期首字更快、输出更快的渠道。',detail:'新回答权重更高，综合首字时间和输出速度；差距不足 10% 时保留原顺序。每五个请求分一个给一小时未测的渠道，慢过的也会再试。只测流式回复，重启清空测量，休息渠道最后。'},
 cheap:{name:'最便宜优先',summary:'仅限路由组，按当前时段的输入 / 输出价格选成员。',detail:'自设价优先，否则标价，再乘提供方倍率与分时倍率；等价保持原顺序，未知价格最后。比较百万输入 / 输出 Token 的同币种价格。分时规则见下方，免费组内均为 0 时保持原序。'},
 },
 'en-US': {
 smart:{name:'Smart',summary:'Default. Prefer the earliest quota reset or credit expiry.',detail:'Rank accounts and keys together; a nested group is one member. Use weekly reset, or the five-hour reset when no weekly quota exists. Credits without resets use the earliest remaining expiry. Equal reset times compare credit expiry. Resting channels rank last.'},
 order:{name:'In order',summary:'Use the first member, then the next if it cannot answer.',detail:'Follow the editor order. Temporarily skip resting members; resume the original order when they recover.'},
 drain:{name:'Drain',summary:'Use one account or key until exhausted, then stay with the next.',detail:'Do not switch back when earlier quota recovers. Temporarily skip rate-limited or failing channels without moving the persistent anchor.'},
 rotate:{name:'Rotate',summary:'Give each conversation round to the next account or key.',detail:'Advance once per conversation round. Retries within that round do not advance it again.'},
 usage:{name:'Least used',summary:'Prefer the account or key with the most remaining quota.',detail:'Show source-reported remaining quota. Unknown balances are not unlimited. Resting channels rank last.'},
 pace:{name:'Pace',summary:'Prefer quota most likely to expire unused.',detail:'Divide weekly remaining quota by hours to reset, or use the five-hour window when there is no weekly quota. Earlier expiring credits can override this with the earliest batch divided by hours to expiry. Accounts at 90% usage are last-resort. Keys rank by recent sent tokens, lowest first.'},
 weight:{name:'Weighted',summary:'Interleave requests by each model’s weight, default 1.',detail:'Weights range from 1 to 1000. A 3:1 split is interleaved, not batched. Each model uses its provider’s own account/key routing. A nested group counts as one member. Resting members sit out; failures fall through.'},
 fast:{name:'Fastest',summary:'Prefer recent fast first tokens and high output speed.',detail:'Recent responses carry more weight. Keep original order within a 10% difference. One in five requests probes a channel not measured for an hour, including previously slow channels. Streamed replies only; measurements reset on restart. Resting channels rank last.'},
 cheap:{name:'Cheapest',summary:'Routing groups only. Prefer the lowest current input/output price.',detail:'Use custom prices before list prices, multiplied by provider and time-of-day factors. Preserve order for ties; unknown prices rank last. Compare same-currency prices per million input/output tokens. Zero-price free members preserve their original order.'},
 },
}
