// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AgentImprovement from './AgentImprovement'
import zhCN from '../../i18n/locales/zh-CN'
import { api } from '../../api'

const state = vi.hoisted(() => ({ overview: null as any, detail: null as any, models: null as any, modelsFailed: false, refresh: vi.fn(), requests: [] as any[] }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('./useAgentData', () => ({ useAgentData: (path: string, fresh: number, poll: number) => { state.requests.push({ path, fresh, poll }); return { value: path?.includes('/pipeline/runs/') ? state.detail : path === '/agent/model-settings' ? state.models : state.overview, loading: false, failed: path === '/agent/model-settings' && state.modelsFailed, refresh: state.refresh } } }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', t: (key: string, vars: Record<string, string | number> = {}) => ((zhCN as Record<string, string>)[key] || key).replace(/\{(\w+)\}/g, (_, name) => String(vars[name])) }) }))
vi.mock('antd', () => ({
  ConfigProvider: ({ children }: any) => children,
  Button: ({ children, onClick, disabled }: any) => <button type="button" onClick={onClick} disabled={disabled}>{children}</button>,
  Switch: ({ checked, onChange, ...props }: any) => <input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} {...props} />,
  Input: (props: any) => <input {...props} />,
  InputNumber: ({ value, onChange, ...props }: any) => <input type="number" value={value} onChange={event => onChange?.(Number(event.target.value))} {...props} />,
  Select: ({ options = [], value, onChange, mode, ...props }: any) => <select {...props} multiple={mode === 'multiple'} value={value} onChange={event => onChange(mode === 'multiple' ? [...event.target.selectedOptions].map(option => option.value) : event.target.value)}>{options.map((option: any) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>,
  Spin: () => null,
}))
const id = 'a'.repeat(64), earlier = 'b'.repeat(64)
beforeEach(() => {
  state.modelsFailed = false; state.requests = []
  state.models = { gatewayManaged: true }
  state.overview = {
    preferences: { revision: 1, enabled: true, timezone: 'Asia/Shanghai', hour: 3, daily_tokens: 0, daily_episodes: 120, cases_per_day: 60, suite_id: 'formal', machine_ids: ['a'], auto_candidates: false, candidate_policy: {} },
    catalog: { machines: [{ id: 'a', label: 'A', mode: 'container' }], suites: [{ id: 'formal', count: 60 }] },
    pipeline: { settings: { revision: 1, auto_publish: false }, runs: [{ id, state: 'completed', created_ms: 2, mode: 'diagnostic' }] },
    research: { settings: { revision: 2, enabled: false, model_tokens: 64000, model_seconds: 180, max_attempts: 2, observation_days: 2, repo: '/trusted/source' } },
  }
  const definition = { id: 'CODE-01', name: '冻结的任务名称', description: '冻结的任务描述', group: 'authored' }
  const run = { id, sequence: 2, time: '2026-10-27 09:30', mode: 'quick', state: 'completed', rawState: 'completed', scope: ['CODE-01'], results: { 'CODE-01': 'passed' }, verified: [], source: 'source', suite: 'suite', judge: 'judge', models: 'models', machine: 'machine', caseDefinitions: [definition], workflow: Object.fromEntries(['evaluate', 'review', 'issue', 'repair', 'verify', 'publish', 'observe'].map(stage => [stage, { state: stage === 'evaluate' ? 'succeeded' : 'pending', artifacts: stage === 'evaluate' ? [{ id: 'artifact', name: 'actual-report.md' }] : [] }])) }
  state.detail = { runs: [{ ...run, id: earlier, sequence: 1, results: { 'CODE-01': 'failed' } }, run], cases: [definition], issues: [], history_complete: true }
  vi.mocked(api).mockImplementation(async (_method, path, payload: any) => ({ data: path.includes('/preferences') ? { ...payload, revision: 2 } : path.endsWith('/research') ? { ...payload, revision: 3 } : { id } }))
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('opens results and preserves seven actual workflow stages in another tab', () => {
  render(<AgentImprovement node={null} />)
  expect(screen.getByRole('tab', { name: '运行结果' }).getAttribute('aria-selected')).toBe('true')
  expect(screen.getByText('Case 汇总')).toBeTruthy()
  fireEvent.click(screen.getByRole('tab', { name: 'Issue' }))
  expect(screen.getByText('Issue 汇总')).toBeTruthy()
  expect(screen.queryByText('Case 汇总')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: '工作流' }))
  expect(screen.getByText('actual-report.md')).toBeTruthy()
  expect(screen.queryByText('verification-report.md')).toBeNull()
})
it('retains case display metadata and expanded lists across tabs', () => {
  render(<AgentImprovement node={null} />)
  fireEvent.click(screen.getByRole('button', { name: '展开 Case 明细' }))
  expect(screen.getByText('冻结的任务名称')).toBeTruthy()
  expect(screen.getByText('冻结的任务描述')).toBeTruthy()
  fireEvent.click(screen.getByRole('tab', { name: '工作流' }))
  fireEvent.click(screen.getByRole('tab', { name: '运行结果' }))
  expect(screen.getByText('冻结的任务名称')).toBeTruthy()
})
it('shows the model-page daily amount without RSI token fields', () => {
  render(<AgentImprovement node={null} />)
  fireEvent.click(screen.getByRole('button', { name: '设置' }))
  expect(screen.getByText('由模型网关管理')).toBeTruthy()
  expect(screen.queryByLabelText(/Token/)).toBeNull()
  expect(screen.queryByText(/每次准入预算/)).toBeNull()
})
it('retains failed input and retries without sending trusted source configuration', async () => {
  vi.mocked(api).mockRejectedValueOnce({ apiError: { code: 'RSI_SETTINGS_CONFLICT' } })
  render(<AgentImprovement node={null} />)
  fireEvent.click(screen.getByRole('button', { name: '设置' }))
  fireEvent.change(screen.getByLabelText('开始时间（小时）'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
  expect((screen.getByLabelText('开始时间（小时）') as HTMLInputElement).value).toBe('5')
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api).mock.calls[1][2]).toEqual(expect.objectContaining({ hour: 5 }))
  expect(vi.mocked(api).mock.calls[1][2]).not.toHaveProperty('repo')
})
it('does not poll ended details', () => {
  render(<AgentImprovement node={null} />)
  expect(state.requests.find(request => request.path?.includes('/pipeline/runs/')).poll).toBe(0)
})
it('does not show a missing model configuration as unlimited', () => {
  state.models = undefined; state.modelsFailed = true
  render(<AgentImprovement node={null} />)
  fireEvent.click(screen.getByRole('button', { name: '设置' }))
  expect(screen.queryByText('不限额')).toBeNull()
  expect(screen.getByText(zhCN['agent.rsi.loadFailed'])).toBeTruthy()
})
