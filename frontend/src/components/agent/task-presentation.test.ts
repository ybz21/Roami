import { expect, it } from 'vitest'
import type { AgentTask } from './agent-protocol'
import { taskTopic } from './task-topic'
import { taskInstructions } from './agent-task-protocol'
import { taskOutcome, taskReportLinks } from './task-outcome'

const task = (intent: unknown) => ({ id: 'internal-id', intent_json: JSON.stringify(intent) } as AgentTask)
it('keeps the topic separate from requirements and preserves it after continuation', () => {
  expect(taskInstructions(task({ initialIntent: { goal: 'Original' }, goal: 'Current full instructions' }))).toBe('Current full instructions')
  expect(taskTopic(task({ title: '修复图片预览', goal: 'Detailed requirements' }))).toBe('修复图片预览')
  expect(taskTopic(task({ title: 'Changed', initialIntent: { title: '制作无人机集群 PPT', goal: 'Original' }, goal: 'Additional steps' }))).toBe('制作无人机集群 PPT')
  expect(taskTopic(task({ goal: '在 /home/ai/codes/swarm 下制作《无人机集群（UAV Swarm）发展》PPT 并交付 .pptx。前序进展：很多细节' }))).toBe('制作《无人机集群发展》PPT')
  expect(taskTopic(task({ goal: '修复 Roami 图片附件显示缺陷并交付 PR。缺陷现象：完整详情' }))).toBe('修复 Roami 图片附件显示缺陷')
  expect(taskTopic({ id: 'private-id', intent_json: '{' } as AgentTask)).toBe('')
})
it('summarizes reports while keeping real PR links separate from ordinary sources', () => {
  const attempt = { id: 'run', revision: 1, state: 'succeeded', result: { summary: '全部完成，回报如下：\n\n## 修复图片预览\n\nPR: **https://github.com/ybz21/Roami/pull/336**\n来源：https://example.com/source' } }
  expect(taskOutcome(attempt)).toBe('修复图片预览')
  expect(taskReportLinks(attempt)).toEqual(['https://github.com/ybz21/Roami/pull/336'])
  expect(taskOutcome({ ...attempt, result: { summary: {} as string } })).toBe('')
  expect(taskReportLinks({ ...attempt, result: { summary: 42 as unknown as string } })).toEqual([])
})
