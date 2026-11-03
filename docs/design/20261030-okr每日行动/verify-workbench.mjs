import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
const directory=path.dirname(fileURLToPath(import.meta.url)),require=createRequire(path.resolve(directory,'../../../frontend/package.json')),temporary=await mkdtemp(path.join(tmpdir(),'roami-workbench-check-'))
try {
 const outfile=path.join(temporary,'state.mjs')
 await require('esbuild').build({entryPoints:[path.join(directory,'promotion-workbench-state.ts')],bundle:true,platform:'node',format:'esm',outfile})
 const {initialWorkbench,submitDraft,acceptDraft,collectDemo,reflect,adopt,post,setPause,records,sampleDelta,parseGitHub,applyGitHub,normalizeRepo,reviewKey,updateGoal,baselineSample}=await import(pathToFileURL(outfile).href)
 let state=initialWorkbench('2026-11-03'),paused=setPause(state,true)
 const chat=post({...paused,draft:'keep going'},'讨论新开场')
 assert.equal(chat.paused,true);assert.equal(chat.messages.at(-1).text,'讨论新开场');assert.equal(chat.draft,'');assert.deepEqual(chat.tasks,state.tasks)
 for(const task of state.tasks) {
  state=submitDraft(state,task.id);assert.equal(submitDraft(state,task.id),state)
  state=acceptDraft(state,task.id);assert.equal(acceptDraft(state,task.id),state)
 }
 assert.equal(state.phase,'measurement');assert.equal(records(state).at(-1).stars,128)
 state=collectDemo(state);assert.equal(collectDemo(state),state);assert.equal(state.phase,'reflection')
 assert.equal(sampleDelta(records(state),state.date,'stars'),-3);assert.equal(sampleDelta(records(state),state.date,'forks'),2)
 state=reflect(state);assert.equal(state.review.inputKey,reviewKey(state));assert.equal(state.phase,'adoption')
 assert.equal(adopt({...state,paused:true}).round,state.round)
 const review=state.review,next=adopt(state);assert.equal(next.round,3);assert.equal(next.history.length,2);assert.equal(adopt(next),next)
 assert.equal(next.tasks.find(task=>task.channel==='x').title,review.actions.x)
 assert.equal(next.tasks.find(task=>task.channel==='bilibili').reviewId,review.id)
 assert.notEqual(next.tasks[0].title,next.tasks[1].title)
 const changed=updateGoal(state,{...state.goal,stars:200});assert.equal(changed.review,null);assert.equal(changed.phase,'reflection');assert.deepEqual(changed.demo,state.demo)
 assert.throws(()=>updateGoal(state,{...state.goal,forks:0}))
 assert.equal(normalizeRepo('https://github.com/ybz21/Roami.git'),'ybz21/Roami')
 for(const repo of ['https://evil.example/a/b','a/b?token=secret','../a/b','a/b/c']) assert.throws(()=>normalizeRepo(repo))
 const payload={id:123,full_name:'demo/roami',stargazers_count:11,forks_count:5},now=new Date('2026-11-03T03:00:00Z'),sample=parseGitHub(payload,'demo/roami',now)
 for(const update of [{id:-1},{stargazers_count:-1},{forks_count:1.5},{full_name:'other/repo'}])assert.throws(()=>parseGitHub({...payload,...update},'demo/roami',now))
 let real=applyGitHub(state,sample,true)
 assert.equal(real.messages.at(-1).date,sample.date);assert.equal(real.phase,'reflection');assert.equal(records(real).length,1);assert.equal(records(real)[0].stars,11);assert.equal(sampleDelta(records(real),sample.date,'stars'),null);assert.deepEqual(real.demo,state.demo)
 real=applyGitHub(real,{...sample,stars:10,receivedAt:'2026-11-03T04:00:00Z'},false)
 assert.equal(real.bindings['123'].length,2);assert.equal(records(real).length,1);assert.equal(records(real)[0].stars,10);assert.equal(baselineSample(real).stars,11);assert.equal(records(real)[0].stars-baselineSample(real).stars,-1)
 real=reflect(real);assert.ok(real.review.facts.some(fact=>fact.includes('链接点击尚缺')))
 real=applyGitHub(real,{...sample,stars:12,receivedAt:'2026-11-03T05:00:00Z'},false);assert.equal(real.review,null);assert.equal(real.phase,'reflection')
 real=applyGitHub(real,{...sample,repoId:456,repo:'other/roami',stars:999},false);assert.equal(records(real)[0].stars,999);assert.equal(real.bindings['123'].length,3)
 console.log('PASS: workbench execution, review/adoption idempotency, pause discussion, target revision, real/demo scope isolation, first baseline, same-day versions, repository identity, stale review and missing data')
} finally {await rm(temporary,{recursive:true,force:true})}
