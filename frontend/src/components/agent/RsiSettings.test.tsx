// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { RsiSettings } from './RsiSettings'
import { api } from '../../api'
import zhCN from '../../i18n/locales/zh-CN'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', t: (key: string, vars: Record<string, string | number> = {}) => ((zhCN as Record<string, string>)[key] || key).replace(/\{(\w+)\}/g, (_, name) => String(vars[name])) }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const value: any = {
  preferences: { revision: 1, enabled: false, timezone: 'Asia/Shanghai', hour: 3, daily_tokens: 0, daily_episodes: 0, cases_per_day: 4, suite_id: 'formal', machine_ids: ['a'], auto_candidates: true, candidate_policy: {} },
  catalog: { machines: [{ id: 'a', label: 'A', mode: 'container' }], suites: [{ id: 'formal', count: 60, splits: {} }] },
  pipeline: { settings: { revision: 3, auto_publish: false, daily_tokens: 1000000, generation_tokens: 300000, codex_tokens: 64000, output_tokens: 8192, memory_output_tokens: 2048 }, runs: [], issues: [] },
  research: { settings: { revision: 2, enabled: false, model_tokens: 64000, model_seconds: 180, max_attempts: 2, observation_days: 2 }, actions: [], improvements: [] },
  requests: [], cycles: [], releases: { seq: 0, active: null, history: [] },
}

it('omits independent budgets and output caps while preserving optional model overrides', async () => {
  vi.mocked(api).mockImplementation(async (_method, _path, body: any) => ({ data: { ...body, revision: body.revision + 1 } }))
  render(<RsiSettings value={value} refresh={vi.fn()} onDirtyChange={vi.fn()} />)
  expect(screen.queryByLabelText('每日 Token 准入预算')).toBeNull()
  expect(screen.queryByLabelText('每次诊断生成预算')).toBeNull()
  expect(screen.queryByLabelText('主 Agent 单次输出额度')).toBeNull()
  fireEvent.click(screen.getByText('独立模型（可选）'))
  fireEvent.change(screen.getByLabelText('主 Agent 模型'), { target: { value: 'custom-main' } })
  fireEvent.change(screen.getByLabelText('记忆模型'), { target: { value: 'memory-model' } })
  fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/improvement/pipeline/settings', { revision: 3, auto_publish: false, main_model: 'custom-main', memory_model: 'memory-model' }))
})

it('saves schedule, automation and research through one action without sending token settings', async () => {
  vi.mocked(api).mockImplementation(async (_method, _path, body: any) => ({ data: { ...body, revision: body.revision + 1 } }))
  const refresh = vi.fn()
  render(<RsiSettings value={value} refresh={refresh} onDirtyChange={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('开始时间（小时）'), { target: { value: '4' } })
  fireEvent.click(screen.getByRole('switch', { name: '运行后自动提 GitHub Issue' }))
  fireEvent.click(screen.getByRole('switch', { name: '自动复盘、提 Issue 和修复' }))
  fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(3))
  expect(vi.mocked(api).mock.calls.map(call => call[1])).toEqual(['/agent/improvement/preferences', '/agent/improvement/pipeline/settings', '/agent/improvement/research'])
  for (const call of vi.mocked(api).mock.calls) expect(Object.keys(call[2])).not.toEqual(expect.arrayContaining(['daily_tokens']))
  expect(vi.mocked(api).mock.calls[0][2]).toMatchObject({ cases_per_day: 60, hour: 4 })
  expect(vi.mocked(api).mock.calls[2][2]).toEqual({ revision: 2, enabled: true, max_attempts: 2, observation_days: 2 })
  await waitFor(() => expect(refresh).toHaveBeenCalled())
})

it('retains the input and accepted revision after a partial failure and ignores stale refresh data', async () => {
  let failed = false
  vi.mocked(api).mockImplementation(async (_method, path, body: any) => {
    if (path.endsWith('/pipeline/settings') && !failed) { failed = true; throw { apiError: { code: 'RSI_SETTINGS_CONFLICT' } } }
    return { data: { ...body, revision: body.revision + 1 } }
  })
  const props = { value, refresh: vi.fn(), onDirtyChange: vi.fn() }, page = render(<RsiSettings {...props} />)
  fireEvent.change(screen.getByLabelText('开始时间（小时）'), { target: { value: '4' } })
  fireEvent.click(screen.getByText('独立模型（可选）'))
  fireEvent.change(screen.getByLabelText('主 Agent 模型'), { target: { value: 'retain-model' } })
  fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('主 Agent 模型') as HTMLInputElement).value).toBe('retain-model')
  fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))
  await waitFor(() => expect(props.refresh).toHaveBeenCalled())
  expect(vi.mocked(api).mock.calls.filter(call => call[1].endsWith('/preferences'))).toHaveLength(1)
  expect(vi.mocked(api).mock.calls.filter(call => call[1].endsWith('/pipeline/settings'))).toHaveLength(2)
  page.rerender(<RsiSettings {...props} value={{ ...value }} />)
  expect((screen.getByLabelText('开始时间（小时）') as HTMLInputElement).value).toBe('4')
  expect((screen.getByLabelText('主 Agent 模型') as HTMLInputElement).value).toBe('retain-model')
})
