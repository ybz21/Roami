import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const directory = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.resolve(directory,'../../../frontend/package.json'))
const temporary = await mkdtemp(path.join(tmpdir(),'okr-generation-check-'))
try {
  const outfile = path.join(temporary,'contract.mjs')
  await require('esbuild').build({ stdin:{ contents:"export * from './okr-generation-contract'; export * from './okr-generation-replays'; export * from './okr-execution-cycle'; export * from './okr-dialogue-scenes'; export * from './okr-swarm-state'; export * from './prototype-data'; export * from './okr-setup-model'",resolveDir:directory,loader:'ts' },bundle:true,platform:'node',format:'esm',outfile })
  const { parsePlan, growthReplay, qualityReplay, repoReplay, validateObservation, replayObservation, measuredValue, initialCycle, cycleDefinitions, cycleActions, deliverAction, collectCycleData, dailyDelta, reviewCycle, reviewIsCurrent, latestCycleReview, applyNextPlan, matureComparison, watchQuality, initialGoals, valueAt, creatorMetrics, starter, analyze, requiredFacts } = await import(pathToFileURL(outfile).href)
  for (const plan of [growthReplay,qualityReplay,repoReplay]) assert.equal(parsePlan(JSON.stringify(plan)).objective,plan.objective)
  assert.equal(growthReplay.keyResults.length,4)
  assert.equal(qualityReplay.keyResults.length,5)
  assert.deepEqual(new Set(qualityReplay.keyResults.map(kr => kr.view)),new Set(['number','milestones','checklist']))
  assert.equal(growthReplay.connectors[0].fields.length,4)
  assert.equal(qualityReplay.connectors[0].fields.length,5)
  assert.ok(qualityReplay.connectors[0].revision > growthReplay.connectors[0].revision)
  assert.equal(growthReplay.keyResults[0].horizon,'long')
  assert.equal(growthReplay.keyResults.find(kr=>kr.id==='publishing-loop').parentKrId,growthReplay.keyResults[0].id)
  const unfamiliar = structuredClone(growthReplay)
  unfamiliar.statement = '降低检索耗时'; unfamiliar.objective = '让文档更容易找到'
  unfamiliar.keyResults = [{ id:'search-result',title:'检索耗时低于20秒',view:'number',metricId:'find-time',target:20,unit:'秒',rationale:'以任务计时观察' }]
  unfamiliar.metrics = [{ id:'find-time',krId:'search-result',name:'检索耗时',unit:'秒',connectorId:'search-source',formula:{ op:'field',field:'seconds' },rationale:'独立计时' }]
  unfamiliar.connectors = [{ ...unfamiliar.connectors[0],id:'search-source',fields:[{ id:'seconds',unit:'秒',selector:'[data-field="seconds"]' }] }]
  unfamiliar.widgets = [{ id:'timing',type:'metric',title:'检索体验',metricIds:['find-time'] }]
  assert.equal(parsePlan(JSON.stringify(unfamiliar)).metrics[0].name,'检索耗时')
  const sample = validateObservation(replayObservation(qualityReplay),qualityReplay)
  assert.equal(measuredValue(qualityReplay.metrics[0],[sample],sample.date),328)
  assert.equal(measuredValue(qualityReplay.metrics[1],[sample],sample.date),null)
  assert.equal(measuredValue(qualityReplay.metrics.find(m=>m.id==='engagement-rate'),[sample],sample.date),40/600*100)
  assert.equal(measuredValue(qualityReplay.metrics[0],[],'2026-11-11'),null)
  for (const mutate of [
    p => { p.widgets[0].metricIds = ['missing'] },
    p => { p.widgets[0].type = 'html' },
    p => { p.metrics[0].formula = { op:'eval' } },
    p => { p.metrics[0].unit = 'ms' },
    p => { p.metrics[1].formula.baseline = 0 },
    p => { p.cycleStart = '2026-02-30' },
    p => { p.keyResults.push(p.keyResults[0]) },
    p => { p.keyResults[0].parentKrId = 'publishing-loop' },
    p => { p.keyResults.find(kr=>kr.id==='publishing-loop').period.end = '2027-02-01' },
  ]) { const plan = structuredClone(qualityReplay); mutate(plan); assert.throws(() => parsePlan(JSON.stringify(plan))) }
  for (const mutate of [
    row => { row.accountId = 'other' },
    row => { delete row.values.audience },
    row => { row.values.audience.unit = '次' },
    row => { row.connectorRevision = 9 },
    row => { row.date = '2026-02-30' },
    row => { row.values.plays.value = 1 },
    row => { row.sourceUrl = 'https://other.example/a' },
  ]) { const row = structuredClone(sample); mutate(row); assert.throws(() => validateObservation(row,qualityReplay)) }
  const zero = structuredClone(sample); zero.values.plays.value = 0; zero.values.likes.value = 0; zero.values.completed.value = 0
  validateObservation(zero,qualityReplay)
  assert.equal(measuredValue(qualityReplay.metrics.find(m=>m.id==='engagement-rate'),[zero],zero.date),null)
  const qualityMetric = id => qualityReplay.metrics.find(metric=>metric.id===id)
  assert.equal(measuredValue(qualityMetric('completion-rate'),[sample],sample.date),24)
  assert.equal(measuredValue(qualityMetric('average-watch'),[sample],sample.date),14)
  assert.equal(measuredValue(qualityMetric('average-watch'),[zero],zero.date),null)
  const missingWatch = structuredClone(sample);delete missingWatch.values['watch-seconds']
  assert.throws(()=>validateObservation(missingWatch,qualityReplay))
  const wrongWatchUnit = structuredClone(qualityReplay);wrongWatchUnit.connectors[0].fields.find(field=>field.id==='watch-seconds').unit='ms'
  assert.throws(()=>parsePlan(JSON.stringify(wrongWatchUnit)))
  const panel = initialGoals()[0], averageMetric = creatorMetrics.find(metric=>metric.id==='averageWatch')
  const dates = Object.keys(panel.observations).sort().slice(-7)
  const expectedAverage = dates.reduce((sum,date)=>sum+panel.observations[date].watchSeconds,0)/dates.reduce((sum,date)=>sum+panel.observations[date].plays,0)
  assert.equal(valueAt(panel,averageMetric,dates.at(-1)),expectedAverage)
  const incompletePanel = structuredClone(panel);delete incompletePanel.observations[dates[0]].watchSeconds
  assert.equal(valueAt(incompletePanel,averageMetric,dates.at(-1)),null)
  const candidates = analyze(starter('creator'))
  assert.ok(candidates.some(metric=>metric.id==='averageWatch' && metric.krId==='watch-time'))
  assert.ok(requiredFacts(candidates).includes('watchSeconds'))
  let cycle = initialCycle('creator')
  assert.throws(() => deliverAction(cycle,'creator','video-draft'))
  cycle = reviewCycle(cycle,'creator')
  assert.equal(latestCycleReview(cycle).waiting,true)
  cycle = applyNextPlan(cycle)
  assert.equal(cycle.plans.at(-1).mode,'measurement')
  const measuring = { ...cycle,activeDate:'2026-11-13' }
  assert.equal(cycleActions(measuring,'creator').length,0)
  cycle = { ...cycle,linkedProjects:['content-studio','content-tools'] }
  cycle = deliverAction(cycle,'creator','video-draft')
  assert.equal(deliverAction(cycle,'creator','video-draft'),cycle)
  cycle = collectCycleData(cycle,'creator')
  assert.equal(dailyDelta(cycle,'2026-11-12'),6)
  assert.equal(collectCycleData(cycle,'creator'),cycle)
  assert.equal(reviewIsCurrent(cycle),false)
  assert.throws(() => applyNextPlan(cycle))
  cycle = reviewCycle(cycle,'creator')
  assert.ok(latestCycleReview(cycle).decision.includes('继续观察'))
  cycle = applyNextPlan(cycle)
  assert.equal(cycle.plans.at(-1).revision,2)
  assert.equal(cycle.plans.at(-1).mode,'production')
  assert.equal(applyNextPlan(cycle),cycle)
  cycle = { ...cycle,activeDate:'2026-11-13' }
  assert.equal(cycleActions(cycle,'creator')[0].title,latestCycleReview({ ...cycle,activeDate:'2026-11-12' }).nextAction)
  cycle = collectCycleData(cycle,'creator')
  assert.equal(dailyDelta(cycle,'2026-11-13'),-2)
  assert.equal(matureComparison(cycle,'2026-11-12'),null)
  assert.equal(matureComparison(cycle,'2026-11-13').change,8)
  assert.equal(matureComparison(cycle,'2026-11-13').averageA,14)
  assert.equal(matureComparison(cycle,'2026-11-13').averageB,19)
  assert.deepEqual(watchQuality(cycle.observations.at(-1)),{completion:27,average:17})
  assert.deepEqual(watchQuality({plays:0,completed:0,watchSeconds:0}),{completion:null,average:null})
  assert.deepEqual(watchQuality({plays:1000}),{completion:null,average:null})
  const revisedQuality = structuredClone(cycle);revisedQuality.observations.at(-1).watchSeconds=10000
  assert.equal(reviewIsCurrent(revisedQuality),false)
  const missingVideos = reviewCycle({ ...cycle,variantObservations:[] },'creator')
  assert.ok(latestCycleReview(missingVideos).facts.some(fact => fact.includes('缺少可比较')))
  cycle = reviewCycle(cycle,'creator')
  assert.ok(latestCycleReview(cycle).decision.includes('没有随机分流'))
  const changedWatch = structuredClone(cycle);changedWatch.observations.at(-1).watchSeconds=11000
  assert.equal(reviewIsCurrent(changedWatch),false)
  const missingAverage = structuredClone(cycle);delete missingAverage.variantObservations.find(row=>row.videoId==='video-b'&&row.ageHours===24).watchSeconds
  assert.equal(matureComparison(missingAverage,'2026-11-13').averageB,null)
  assert.equal(cycleDefinitions.creator.target,200)
  let repo = initialCycle('repo')
  repo = { ...repo,linkedProjects:['pocketboard'] }
  repo = deliverAction(repo,'repo','index-candidate')
  repo = collectCycleData(repo,'repo')
  assert.equal(repo.observations.at(-1).value,720)
  repo = reviewCycle(repo,'repo')
  assert.ok(latestCycleReview(repo).facts.some(fact => fact.includes('280ms') && fact.includes('720ms')))
  const { dialogueScenes,sceneOffsets,sceneAt,storyDuration,scenePlan,sceneCycle,sceneSnapshot,storylines,sceneLifecycle,swarmProjection,swarmMessages } = await import(pathToFileURL(outfile).href)
  for (const kind of ['creator','repo']) {
    const scenes = dialogueScenes[kind], offsets = sceneOffsets(kind)
    assert.equal(scenes[0].view,'intent')
    assert.equal(sceneLifecycle(scenes[0]),'building')
    assert.equal(sceneLifecycle(scenes.find(scene=>scene.id==='projects')),'building')
    assert.equal(sceneLifecycle(scenes.find(scene=>scene.id==='activate')),'running')
    assert.equal(sceneLifecycle(scenes.at(-1)),'running')
    assert.deepEqual([...new Set(scenes.map(scene => scene.chapter))],storylines.map(line => line.title))
    const chapterOrder = scenes.map(scene => storylines.findIndex(line => line.title === scene.chapter))
    assert.deepEqual(chapterOrder,[...chapterOrder].sort((a,b) => a-b))
    assert.equal(new Set(scenes.map(scene => scene.id)).size,scenes.length)
    assert.equal(sceneAt(kind,0),0)
    assert.equal(sceneAt(kind,storyDuration(kind)),scenes.length-1)
    for (const [index,scene] of scenes.entries()) {
      assert.equal(sceneAt(kind,offsets[index]),index)
      assert.ok(scene.duration >= 1000 && scene.user && scene.reply && scene.caption)
      parsePlan(JSON.stringify(scenePlan(kind,scene.revision)))
      const stage = sceneSnapshot(kind,scene)
      if (chapterOrder[index] < 3) { assert.equal(stage.observations.length,1);assert.equal(stage.events.length,0);assert.equal(stage.reviews.length,0) }
    }
    const launch = swarmProjection(kind,scenes.find(scene=>scene.id==='activate')), active = swarmProjection(kind,scenes.find(scene=>scene.id==='work')), final = swarmProjection(kind,scenes.at(-1))
    assert.equal(launch.id,final.id)
    assert.equal(launch.members.length,4)
    assert.ok(launch.tasks.every(task=>task.state==='waiting'))
    assert.ok(active.tasks.some(task=>task.member==='执行'&&task.state==='done'))
    assert.ok(active.tasks.some(task=>task.member==='数据'&&task.state!=='done'))
    assert.ok(final.nextPlan)
    assert.equal(launch.boardId,final.boardId)
    assert.equal(launch.roomId,final.roomId)
    const firstReview = swarmProjection(kind,scenes.find(scene=>scene.id==='first-review'))
    assert.equal(firstReview.loop.find(step=>step.id==='reflect').status,'done')
    assert.equal(firstReview.loop.find(step=>step.id==='adjust').status,'working')
    assert.equal(firstReview.loop.find(step=>step.id==='execute-again').status,'waiting')
    const secondExecution = swarmProjection(kind,scenes.find(scene=>scene.id==='second-work'))
    assert.ok(secondExecution.inheritedPlan.sourceReviewKey)
    assert.equal(secondExecution.inheritedPlan.focus,firstReview.review.nextAction)
    assert.equal(secondExecution.tasks.find(task=>task.member==='执行').title,firstReview.review.nextAction)
    assert.ok(secondExecution.allTasks.some(task=>task.id.startsWith('2026-11-12:')))
    assert.ok(secondExecution.allTasks.some(task=>task.id.startsWith('2026-11-13:')))
    const room = swarmMessages(kind,scenes.at(-1))
    assert.deepEqual(new Set(room.filter(message=>message.author!=='你').map(message=>message.author)),new Set(['主责智能体','执行智能体','数据智能体','反思智能体']))
    assert.ok(room.filter(message=>message.taskId).every(message=>final.allTasks.some(task=>task.id===message.taskId)))
    assert.ok(swarmMessages(kind,scenes.find(scene=>scene.id==='work')).every(message=>message.author!=='反思智能体'))
    assert.ok(room.some(message=>message.author==='执行智能体'&&message.date==='2026-11-13'))

    const deliveredStage = sceneSnapshot(kind,scenes.find(scene => scene.id === 'work'))
    assert.ok(deliveredStage.delivered['2026-11-12'].length>0)
    assert.equal(deliveredStage.observations.length,1)
    assert.equal(latestCycleReview(deliveredStage),undefined)
    const collectedStage = sceneSnapshot(kind,scenes.find(scene => scene.id === 'collect'))
    assert.equal(collectedStage.observations.length,2)
    assert.equal(latestCycleReview(collectedStage),undefined)
    const reviewedStage = sceneSnapshot(kind,scenes.find(scene => scene.id === 'first-review'))
    assert.ok(latestCycleReview(reviewedStage))
    if (kind === 'creator') {
      const secondWork = sceneSnapshot(kind,scenes.find(scene => scene.id === 'second-work'))
      assert.equal(secondWork.activeDate,'2026-11-13')
      assert.equal(secondWork.observations.length,2)
      assert.ok(secondWork.delivered['2026-11-13'].length)
      assert.ok(secondWork.plans.at(-1).sourceReviewKey)
    }
    const snapshot = sceneCycle(kind,2)
    assert.equal(snapshot.activeDate,'2026-11-13')
    assert.equal(snapshot.observations.length,3)
    if (kind === 'creator') assert.equal(dailyDelta(snapshot,snapshot.activeDate),-2)
    else assert.equal(snapshot.observations.at(-1).value,720)
  }
  console.log('PASS: generated plans, daily learning cycle, evidence boundaries, dialogue scenes and seek checkpoints for both stories')
} finally {
  await rm(temporary,{ recursive:true,force:true })
}
