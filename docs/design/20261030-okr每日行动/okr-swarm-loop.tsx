import React from 'react'
import { ChevronRight } from '../../../frontend/src/icons'
import { swarmProjection } from './okr-swarm-state'

export default function SwarmLoop({swarm,paused}:{swarm:ReturnType<typeof swarmProjection>;paused:boolean}) {
  return <section className="swarm-loop book-section" aria-label="多智能体执行反思闭环" data-board-id={swarm.boardId} data-room-id={swarm.roomId}>
    <div className="section-head"><h3>多智能体闭环 · 第 {swarm.state.activeDate === '2026-11-12' ? 1 : 2} 轮</h3><span className="meta">共享一个群聊和一张看板</span></div>
    <ol className="swarm-loop-steps">{swarm.loop.map((step,index)=><li key={step.id} data-loop-step={step.id} data-status={step.status} aria-current={step.status === 'working' ? 'step' : undefined}><div><small>{step.agent}</small><h3>{step.title}</h3><b>{({waiting:'待接棒',working:'进行中',done:'已写回',ready:'已接到新计划'})[step.status]}</b><small>{step.output}</small></div>{index < swarm.loop.length-1 && <ChevronRight size={18}/>}</li>)}</ol>
    {swarm.inheritedPlan?.sourceReviewKey ? <p className="swarm-lineage"><b>上一轮反思已经进入本轮执行</b><span>{swarm.inheritedPlan.focus}</span></p> : <p className="meta">主责派任务，成员在群聊接棒；执行、数据、反思和新计划都写回同一张看板。</p>}
    {paused && <p className="warn-text">新派发已暂停，已有任务和反思保留；可继续在群聊讨论。</p>}
  </section>
}
