// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import PipelineRuns from './PipelineRuns'
import zhCN from '../../i18n/locales/zh-CN'
import { api } from '../../api'

const state = vi.hoisted(() => ({ detail: null as any, refresh: vi.fn() }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('./useAgentData', () => ({ useAgentData: () => ({ value: state.detail, loading: false, refresh: state.refresh }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', t: (key: string, vars: Record<string, string | number> = {}) => ((zhCN as Record<string, string>)[key] || key).replace(/\{(\w+)\}/g, (_, name) => String(vars[name])) }) }))
vi.mock('antd', () => ({ Input: (props: any) => <input {...props} />, Select: ({ value, options, onChange }: any) => <select value={value} onChange={e => onChange(e.target.value)}>{options.map((option: any) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>, Button: ({ children, loading: _loading, ...props }: any) => <button {...props}>{children}</button>, InputNumber: ({ value, onChange, ...props }: any) => <input type="number" value={value ?? ''} onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))} {...props} />, Switch: ({ checked, onChange, ...props }: any) => <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} {...props} />, Spin: () => null }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <div>{children}</div> }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const settings = { revision: 3, auto_publish: false, daily_tokens: 1000000, generation_tokens: 300000, codex_tokens: 64000, output_tokens: 8192, memory_output_tokens: 2048 }
const data = { settings, runs: [], issues: [], publication: { repository: 'example/test' } }

it('renders one run with isolated stages and never labels an unverified issue fixed', async () => {
  state.detail = { id: 'run', mode: 'diagnostic', state: 'completed', created_ms: 1, updated_ms: 2, summary: { generation_tokens: null }, issue: null, snapshot: { case_ids: ['a'] }, nodes: [{ node: 'evaluate', attempt: 1, state: 'succeeded', config: {}, error_code: null }, { node: 'review', attempt: 1, state: 'blocked', config: {}, error_code: 'RSI_USAGE_UNKNOWN' }], cases: [{ case_id: 'a', state: 'blocked', kind: 'task', passed: false, quality: 0, metrics: { tokens: null }, signals: ['RSI_USAGE_UNKNOWN'], tool_calls: 0 }], artifacts: [], issues: [{ id: 'i', case_id: 'a', code: 'WORKSPACE_REQUIRED', status: 'unverified' }] }
  const navigate = vi.fn()
  vi.mocked(api).mockResolvedValue({ data: { id: 'second' } })
  render(<PipelineRuns data={data} view="runs" runId="run" node={null} onRun={navigate} refresh={() => {}} eligible />)
  expect(screen.getByText('未验证')).toBeTruthy()
  expect(screen.queryByText('已修复')).toBeNull()
  expect(screen.getByText('0/1')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '复测同组 Case' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/improvement/pipeline/requests', expect.objectContaining({ baseline_run: 'run' })))
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('second'))
})
