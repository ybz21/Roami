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
  await require('esbuild').build({ stdin:{ contents:"export * from './okr-generation-contract'; export * from './okr-generation-replays'; export * from './okr-execution-cycle'; export * from './okr-dialogue-scenes'; export * from './okr-swarm-state'",resolveDir:directory,loader:'ts' },bundle:true,platform:'node',format:'esm',outfile })
  const { parsePlan, growthReplay, qualityReplay, repoReplay, validateObservation, replayObservation, measuredValue, initialCycle, cycleDefinitions, cycleActions, deliverAction, collectCycleData, dailyDelta, reviewCycle, reviewIsCurrent, latestCycleReview, applyNextPlan, matureComparison } = await import(pathToFileURL(outfile).href)
  for (const plan of [growthReplay,qualityReplay,repoReplay]) assert.equal(parsePlan(JSON.stringify(plan)).objective,plan.objective)
  assert.equal(growthReplay.keyResults.length,2)
  assert.equal(qualityReplay.keyResults.length,3)
  assert.deepEqual(new Set(qualityReplay.keyResults.map(kr => kr.view)),new Set(['number','milestones','checklist']))
  assert.equal(growthReplay.connectors[0].fields.length,1)
  assert.equal(qualityReplay.connectors[0].fields.length,3)
  assert.ok(qualityReplay.connectors[0].revision > growthReplay.connectors[0].revision)
  assert.equal(growthReplay.keyResults[0].horizon,'long')
  assert.equal(growthReplay.keyResults[1].parentKrId,growthReplay.keyResults[0].id)
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
  assert.equal(measuredValue(qualityReplay.metrics[2],[sample],sample.date),40/700*100)
  assert.equal(measuredValue(qualityReplay.metrics[0],[],'2026-11-11'),null)
  for (const mutate of [
    p => { p.widgets[0].metricIds = ['missing'] },
    p => { p.widgets[0].type = 'html' },
    p => { p.metrics[0].formula = { op:'eval' } },
    p => { p.metrics[0].unit = 'ms' },
    p => { p.metrics[1].formula.baseline = 0 },
    p => { p.cycleStart = '2026-02-30' },
    p => { p.keyResults.push(p.keyResults[0]) },
    p => { p.keyResults[0].parentKrId = p.keyResults[1].id },
    p => { p.keyResults[1].period.end = '2027-02-01' },
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
  const zero = structuredClone(sample); zero.values.plays.value = 0; zero.values.likes.value = 0
  validateObservation(zero,qualityReplay)
  assert.equal(measuredValue(qualityReplay.metrics[2],[zero],zero.date),null)
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
  const missingVideos = reviewCycle({ ...cycle,variantObservations:[] },'creator')
  assert.ok(latestCycleReview(missingVideos).facts.some(fact => fact.includes('缺少可比较')))
  cycle = reviewCycle(cycle,'creator')
  assert.ok(latestCycleReview(cycle).decision.includes('没有随机分流'))
  assert.equal(cycleDefinitions.creator.target,200)
  let repo = initialCycle('repo')
  repo = { ...repo,linkedProjects:['pocketboard'] }
  repo = deliverAction(repo,'repo','index-candidate')
  repo = collectCycleData(repo,'repo')
  assert.equal(repo.observations.at(-1).value,720)
  repo = reviewCycle(repo,'repo')
  assert.ok(latestCycleReview(repo).facts.some(fact => fact.includes('280ms') && fact.includes('720ms')))
  const { dialogueScenes,sceneOffsets,sceneAt,storyDuration,scenePlan,sceneCycle,sceneSnapshot,storylines,sceneLifecycle,swarmProjection } = await import(pathToFileURL(outfile).href)
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
