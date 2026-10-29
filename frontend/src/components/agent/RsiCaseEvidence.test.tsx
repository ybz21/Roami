// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import RsiCaseEvidence from './RsiCaseEvidence'
import zh from '../../i18n/locales/zh-CN'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string, values: Record<string, unknown> = {}) => ((zh as Record<string, string>)[key] || key).replace(/\{(\w+)\}/g, (_, name) => String(values[name])) }) }))
afterEach(cleanup)
it('shows a real zero score and threshold without rounding away a failure', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { native_metric: 0, native_metric_minimum: 0.8, native_verifier_ran: true } }} />)
  expect(screen.getByText('0')).toBeTruthy(); expect(screen.getByText('0.8')).toBeTruthy()
})
it('does not show zero or reference comparisons for a verifier that never ran', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { native_metric: 0, native_metric_minimum: 1, native_verifier_ran: false, native_reference_results: [0, 0] } }} />)
  expect(screen.getByText('未完成判定')).toBeTruthy(); expect(screen.queryByText('原生评分')).toBeNull(); expect(screen.queryByText('备选参考结果')).toBeNull()
})
it('separates partial points, unscored points and reference results', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { native_reference_results: [0, 0], native_partial: { scored_points: 0, total_points: 8, unscored_points: 7 } } }} />)
  expect(screen.getByText('0 / 8')).toBeTruthy(); expect(screen.getByText('7 项未评分')).toBeTruthy(); expect(screen.getByText(/参考 1：0/)).toBeTruthy()
})
it('keeps paired arm scores separate', () => {
  render(<RsiCaseEvidence evidence={{ arm_results: { baseline: { native_judgment: { native_metric: 0.5 } }, candidate: { native_judgment: { native_metric: 0.75 } } } }} />)
  expect(within(screen.getByText('基线结果').parentElement!).getByText('0.5')).toBeTruthy()
  expect(within(screen.getByText('候选结果').parentElement!).getByText('0.75')).toBeTruthy()
})
it('keeps tools, files and unknown usage in execution details', () => {
  render(<RsiCaseEvidence evidence={{ metrics: { tokens: null, model_calls: 2 }, tools: [{ name: 'bash', state: 'failed', error: 'TOOL_FAILED' }], files: ['output.mp4'] }} />)
  const details = screen.getByText('执行记录').closest('details')!
  expect(details.open).toBe(false); expect(within(details).getByText('模型用量未知')).toBeTruthy(); expect(within(details).getByText('output.mp4')).toBeTruthy()
})
