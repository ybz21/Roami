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

it('keeps a partial reference unscored while displaying a genuine zero for its alternative', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { native_reference_results: [null, 0], native_verifier_ran: true } }} />)
  expect(screen.getByText(/参考 1：尚未评分/)).toBeTruthy()
  expect(screen.getByText(/参考 2：0/)).toBeTruthy()
  expect(screen.queryByText('原生评分')).toBeNull()
})

it('identifies post-timeout artifact scores without calling the run passed', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { artifact_assessment_after_timeout: true, native_metric: 1, native_metric_minimum: 1, native_verifier_ran: true } }} />)
  expect(screen.getByText('核验时机')).toBeTruthy()
  expect(screen.getByText('执行超时后（运行未通过）')).toBeTruthy()
  expect(screen.getByText('原生评分')).toBeTruthy()
})

it('keeps a failed timeout assessment unscored and its error in collapsed execution details', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { artifact_assessment_after_timeout: true, artifact_assessment_error: 'RSI_ARTIFACT_ASSESSMENT_TIMEOUT', native_metric: 0, native_verifier_ran: false } }} />)
  expect(screen.getByText('执行超时后（运行未通过）')).toBeTruthy()
  expect(screen.getByText('未完成判定')).toBeTruthy()
  expect(screen.queryByText('原生评分')).toBeNull()
  const details = screen.getByText('执行记录').closest('details')!
  expect(details.open).toBe(false)
  expect(within(details).getByText('RSI_ARTIFACT_ASSESSMENT_TIMEOUT')).toBeTruthy()
})

it('can show timeout assessment scope even when there is no valid score or metric', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { artifact_assessment_after_timeout: true } }} />)
  expect(screen.getByText('执行超时后（运行未通过）')).toBeTruthy()
  expect(screen.queryByText('原生评分')).toBeNull()
})

it('keeps normal evaluation and the other paired arm free of timeout labels', () => {
  render(<RsiCaseEvidence evidence={{ arm_results: { baseline: { native_judgment: { native_metric: 1 } }, candidate: { native_judgment: { artifact_assessment_after_timeout: true, native_metric: 1 } } } }} />)
  expect(within(screen.getByText('基线结果').parentElement!).queryByText('核验时机')).toBeNull()
  expect(within(screen.getByText('候选结果').parentElement!).getByText('执行超时后（运行未通过）')).toBeTruthy()
})

it('requires the boolean timeout flag before showing a timeout scope or error', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { artifact_assessment_after_timeout: 'true', artifact_assessment_error: 'RSI_ARTIFACT_ASSESSMENT_TIMEOUT', native_metric: 0.2 } }} />)
  expect(screen.queryByText('核验时机')).toBeNull()
  expect(screen.queryByText('RSI_ARTIFACT_ASSESSMENT_TIMEOUT')).toBeNull()
})

it('keeps an invalid public error out of the execution details', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { artifact_assessment_after_timeout: true, artifact_assessment_error: 'arbitrary upstream text' } }} />)
  expect(screen.getByText('执行超时后（运行未通过）')).toBeTruthy()
  expect(screen.queryByText('arbitrary upstream text')).toBeNull()
  expect(screen.queryByText('执行记录')).toBeNull()
})
