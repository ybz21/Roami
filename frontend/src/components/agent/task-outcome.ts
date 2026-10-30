import type { TaskAttempt } from './agent-task-protocol'

export function taskReportLinks(attempt?: TaskAttempt): string[] {
  const report = typeof attempt?.result?.summary === 'string' ? attempt.result.summary : ''
  return [...new Set(report.match(/https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/[1-9]\d*\b/g) || [])]
}

export function taskOutcome(attempt?: TaskAttempt): string {
  const report = typeof attempt?.result?.summary === 'string' ? attempt.result.summary : ''
  return taskReportSummary(report)
}

export function taskReportSummary(value: unknown): string {
  const report = typeof value === 'string' ? value : ''
  return report.replace(/```[\s\S]*?```/g, '').split(/\n\s*\n|\n/)
    .map(line => line.replace(/^\s{0,3}(?:#{1,6}\s+|[-*]\s+)/, '').replace(/!?(?:\[([^\]]*)\])\([^)]*\)/g, '$1').replace(/https?:\/\/\S+/g, '').replace(/[*`_]/g, '').trim())
    .find(line => line && !/^(?:全部完成[，,：:]?\s*回报如下[：:]?|回报如下[：:]?|根因[（(]|改动文件|验证结果|Summary|Changes|Validation|Results?[:：]?$)/i.test(line)) || ''
}
