import type { AgentTask } from './agent-protocol'
import { taskGoal } from './agent-task-protocol'

export function taskTopic(task: AgentTask): string {
  try {
    const intent = JSON.parse(task.intent_json), title = intent.initialIntent?.title || intent.title
    if (typeof title === 'string' && title.trim()) return title.replace(/\s+/g, ' ').trim()
  } catch { /* Legacy tasks derive their topic from the original goal. */ }
  const goal = taskGoal(task)
  if (goal === task.id) return ''
  const document = goal.match(/《([^》]+)》/)
  if (document && /ppt|幻灯片/i.test(goal)) {
    const action = goal.match(/审阅|评审|修改|修订|制作|生成|设计/)?.[0] || ''
    return action + '《' + document[1].replace(/（[^）]*）|\([^)]*\)/g, '').trim() + '》PPT'
  }
  return goal.replace(/（[^）]*）|\([^)]*\)/g, '')
    .replace(/https?:\/\/\S+|\/(?:[^\s，。；：]+\/)*[^\s，。；：]*/g, '')
    .replace(/^(?:继续|接续|续作)(?:完成|并收敛交付|上一次[^：:]*[:：])?\s*/, '')
    .split(/[\n。；：]|\.\s/)[0]
    .replace(/(?:并|，)(?:交付|提交).*$/, '')
    .replace(/\s+/g, ' ').trim() || goal.split('\n')[0]
}
