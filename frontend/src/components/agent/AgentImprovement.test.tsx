// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentImprovement from './AgentImprovement'
import zhCN from '../../i18n/locales/zh-CN'
import { api } from '../../api'

const state = vi.hoisted(() => ({ overview: null as any, refresh: vi.fn() }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('./useAgentData', () => ({ useAgentData: () => ({ value: state.overview, loading: false, failed: false, refresh: state.refresh }) }))
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
