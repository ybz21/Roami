// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentImprovement from './AgentImprovement'
import zhCN from '../../i18n/locales/zh-CN'
import { api } from '../../api'

const state = vi.hoisted(() => ({ overview: null as any, refresh: vi.fn(), detail: null as any }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('./useAgentData', () => ({ useAgentData: (path: string) => ({ value: path.includes('/pipeline/runs/') ? state.detail : state.overview, loading: false, failed: false, refresh: state.refresh }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', t: (key: string, vars: Record<string, string | number> = {}) => ((zhCN as Record<string, string>)[key] || key).replace(/\{(\w+)\}/g, (_, name) => String(vars[name])) }) }))
vi.mock('antd', () => ({
  Button: ({ children, onClick, disabled }: any) => <button type="button" onClick={onClick} disabled={disabled}>{children}</button>,
  Checkbox: ({ children, checked, onChange, ...props }: any) => <label><input type="checkbox" checked={checked} onChange={onChange} {...props} />{children}</label>,
  Switch: ({ checked, onChange, ...props }: any) => <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} {...props} />,
  Input: (props: any) => <input {...props} />,
  InputNumber: ({ value, onChange, ...props }: any) => <input type="number" value={value} onChange={e => onChange?.(Number(e.target.value))} {...props} />,
  Select: ({ options, value, onChange, mode: _mode }: any) => <select value={Array.isArray(value) ? value[0] : value} onChange={e => onChange(e.target.value)}>{options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>,
  Spin: () => null,
}))
afterEach(() => { cleanup(); vi.clearAllMocks() })

function overview(complete = true) {
  return {
    preferences: { revision: 1, enabled: false, timezone: 'Asia/Shanghai', hour: 3, daily_tokens: 0, daily_episodes: 120, cases_per_day: 4, suite_id: 'formal', machine_ids: ['a'], auto_candidates: true, candidate_policy: {} },
    catalog: { machines: [{ id: 'a', label: 'A', mode: 'container' }], suites: [{ id: 'formal', count: 60, splits: { development: 60 } }] },
    requests: [], releases: { seq: 0, active: null, history: [] },
    cycles: [{ id: 'cycle', day: '2026-10-23', state: 'completed', machine_id: 'a', report: { review: { complete, expected_trials: 120, metrics_reviewed: 120, logs_reviewed: complete ? 120 : 119 } } }],
  }
}
it('shows a fixed full daily suite and saves 60 even when old cached preferences said four', async () => {
  state.overview = overview()
  vi.mocked(api).mockResolvedValue({ data: {} })
  render(<AgentImprovement node={null} />)
  const count = await screen.findByLabelText('每日完整评测（项）') as HTMLInputElement
  expect(count.value).toBe('60')
  expect(count.readOnly).toBe(true)
  fireEvent.change(screen.getByLabelText('开始时间（小时）'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/improvement/preferences', expect.objectContaining({ cases_per_day: 60, hour: 5 })))
})
it.each([true, false])('shows exact metric and log review coverage (complete=%s)', async complete => {
  state.overview = overview(complete)
  render(<AgentImprovement node={null} />)
  fireEvent.click(await screen.findByRole('button', { name: /2026/ }))
  expect(screen.getByText(`指标 120/120，日志 ${complete ? 120 : 119}/120。`, { exact: false })).toBeTruthy()
  expect(screen.getByText(complete ? /回顾完成/ : /回顾尚不完整/)).toBeTruthy()
})
it('shows observation as pending and keeps recovery actions in execution records', async () => {
  state.overview = { ...overview(), research: { settings: { enabled: true }, improvements: [{ id: 'issue', title: '重复读取未变化文件', state: 'observing' }], actions: [{ id: 'step', kind: 'verify', state: 'waiting_budget', error_code: 'RSI_DAILY_BUDGET' }] } }
  vi.mocked(api).mockResolvedValue({ data: {} })
  render(<AgentImprovement node={null} />)
  expect(await screen.findByText('重复读取未变化文件')).toBeTruthy()
  expect(screen.getByText('观察中')).toBeTruthy()
  expect(screen.queryByText('已验证修复')).toBeNull()
  fireEvent.click(screen.getByText('执行记录'))
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/improvement/research/step/resume', undefined))
})


it('links a published draft while preserving its pending observation state', () => {
  state.overview = { ...overview(), research: { settings: { enabled: true }, actions: [], improvements: [{ id: 'i', title: 'Observed behavior', state: 'observing', reviewUrl: 'https://github.com/example/rsi-test/pull/1' }] } }
  render(<AgentImprovement node={null} />)
  const link = screen.getByRole('link', { name: '查看 PR' })
  expect(link.getAttribute('href')).toBe('https://github.com/example/rsi-test/pull/1')
  expect(link.getAttribute('rel')).toContain('noopener')
  expect(screen.getByText('Observed behavior')).toBeTruthy()
})

it('keeps a full daily suite and links the aggregated Issue with a private report', async () => {
  state.overview = { ...overview(), research: { settings: { enabled: true }, actions: [{ id: 'issue-role', kind: 'issue', state: 'done', error_code: null }], improvements: [], reports: [{ cycle_id: 'period-test', day: '2026-10-24', points: 2, issueUrl: 'https://github.com/example/rsi-test/issues/3' }] } }
  vi.mocked(api).mockResolvedValue({ data: { review_document: '# Codex 复盘\n\n本轮完整证据。' } })
  render(<AgentImprovement node={null} />)
  expect((await screen.findByLabelText('每日完整评测（项）') as HTMLInputElement).value).toBe('60')
  const issue = screen.getByRole('link', { name: '查看 Issue' })
  expect(issue.getAttribute('href')).toBe('https://github.com/example/rsi-test/issues/3')
  expect(issue.getAttribute('rel')).toContain('noopener')
  fireEvent.click(screen.getByText('完整复盘'))
  fireEvent.click(screen.getByRole('button', { name: '读取复盘' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('GET', '/agent/improvement/cycles/period-test'))
  expect(await screen.findByText('本轮完整证据。')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('开始时间（小时）'), { target: { value: '4' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/improvement/preferences', expect.objectContaining({ hour: 4, cases_per_day: 60 })))
})

function workflowOverview() {
  return { ...overview(), research: { settings: { revision: 2, enabled: false, model_tokens: 64000, model_seconds: 180, max_attempts: 2, observation_days: 2, repo: '/trusted' }, actions: [{ id: 'review-a', kind: 'review', state: 'blocked', error_code: 'RSI_USAGE_UNKNOWN' }], improvements: [], reports: [{ cycle_id: 'daily-a', day: '2026-10-24', points: 1, issueUrl: 'https://github.com/example/repo/issues/1' }] } }
}
it('configures a selected workflow node without sending trusted source targets', async () => {
  state.overview = workflowOverview()
  vi.mocked(api).mockResolvedValue({ data: {} })
  render(<AgentImprovement node="a" workflow />)
  expect(screen.getAllByRole('button', { pressed: false }).length).toBeGreaterThan(5)
  fireEvent.click(screen.getByRole('button', { name: /2 复盘/ }))
  expect(screen.getByText('Codex 逐项回顾指标、调用过程和日志，生成每日复盘文档。')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Codex 每次准入预算（Token）'), { target: { value: '32000' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/improvement/research', { revision: 2, enabled: false, model_tokens: 32000, model_seconds: 180, max_attempts: 2, observation_days: 2 }))
})
it('previews admission without enqueueing work and keeps daily issue access in its own tab', async () => {
  state.overview = workflowOverview()
  vi.mocked(api).mockResolvedValue({ data: { cases: 60, machines: 1, episodes: 120, reservation_tokens: null, next_run: null, codex_tokens_per_operation: 64000, blockers: ['RSI_ARTIFACT_REVIEW_REQUIRED'] } })
  render(<AgentImprovement node="a" workflow />)
  fireEvent.click(screen.getByRole('button', { name: '预览运行' }))
  await screen.findByText('最多执行数（基线与候选）')
  expect(api).toHaveBeenCalledWith('POST', '/agent/improvement/preview')
  expect(vi.mocked(api).mock.calls.some(call => call[1].includes('/requests'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: '每日 Issue' }))
  expect(screen.getByRole('link', { name: '查看 Issue' }).getAttribute('href')).toBe('https://github.com/example/repo/issues/1')
  expect(screen.queryByText('每日评测')).toBeNull()
})
it('preserves failed configuration input and invalidates the preview when edited', async () => {
  state.overview = workflowOverview()
  vi.mocked(api).mockRejectedValue({ apiError: { code: 'RSI_SETTINGS_CONFLICT' } })
  render(<AgentImprovement node="a" workflow />)
  fireEvent.click(screen.getByRole('button', { name: /4 修复/ }))
  fireEvent.change(screen.getByLabelText('每个问题最多修复次数'), { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('每个问题最多修复次数') as HTMLInputElement).value).toBe('3')
  fireEvent.click(screen.getByRole('button', { name: /1 评测/ }))
  expect((screen.getByRole('button', { name: '预览运行' }) as HTMLButtonElement).disabled).toBe(true)
})

it('reuses the same manual request key after a partial multi-machine failure', async () => {
  state.overview = { ...workflowOverview(), preferences: { ...workflowOverview().preferences, daily_tokens: 100000, machine_ids: ['a', 'b'] } }
  vi.mocked(api).mockResolvedValueOnce({ data: {} }).mockRejectedValueOnce({ apiError: { code: 'RSI_OPERATION_FAILED' } }).mockResolvedValue({ data: {} })
  render(<AgentImprovement node="a" workflow />)
  fireEvent.click(screen.getByRole('button', { name: '运行一次' }))
  await screen.findByRole('alert')
  const requestKey = vi.mocked(api).mock.calls[0][2].request_key
  fireEvent.click(screen.getByRole('button', { name: '运行一次' }))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(4))
  expect(vi.mocked(api).mock.calls.every(call => call[2].request_key === requestKey)).toBe(true)
})

it('stops enqueueing remaining machines when the experiment page is unmounted', async () => {
  state.overview = { ...workflowOverview(), preferences: { ...workflowOverview().preferences, daily_tokens: 100000, machine_ids: ['a', 'b'] } }
  let finish!: (value: any) => void
  vi.mocked(api).mockReturnValue(new Promise(resolve => { finish = resolve }))
  const page = render(<AgentImprovement node="a" workflow />)
  fireEvent.click(screen.getByRole('button', { name: '运行一次' }))
  expect(api).toHaveBeenCalledTimes(1)
  page.unmount()
  finish({ data: {} })
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(api).toHaveBeenCalledTimes(1)
})

it('opens a run deep link on first mount without resetting to workflow', async () => {
  state.overview = { ...overview(), pipeline: { settings: { revision: 0, auto_publish: false, daily_tokens: 1000000, generation_tokens: 300000, codex_tokens: 64000, output_tokens: 8192, memory_output_tokens: 2048 }, runs: [], issues: [] } }
  state.detail = { id: 'saved-run', mode: 'diagnostic', state: 'completed', created_ms: 1, updated_ms: 1, summary: {}, issue: null, snapshot: { case_ids: [] }, nodes: [], cases: [], artifacts: [], issues: [] }
  render(<AgentImprovement node={null} workflow runId="saved-run" />)
  expect(await screen.findByRole('button', { name: '复测同组 Case' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '诊断 10 项' })).toBeNull()
})
