import type { RoutingTarget } from './routing-strategies'
const epoch=Date.UTC(2026,10,12,12),hour=3600000
export function peakMultiplier(provider:'deepseek'|'ollama',now:number) {
 const date=new Date(now),weekday=date.getUTCDay()>0&&date.getUTCDay()<6,h=date.getUTCHours()+date.getUTCMinutes()/60
 return provider==='deepseek'?(weekday&&(h>=1&&h<4||h>=6&&h<10)?2:1):(weekday&&h>=12&&h<18?1:.5)
}
export function routingFixtures(scene:string,now:number):RoutingTarget[] {
 const target=(id:string,label:string,values:Partial<RoutingTarget>={}):RoutingTarget=>({id,member:id,label,kind:'account',weight:1,remaining:80,capacity:100,resetAt:epoch+24*hour,credits:[],recentTokens:0,cooldownUntil:0,exhausted:false,...values})
 if(scene==='quota')return[target('weekly','Weekly A',{resetAt:epoch+72*hour,remaining:80}),target('five-hour','5-hour only',{resetAt:epoch+2*hour,remaining:50}),target('weekly-b','Weekly B',{remaining:95}),target('reserve','90% used',{remaining:5,resetAt:epoch+hour/60})]
 if(scene==='credits')return[target('month-later','Monthly A',{resetAt:Date.UTC(2026,10,30),credits:[{remaining:30,expiresAt:epoch+48*hour}]}),target('month-sooner','Monthly B',{resetAt:Date.UTC(2026,10,30),credits:[{remaining:20,expiresAt:epoch+24*hour}]}),target('points','Credit pack',{resetAt:null,credits:[{remaining:40,expiresAt:epoch+12*hour}]})]
 if(scene==='keys')return[target('key-a','Key A',{kind:'key',remaining:null,capacity:null,resetAt:null,recentTokens:20000}),target('key-b','Key B',{kind:'key',remaining:null,capacity:null,resetAt:null,recentTokens:1000})]
 if(scene==='weight')return[target('a-1','Model A / Account 1',{member:'model-a',weight:3}),target('a-2','Model A / Account 2',{member:'model-a',weight:3,resetAt:epoch+48*hour}),target('b','Model B / Key',{member:'model-b',kind:'key',remaining:null,capacity:null,weight:1}),target('group','Nested group',{kind:'group',member:'child-group',weight:1})]
 if(scene==='speed')return[target('steady','Channel A',{speed:{ttft:500,tps:50,measuredAt:epoch}}),target('similar','Channel B (<10%)',{speed:{ttft:480,tps:52,measuredAt:epoch}}),target('stale','Channel C (stale)',{speed:{ttft:1500,tps:15,measuredAt:epoch-2*hour}})]
 return[target('official','DeepSeek official',{price:{input:1*peakMultiplier('deepseek',now),output:2*peakMultiplier('deepseek',now),currency:'USD'}}),target('ollama','Ollama Cloud',{price:{input:1.2*peakMultiplier('ollama',now),output:2.4*peakMultiplier('ollama',now),currency:'USD'}}),target('custom','Custom price × 1.2',{price:{input:.8*1.2,output:1.6*1.2,currency:'USD'}}),target('unknown','Unknown price',{price:undefined})]
}
