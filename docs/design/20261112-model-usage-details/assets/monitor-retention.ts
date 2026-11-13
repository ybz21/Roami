export const MONITOR_RETENTION_MS=24*60*60*1000
export const MONITOR_MAX_RECORDS=10000
export const MONITOR_MAX_BYTES=64*1024*1024
export type MonitorSample={id:number;at:number;source:string;model:string;success:boolean;ttft:number|null;tps:number|null;quality:'pass'|'fail'|'unchecked';failure:'timeout'|'rate-limit'|'invalid'|null}
export class MonitorRing {
 private entries:{sample:MonitorSample;bytes:number}[]=[]
 bytes=0
 expired=0
 evicted=0
 constructor(readonly maxRecords=MONITOR_MAX_RECORDS,readonly maxBytes=MONITOR_MAX_BYTES){}
 append(samples:MonitorSample[],now:number){
  this.prune(now)
  for(const sample of samples){
   if(sample.at<=now-MONITOR_RETENTION_MS||sample.at>now)continue
   const bytes=new TextEncoder().encode(JSON.stringify(sample)).byteLength
   if(bytes>this.maxBytes){this.evicted++;continue}
   const entry={sample,bytes},last=this.entries[this.entries.length-1]
   if(!last||last.sample.at<=sample.at)this.entries.push(entry)
   else{let low=0,high=this.entries.length;while(low<high){const mid=(low+high)>>>1;if(this.entries[mid].sample.at<=sample.at)low=mid+1;else high=mid}this.entries.splice(low,0,entry)}
   this.bytes+=bytes
   while(this.entries.length>this.maxRecords||this.bytes>this.maxBytes)this.drop(false)
  }
 }
 private drop(expired:boolean){const entry=this.entries.shift();if(!entry)return;this.bytes-=entry.bytes;if(expired)this.expired++;else this.evicted++}
 prune(now:number){while(this.entries.length&&this.entries[0].sample.at<=now-MONITOR_RETENTION_MS)this.drop(true)}
 snapshot(){return this.entries.map(entry=>entry.sample)}
}
export const percentile=(values:number[],ratio:number)=>values.length?[...values].sort((a,b)=>a-b)[Math.max(0,Math.ceil(values.length*ratio)-1)]:null
export function monitorStats(samples:MonitorSample[]){
 const replies=samples.filter(value=>value.success),graded=samples.filter(value=>value.quality!=='unchecked')
 return{count:samples.length,success:samples.length?replies.length/samples.length:null,p95:percentile(replies.map(value=>value.ttft).filter((value):value is number=>value!==null),.95),tps:percentile(replies.map(value=>value.tps).filter((value):value is number=>value!==null),.5),quality:graded.length?graded.filter(value=>value.quality==='pass').length/graded.length:null,graded:graded.length,failed:samples.filter(value=>!value.success).length}
}
