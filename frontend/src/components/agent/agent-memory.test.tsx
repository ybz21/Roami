// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentMemory from './AgentMemory'
import { api } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <div>{children}</div> }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: vi.fn() }, modal: { confirm: vi.fn() } }) },
  Button: ({ children, loading: _loading, danger: _danger, ...props }: any) => <button {...props}>{children}</button>,
  Input: Object.assign((props: any) => <input {...props} />, { Search: (props: any) => <input {...props} /> }),
  Dropdown: ({ children }: any) => children,
  Tabs: ({ items, activeKey, onChange }: any) => <div role="tablist">{items.map((item: any) => <button type="button" role="tab" key={item.key} aria-selected={item.key === activeKey} onClick={() => onChange(item.key)}>{item.label}</button>)}</div>,
  Modal: ({ open, children }: any) => open ? <div role="dialog">{children}</div> : null,
  Select: ({ options, onChange, ...props }: any) => <select {...props} onChange={(e) => onChange(e.target.value)}>{options.map((option: any) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>,
  Spin: () => <span role="progressbar" />,
}))
afterEach(() => { cleanup(); vi.resetAllMocks() })

it('ignores a late memory response after changing conversations, even if transport ignores abort', async () => {
  let finishOld!: (value: any) => void
  const old = new Promise((resolve) => { finishOld = resolve })
  let oldSignal: AbortSignal | undefined
  vi.mocked(api).mockImplementation(async (_method, path, _body, options) => {
    if (path === '/agent/status') return { data: { memoryTimezone: 'UTC' } }
    if (path.startsWith('/agent/tasks')) return { data: [] }
    if (path.includes('conversationId=old')) { oldSignal = options?.signal; return old }
    return { data: { items: [{ id: 'new-memory', title: 'Current memory', body: 'Current fact', state: 'active' }], total: 1 } }
  })
  const view = render(<AgentMemory cid="old" projects={[]} select={vi.fn()} />)
  await waitFor(() => expect(oldSignal).toBeDefined())
  view.rerender(<AgentMemory cid="new" projects={[]} select={vi.fn()} />)
  await screen.findByText('Current fact')
  expect(oldSignal?.aborted).toBe(true)
  await act(async () => { finishOld({ data: { items: [{ id: 'old-memory', title: 'Previous memory', body: 'Previous fact', state: 'active' }], total: 1 } }); await old })
  expect(screen.queryByText('Previous fact')).toBeNull()
  expect(screen.getByText('Current fact')).toBeTruthy()
  expect(screen.queryByRole('progressbar')).toBeNull()
})

it('opens the owner-wide catalog, paginates and resets pagination when searching or filtering', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/status') return { data: { memoryTimezone: 'UTC' } }
    const params = new URLSearchParams(path.split('?')[1])
    const next = params.get('offset') === '20'
    return { data: { items: [{ id: 'memory', title: next ? 'Older memory' : 'Personal preference', body: 'Use concise replies', state: 'active', kind: 'preference', source_count: 1 }], total: 21 } }
  })
  render(<AgentMemory fullPage projects={[]} select={vi.fn()} />)
  await screen.findByText('Personal preference')
  let path = vi.mocked(api).mock.calls.filter(call => call[1].includes('/catalog?')).slice(-1)[0]![1]
  expect(path).not.toContain('conversationId=')
  expect(screen.getByText('agent.memoryGroup.personal', { selector: 'span' })).toBeTruthy()
  fireEvent.click(screen.getByText('agent.memoryNext'))
  await screen.findByText('Older memory')
  expect(vi.mocked(api).mock.calls.slice(-1)[0]![1]).toContain('offset=20')
  fireEvent.change(screen.getByLabelText('agent.searchMemory'), { target: { value: 'concise' } })
  await screen.findByText('Personal preference')
  path = vi.mocked(api).mock.calls.slice(-1)[0]![1]
  expect(path).toContain('offset=0')
  expect(path).toContain('query=concise')
  fireEvent.change(screen.getByLabelText('agent.memoryGroup'), { target: { value: 'personal' } })
  await waitFor(() => expect(vi.mocked(api).mock.calls.slice(-1)[0]![1]).toContain('personalOnly=true'))
})

it('opens the exact source message of a personal memory and keeps the management entry available in chat', async () => {
  const select = vi.fn()
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/status') return { data: { memoryTimezone: 'UTC' } }
    if (path.startsWith('/agent/tasks')) return { data: [] }
    if (path.endsWith('/sources')) return { data: [{ sourceKey: 'source-message', text: 'Original user preference', conversationId: 'source-conversation', branchId: 'source-branch', messageId: 'source-message', kind: 'message' }] }
    return { data: { items: [{ id: 'personal', title: 'Preference', body: 'Concise replies', state: 'active' }], total: 1 } }
  })
  render(<AgentMemory cid="current" projects={[]} select={select} />)
  expect(screen.getByRole('link', { name: 'agent.memoryCenter' }).getAttribute('href')).toBe('#/settings/agent/memory')
  fireEvent.click(await screen.findByText('agent.memorySources'))
  await screen.findByText('Original user preference')
  fireEvent.click(screen.getByText('agent.memoryOpenSource'))
  expect(select).toHaveBeenCalledWith('source-conversation', 'source-branch', 'source-message')
})

it('keeps reusable memories separate from daily counts and resets the server page when switching views', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path === '/agent/status') return { data: { memoryTimezone: 'UTC' } }
    const daily = new URLSearchParams(path.split('?')[1]).get('category') === 'activity'
    return { data: { items: daily ? [{ id: 'daily', title: 'Daily counters', body: JSON.stringify({ scopeKey: 'unassigned', counts: { userTurns: 31, tasksCreated: 6 } }), state: 'active', kind: 'summary', day_key: '2026-10-18', source_count: 4 }] : [{ id: 'preference', title: 'Writing preference', body: 'Use concise replies', state: 'active', kind: 'preference', source_count: 1 }], total: daily ? 1 : 21 } }
  })
  render(<AgentMemory fullPage projects={[]} select={vi.fn()} />)
  await screen.findByText('Writing preference')
  expect(vi.mocked(api).mock.calls.filter(call => call[1].includes('/catalog?')).pop()![1]).toContain('category=knowledge')
  expect(screen.queryByText('Daily counters')).toBeNull()
  fireEvent.click(screen.getByText('agent.memoryNext'))
  await waitFor(() => expect(vi.mocked(api).mock.calls.slice(-1)[0]![1]).toContain('offset=20'))
  fireEvent.click(screen.getByRole('tab', { name: 'agent.memoryView.activity' }))
  await screen.findByText('31')
  expect(screen.queryByText('Writing preference')).toBeNull()
  expect(screen.getByText('2026-10-18')).toBeTruthy()
  const params = new URLSearchParams(vi.mocked(api).mock.calls.slice(-1)[0]![1].split('?')[1])
  expect(params.get('category')).toBe('activity'); expect(params.get('offset')).toBe('0')
  expect(screen.getAllByText('agent.memoryCountUnknown')).toHaveLength(4)
})
