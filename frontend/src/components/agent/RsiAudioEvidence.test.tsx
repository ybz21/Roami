// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import receipt from '../../../../cases/case-70-mech-md01/input/native-receipt.json'
import zh from '../../i18n/locales/zh-CN'
import RsiCaseEvidence from './RsiCaseEvidence'

vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', t: (key: string) => (zh as Record<string, string>)[key] || key }) }))
afterEach(cleanup)
const native = () => ({ native_metric: receipt.reward, native_metric_minimum: 0.8, native_verifier_ran: true, grade_scope: 'original_media_verifier_plus_frozen_delivery_checks', native_audio_diagnostic: { in_window_reward: receipt.in_window_reward, out_window_reward: receipt.out_window_reward, ...receipt.details } })

it('shows region scores first and expands actual Case70 metrics without publishing reference fields', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: native() }} />)
  expect(screen.getByText('0.595')).toBeTruthy()
  expect(screen.getByText('修复区得分')).toBeTruthy()
  expect(screen.getByText('0.55')).toBeTruthy()
  expect(screen.getByText('保留区得分')).toBeTruthy()
  const details = screen.getByText('音频指标').closest('details')!
  expect(details.open).toBe(false)
  fireEvent.click(within(details).getByText('音频指标'))
  expect(details.open).toBe(true)
  expect(within(details).getByText('PESQ')).toBeTruthy()
  expect(within(details).getByText('0.45')).toBeTruthy()
  expect(document.body.textContent).not.toContain('PRIVATE_')
  expect(document.body.textContent).not.toContain('private_start')
  expect(document.body.textContent).not.toContain('dnsmos_ref_ovl')
})

it('keeps zero distinct from unavailable and rejects nonfinite, boolean or string measurements', () => {
  const value = native()
  const audio = { in_window_reward: 0, out_window_reward: null, in_window: { pesq_wb: NaN, stoi: '0.9', lsd_full: Infinity, f0_corr: true }, out_window: { out_n_samples: 32000 } }
  render(<RsiCaseEvidence evidence={{ native_judgment: { ...value, native_audio_diagnostic: audio } }} />)
  expect(screen.getByText('0')).toBeTruthy()
  expect(screen.getAllByText('不可用')).toHaveLength(5)
  expect(document.body.textContent).not.toMatch(/NaN|Infinity|true/)
})

it.each([false, undefined, 'true'])('hides stale components without a completed native verdict (%s)', ran => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { ...native(), native_verifier_ran: ran } }} />)
  expect(screen.queryByText('修复区得分')).toBeNull()
  expect(screen.queryByText('音频指标')).toBeNull()
})

it('does not attach audio components to another evaluator or invent missing metrics', () => {
  const { rerender } = render(<RsiCaseEvidence evidence={{ native_judgment: { ...native(), grade_scope: 'another_evaluator' } }} />)
  expect(screen.queryByText('音频指标')).toBeNull()
  rerender(<RsiCaseEvidence evidence={{ native_judgment: { ...native(), native_audio_diagnostic: { in_window_reward: 0.55 } } }} />)
  expect(screen.getByText('修复区得分')).toBeTruthy()
  expect(screen.queryByText('音频指标')).toBeNull()
  expect(screen.queryByText('保留区得分')).toBeNull()
})

it('does not round a small nonzero score or a score below one into a misleading endpoint', () => {
  render(<RsiCaseEvidence evidence={{ native_judgment: { ...native(), native_audio_diagnostic: { in_window_reward: 1e-14, out_window_reward: 0.9999999999999999 } } }} />)
  expect(screen.getByText(/E-14/)).toBeTruthy()
  expect(screen.getByText('0.9999999999999999')).toBeTruthy()
  expect(screen.queryByText('0')).toBeNull()
  expect(screen.queryByText('1')).toBeNull()
})

it('keeps the two comparison arms independent', () => {
  render(<RsiCaseEvidence evidence={{ arm_results: { baseline: { native_judgment: native() }, candidate: { native_judgment: { ...native(), native_audio_diagnostic: { in_window_reward: 0.6 } } } } }} />)
  const baseline = screen.getByText('基线结果').parentElement!, candidate = screen.getByText('候选结果').parentElement!
  expect(within(baseline).getByText('0.55')).toBeTruthy()
  expect(within(candidate).getByText('0.6')).toBeTruthy()
  expect(within(candidate).queryByText('0.55')).toBeNull()
})
