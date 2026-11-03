export type Channel='x'|'bilibili'
export type Actor='你'|'主责智能体'|'X 图文智能体'|'B站视频智能体'|'数据智能体'|'反思智能体'
export type Sample={date:string;stars:number;forks:number;receivedAt:string;source:'demo'|'github';repoId?:number;repo?:string;xViews?:number;xClicks?:number;biliPlays?:number;biliCompleted?:number;biliWatchSeconds?:number}
export type Task={id:string;channel:Channel;title:string;status:'doing'|'review'|'done';reviewId:string;artifact:string}
export type Review={id:string;inputKey:string;facts:string[];hypothesis:string;actions:Record<Channel,string>}
export type Message={id:string;author:Actor;text:string;taskId?:string;reviewId?:string;date:string}
export type Workbench={version:1;round:number;date:string;paused:boolean;phase:'execution'|'measurement'|'reflection'|'adoption';seq:number;goal:{objective:string;stars:number;forks:number;revision:number};tasks:Task[];history:Task[];messages:Message[];reviews:Review[];review:Review|null;demo:Sample[];bindings:Record<string,Sample[]>;source:'demo'|'github';repo:string;repoId:number|null;draft:string}
export const workbenchStore='roami-promotion-workbench-v1'
export const channelNames:Record<Channel,string>={x:'X 图文智能体',bilibili:'B站视频智能体'}
export const dateOffset=(date:string,amount:number)=>new Date(Date.parse(`${date}T12:00:00Z`)+86400000*amount).toISOString().slice(0,10)
export function localDate(now=new Date()) { const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);return ['year','month','day'].map(type=>parts.find(part=>part.type===type)!.value).join('-') }
const actions:Record<Channel,string>={x:'先展示 Roami 使用结果，再给步骤与仓库入口；补齐链接点击观测',bilibili:'每天一个小技巧：断开后继续同一会话；录屏、中文配音和字幕保持同步'}
function newTasks(round:number,reviewId:string,focus=actions):Task[] { return (['x','bilibili'] as const).map(channel=>({id:`r${round}-${channel}`,channel,title:focus[channel],status:'doing',reviewId,artifact:channel==='x'?'英文图文稿 · 功能截图 · 仓库入口':'技巧脚本 · 录屏 · 中文配音 · 字幕 · 成片'})) }
export function initialWorkbench(date=localDate()):Workbench {
  const yesterday=dateOffset(date,-1),previous=dateOffset(date,-2)
  const review:Review={id:'review-r1',inputKey:'seed',facts:['第一轮两条内容线已有演示交付。','X 曝光 1800，链接点击尚缺。','仓库演示快照为 128 star、19 fork；不能确定来自哪条内容。'],hypothesis:'先验证结果展示与开场，同时补齐点击；保持每天一个带配音技巧。',actions}
  return {version:1,round:2,date,paused:false,phase:'execution',seq:5,goal:{objective:'让更多开发者了解 Roami，并愿意关注和复用项目',stars:100,forks:20,revision:1},tasks:newTasks(2,review.id),history:[],messages:[{id:'m1',author:'反思智能体',date:yesterday,reviewId:review.id,text:review.hypothesis},{id:'m2',author:'主责智能体',date,text:'采用上一轮反思。@X 图文智能体 先展示使用结果；@B站视频智能体 继续每日配音小技巧。两条任务已写回共享看板。',reviewId:review.id},{id:'m3',author:'X 图文智能体',date,text:'已领取英文图文任务，沿用已验证功能与仓库入口。',taskId:'r2-x'},{id:'m4',author:'B站视频智能体',date,text:'已领取今日小技巧，正在准备录屏、配音稿与字幕。',taskId:'r2-bilibili'}],reviews:[review],review:null,demo:[{date:previous,stars:120,forks:18,receivedAt:`${previous}T13:00:00Z`,source:'demo'},{date:yesterday,stars:128,forks:19,xViews:1800,biliPlays:400,biliCompleted:104,biliWatchSeconds:6400,receivedAt:`${yesterday}T13:00:00Z`,source:'demo'}],bindings:{},source:'demo',repo:'ybz21/Roami',repoId:null,draft:''}
}
function message(state:Workbench,author:Actor,text:string,refs:Partial<Pick<Message,'taskId'|'reviewId'|'date'>>={}):Workbench { const seq=state.seq+1;return {...state,seq,messages:[...state.messages,{id:`m${seq}`,author,text,date:state.date,...refs}]} }
export function records(state:Workbench):Sample[] { const rows=state.source==='demo' ? state.demo : state.bindings[String(state.repoId)] ?? [];return [...new Map(rows.map(row=>[row.date,row])).values()].sort((a,b)=>a.date.localeCompare(b.date)) }
export function baselineSample(state:Workbench):Sample|undefined { return state.source==='demo'?state.demo[0]:state.bindings[String(state.repoId)]?.[0] }
export function sampleDelta(rows:Sample[],date:string,key:'stars'|'forks'):number|null { const current=rows.find(row=>row.date===date),previous=rows.find(row=>row.date===dateOffset(date,-1));return current&&previous ? current[key]-previous[key] : null }
export function submitDraft(state:Workbench,id:string):Workbench { const task=state.tasks.find(item=>item.id===id);if(!task||task.status!=='doing')return state;return message({...state,tasks:state.tasks.map(item=>item.id===id?{...item,status:'review'}:item)},channelNames[task.channel] as Actor,'素材草稿已提交，等待验收；发布状态仍待处理。',{taskId:id}) }
export function acceptDraft(state:Workbench,id:string):Workbench { const task=state.tasks.find(item=>item.id===id);if(!task||task.status!=='review')return state;const tasks=state.tasks.map(item=>item.id===id?{...item,status:'done' as const}:item);return message({...state,tasks,phase:tasks.every(item=>item.status==='done')?'measurement':state.phase},'主责智能体',`${channelNames[task.channel]}的演示产物已验收。交付写回看板，仓库结果等待数据。`,{taskId:id}) }
export function collectDemo(state:Workbench):Workbench { if(state.source!=='demo'||state.phase!=='measurement')return state;const previous=state.demo.at(-1)!,sample:Sample={date:state.date,stars:state.round===2?125:previous.stars+4,forks:state.round===2?21:previous.forks+1,xViews:2200,xClicks:44,biliPlays:600,biliCompleted:192,biliWatchSeconds:11400,receivedAt:new Date().toISOString(),source:'demo'};return message({...state,demo:[...state.demo.filter(row=>row.date!==sample.date),sample],phase:'reflection'},'数据智能体',`已回填 ${sample.date} 演示数据：${sample.stars} star、${sample.forks} fork；渠道反馈与仓库结果分别保留。`) }
export function normalizeRepo(input:string):string { const value=input.trim().replace(/^https:\/\/github\.com\//,'').replace(/\/$/,'').replace(/\.git$/,'');if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value))throw new Error('填写 owner/repo，例如 ybz21/Roami。');return value }
export function parseGitHub(payload:unknown,repo:string,now=new Date()):Sample {
  const value=payload as {id?:number;full_name?:string;stargazers_count?:number;forks_count?:number}
  if(!value||!Number.isSafeInteger(value.id)||value.id!<=0||typeof value.full_name!=='string'||value.full_name.toLowerCase()!==repo.toLowerCase()||![value.stargazers_count,value.forks_count].every(count=>Number.isSafeInteger(count)&&count!>=0))throw new Error('仓库身份或指标字段不完整，保留上次数据。')
  return {date:localDate(now),stars:value.stargazers_count!,forks:value.forks_count!,repoId:value.id,repo:value.full_name,source:'github',receivedAt:now.toISOString()}
}
export function applyGitHub(state:Workbench,sample:Sample,forRound:boolean):Workbench {
  if(sample.source!=='github'||!sample.repoId||!sample.repo)throw new Error('不是有效的 GitHub 观测。')
  const key=String(sample.repoId),rows=state.bindings[key]??[],existing=rows.findLast(row=>row.date===sample.date)
  // 同日变化保留采集版本，日序列仅取最后一份有效快照。
  const next={...state,source:'github' as const,repo:sample.repo,repoId:sample.repoId,bindings:{...state.bindings,[key]:[...rows,sample]},review:null,phase:forRound&&state.phase==='measurement'?'reflection' as const:state.phase==='adoption'?'reflection' as const:state.phase}
  return message(next,'数据智能体',`${existing?'更新':'读取'} GitHub 公开快照：${sample.stars} star、${sample.forks} fork。${rows.length?'历史按仓库身份保留。':'这是首个真实起点，不补造历史。'} 渠道数据仍未连接。`,{date:sample.date})
}
export function reviewKey(state:Workbench) { return JSON.stringify({round:state.round,source:state.source,repoId:state.repoId,records:records(state),tasks:state.tasks,goal:state.goal.revision}) }
export function reflect(state:Workbench):Workbench {
  if(state.phase!=='reflection')return state
  const rows=records(state),latest=rows.at(-1),baseline=baselineSample(state);if(!latest)throw new Error('先取得有效观测。')
  const stars=sampleDelta(rows,latest.date,'stars'),forks=sampleDelta(rows,latest.date,'forks')
  const facts=[`${state.tasks.filter(task=>task.status==='done').length}/${state.tasks.length} 项素材交付已验收；发布仍待独立核验。`,`${latest.date}：${latest.stars} star、${latest.forks} fork；日变化 ${stars===null?'未知':stars} / ${forks===null?'未知':forks}，周期净增 ${baseline?latest.stars-baseline.stars:'未知'} / ${baseline?latest.forks-baseline.forks:'未知'}。`,latest.xClicks===undefined?'链接点击尚缺，不能把它补成零。':`X 点击 ${latest.xClicks}；B站播放 ${latest.biliPlays}、完播 ${latest.biliCompleted}/${latest.biliPlays}、总观看 ${latest.biliWatchSeconds} 秒。`]
  const actions:Record<Channel,string>={x:stars!==null&&stars<0?'围绕一个开发者痛点重写 X 图文，先给结果；保持仓库入口并继续补测点击':'X 图文先展示使用结果，再讲步骤；核对入口和链接点击',bilibili:'继续每日一个带配音小技巧，主题与时长保持，本轮只调整前 5 秒'}
  const review:Review={id:`review-r${state.round}`,inputKey:reviewKey(state),facts,hypothesis:'观看与仓库增长需分别观察。当前证据不足以把 star/fork 归因到某条内容，继续单变量验证。',actions}
  return message({...state,review,reviews:[...state.reviews,review],phase:'adoption'},'反思智能体',`${review.hypothesis} 建议已分别写入两条执行线。`,{reviewId:review.id})
}
export function adopt(state:Workbench):Workbench { if(state.paused||state.phase!=='adoption'||!state.review||state.review.inputKey!==reviewKey(state))return state;const round=state.round+1,review=state.review,next={...state,round,date:dateOffset(state.date,1),phase:'execution' as const,history:[...state.history,...state.tasks],tasks:newTasks(round,review.id,review.actions),review:null};return message(next,'主责智能体',`已采用反思，进入第 ${round} 轮。X 图文与B站视频各有新任务；沿用同一个群聊与共享看板。`,{reviewId:review.id}) }
export function post(state:Workbench,text:string):Workbench { return text.trim()?message({...state,draft:''},'你',text.trim()):state }
export function setPause(state:Workbench,paused:boolean):Workbench { return message({...state,paused},'主责智能体',paused?'暂停新派发；已有任务可继续验收、取数和反思，群聊仍可讨论。':'恢复新派发，保留已有产物、数据和反思。') }
export function updateGoal(state:Workbench,goal:Workbench['goal']):Workbench { if(!goal.objective.trim()||![goal.stars,goal.forks].every(value=>Number.isSafeInteger(value)&&value>0))throw new Error('填写目标，并为 star、fork 设置正整数增量。');return message({...state,goal:{...goal,revision:state.goal.revision+1},review:null,phase:state.phase==='adoption'?'reflection':state.phase},'主责智能体','目标约定已更新，历史事实保留；采用下一轮前重新核对反思。') }
