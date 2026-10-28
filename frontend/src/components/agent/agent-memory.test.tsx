// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AgentMemory from './AgentMemory'
import { api } from '../../api'
import { clearAgentDataCache } from './agent-data-cache'
import type { MemoryRecord } from './memory-record'

const mocks = vi.hoisted(() => ({ confirm: vi.fn(), success: vi.fn(), error: vi.fn(), layout: { phone: false } }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => mocks.layout }))
vi.mock('../MobileSubPage', () => ({ default: ({ title, onBack, children, action }: any) => <div data-mobile-page><header><button aria-label="common.back" onClick={onBack}>common.back</button>{title}{action && <button aria-label={action.label} onClick={action.onClick}>{action.icon}</button>}</header>{children}</div> }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <div>{children}</div> }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: mocks.error, success: mocks.success }, modal: { confirm: mocks.confirm } }) },
  Button: ({ children, loading: _loading, danger: _danger, type: _type, ...props }: any) => <button {...props}>{children}</button>,
  Input: ({ prefix: _prefix, allowClear: _clear, ...props }: any) => <input {...props} />,
  Dropdown: ({ children, menu }: any) => <div>{children}<div role="menu">{menu.items.map((item: any) => <button role="menuitem" key={item.key} onClick={() => menu.onClick({ key: item.key })}>{item.label}</button>)}</div></div>,
  Select: ({ options, onChange, showSearch: _search, optionFilterProp: _filter, loading: _loading, ...props }: any) => <select {...props} onChange={event => onChange(event.target.value)}>{options.map((option: any) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>,
  Spin: () => <span role="progressbar" />,
  Skeleton: () => <span role="progressbar" />,
}))
const record = (id = 'memory', patch: Partial<MemoryRecord> = {}): MemoryRecord => ({ id, title: 'Remembered preference', body: 'Use concise replies', state: 'active', kind: 'preference', updated_ms: 1760000000000, ...patch })
const evidence = [{ sourceKey: 'source', text: 'Original user preference', available: true, unchanged: true, conversationTitle: 'Original conversation', conversationId: 'source-conversation', branchId: 'source-branch', messageId: 'source-message' }]
function install(records = [record()], overrides?: (method: string, path: string, body?: any, opts?: any) => unknown) {
  vi.mocked(api).mockImplementation(async (method, path, body, opts) => {
    const override = overrides?.(method, path, body, opts)
    if (override !== undefined) return override as any
    if (path === '/agent/status') return { data: { memoryTimezone: 'UTC' } }
    if (path.startsWith('/agent/memories/facets?')) return { data: { project: [], conversation: [], task: [], reviewCount: 0 } }
    if (path.endsWith('/history')) return { data: { items: [], truncated: false } }
    if (path.endsWith('/detail')) { const item = records.find(item => path.includes('/' + item.id + '/')); return { data: { record: item, evidence, current: null, canConfirm: item?.state !== 'active' } } }
    if (path.startsWith('/agent/memories/catalog?')) return { data: { items: records, total: records.length, limit: 20, offset: 0 } }
    return { data: {} }
  })
}
const rows = () => document.querySelectorAll<HTMLButtonElement>('.memory-row')
const detail = () => within(screen.getByRole('region', { name: 'agent.memoryBrowse.detail' }))
beforeEach(() => { history.replaceState({}, '', '#/home/memory/home'); mocks.layout.phone = false; clearAgentDataCache(); vi.clearAllMocks() })
afterEach(() => { cleanup(); clearAgentDataCache(); vi.resetAllMocks(); history.replaceState({}, '', '#/home') })

it('ignores a late list response after changing conversation without showing it in the new scope', async () => {
  let finish!: (value: any) => void
  const old = new Promise(resolve => { finish = resolve })
  install([record('new', { title: 'Current memory', body: 'Current fact' })], (_method, path) => path.includes('conversationId=old') ? old : undefined)
  const view = render(<AgentMemory cid="old" defaultGroup="conversation" projects={[]} select={vi.fn()} />)
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1].includes('conversationId=old'))).toBe(true))
  view.rerender(<AgentMemory cid="new" defaultGroup="conversation" projects={[]} select={vi.fn()} />)
  await screen.findByText('Current fact')
  await act(async () => { finish({ data: { items: [record('old', { body: 'Previous fact' })], total: 1 } }); await old })
  expect(screen.queryByText('Previous fact')).toBeNull()
})

it('defaults to all scopes and keeps types separate, with server pagination reset on search', async () => {
  install(undefined, (_method, path) => {
    if (!path.includes('/catalog?')) return
    const older = new URLSearchParams(path.split('?')[1]).get('offset') === '20'
    return { data: { items: [record('memory', { title: older ? 'Older memory' : 'Personal preference' })], total: 21 } }
  })
  render(<AgentMemory fullPage cid="current" projects={[]} select={vi.fn()} />)
  await screen.findByText('Personal preference')
  expect(vi.mocked(api).mock.calls.filter(call => call[1].includes('/catalog?')).pop()![1]).not.toContain('conversationId=')
  fireEvent.click(screen.getByRole('button', { name: 'agent.memoryNext' }))
  await screen.findByText('Older memory')
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'concise' } })
  await screen.findByText('Personal preference')
  expect(location.hash).toContain('memoryQuery=concise')
  fireEvent.change(screen.getByLabelText('agent.memoryBrowse.scope'), { target: { value: 'personal' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.memoryBrowse.filters' }))
  fireEvent.change(screen.getByLabelText('agent.memoryBrowse.type'), { target: { value: 'preference' } })
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1].includes('scope=personal') && call[1].includes('kind=preference') && call[1].includes('offset=0'))).toBe(true))
})

it('uses the combined review endpoint and human-readable scope facets', async () => {
  const candidate = record('candidate', { title: 'Proposed memory', state: 'candidate', task_id: 'task-id', task_title: 'Readable task' })
  install([candidate], (_method, path) => path.includes('/facets?') ? { data: { project: [], conversation: [], task: [{ id: 'task-id', name: 'Readable task' }], reviewCount: 1 } } : undefined)
  render(<AgentMemory fullPage projects={[]} select={vi.fn()} />)
  await screen.findByText('Proposed memory')
  fireEvent.click(screen.getByRole('tab', { name: /agent.memoryBrowse.review/ }))
  fireEvent.change(screen.getByLabelText('agent.memoryBrowse.scope'), { target: { value: 'task' } })
  await screen.findByRole('option', { name: 'Readable task' })
  fireEvent.change(screen.getByLabelText('agent.memoryGroup.task'), { target: { value: 'task-id' } })
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1].includes('state=review') && call[1].includes('taskId=task-id'))).toBe(true))
  expect(screen.getByRole('option', { name: 'Readable task' })).toBeTruthy()
})

it('loads full content and original source on selection, with history only loaded on demand', async () => {
  const select = vi.fn()
  install()
  render(<AgentMemory compact projects={[]} select={select} />)
  await screen.findByText('Remembered preference')
  expect(vi.mocked(api).mock.calls.some(call => call[1].endsWith('/detail'))).toBe(false)
  fireEvent.click(rows()[0])
  await detail().findByText('Original user preference')
  expect(location.hash).toContain('memoryId=memory')
  expect(vi.mocked(api).mock.calls.some(call => call[1].endsWith('/history'))).toBe(false)
  fireEvent.click(detail().getByRole('button', { name: 'agent.memoryOpenSource' }))
  expect(select).toHaveBeenCalledWith('source-conversation', 'source-branch', 'source-message')
  fireEvent.click(detail().getByRole('button', { name: 'agent.memoryBrowse.history' }))
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1].endsWith('/history'))).toBe(true))
  expect(screen.getByRole('link', { name: 'agent.memoryBrowse.browse' }).getAttribute('href')).toContain('home/memory/home')
})

it('preserves loaded rows after refresh failure and offers a real recovery action', async () => {
  let fail = false
  install(undefined, (_method, path) => fail && path.includes('/catalog?') ? Promise.reject(new Error('offline')) : undefined)
  render(<AgentMemory projects={[]} select={vi.fn()} />)
  await screen.findByText('Remembered preference')
  fail = true
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'changed' } })
  await screen.findByText('agent.memoryBrowse.loadFailed')
  expect(screen.getByText('Remembered preference')).toBeTruthy()
  fail = false
  fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'agent.retry' }))
  await waitFor(() => expect(screen.queryByText('agent.memoryBrowse.loadFailed')).toBeNull())
})

it('compares a conflict and submits the observed current ID only after explicit confirmation', async () => {
  const proposed = record('conflict', { title: 'New executor', body: 'Use Claude', state: 'conflict' })
  install([proposed], (_method, path) => path.endsWith('/detail') ? { data: { record: proposed, evidence, current: record('previous', { body: 'Use Codex' }), canConfirm: true } } : undefined)
  render(<AgentMemory fullPage projects={[]} select={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /New executor/ }))
  await detail().findByText('Use Codex')
  fireEvent.click(detail().getByRole('button', { name: 'agent.memoryBrowse.replace' }))
  expect(mocks.confirm).toHaveBeenCalledWith(expect.objectContaining({ title: 'agent.memoryBrowse.replace' }))
  expect(vi.mocked(api).mock.calls.some(call => call[0] === 'POST')).toBe(false)
  await act(async () => { await mocks.confirm.mock.calls[0][0].onOk() })
  expect(api).toHaveBeenCalledWith('POST', '/agent/memories/conflict/confirm', { accepted: true, expectedCurrentId: 'previous' })
})

it('disables confirmation when a source changed or could not be loaded', async () => {
  const candidate = record('candidate', { state: 'candidate' })
  install([candidate], (_method, path) => path.endsWith('/detail') ? { data: { record: candidate, evidence: [{ ...evidence[0], unchanged: false }], current: null, canConfirm: false } } : undefined)
  render(<AgentMemory projects={[]} select={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Remembered preference/ }))
  await detail().findByText('agent.memoryBrowse.sourceChanged')
  expect((detail().getByRole('button', { name: 'agent.memoryConfirm' }) as HTMLButtonElement).disabled).toBe(true)
})

it('retains the selected detail and source after a failed delete', async () => {
  install(undefined, (method) => method === 'DELETE' ? Promise.reject(new Error('offline')) : undefined)
  render(<AgentMemory fullPage projects={[]} select={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Remembered preference/ }))
  await detail().findByText('Original user preference')
  fireEvent.click(detail().getByRole('menuitem', { name: 'agent.memoryDelete' }))
  await act(async () => { await expect(mocks.confirm.mock.calls[0][0].onOk()).rejects.toThrow('MEMORY_DELETE_FAILED') })
  expect(location.hash).toContain('memoryId=memory')
  expect(detail().getByText('Original user preference')).toBeTruthy()
  expect(detail().getByRole('alert')).toBeTruthy()
  expect(mocks.success).not.toHaveBeenCalled()
})

it('uses one mobile return bar and restores list selection through URL history', async () => {
  mocks.layout.phone = true
  const onBack = vi.fn()
  install()
  render(<AgentMemory fullPage onBack={onBack} projects={[]} select={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Remembered preference/ }))
  await detail().findByText('Original user preference')
  expect(document.querySelectorAll('[data-mobile-page] header')).toHaveLength(1)
  fireEvent.click(within(document.querySelector('header')!).getByRole('button', { name: 'common.back' }))
  await waitFor(() => expect(location.hash).not.toContain('memoryId='))
  expect(onBack).not.toHaveBeenCalled()
})

it('renders one empty state without zero totals or useless pagination and keeps daily activity separate', async () => {
  install([], (_method, path) => {
    if (!path.includes('/catalog?')) return
    return new URLSearchParams(path.split('?')[1]).get('category') === 'activity' ? { data: { items: [record('daily', { day_key: '2026-10-18', kind: 'summary', body: JSON.stringify({ counts: { userTurns: 31, tasksCompleted: 6 }, scopeKey: 'unassigned' }) })], total: 1 } } : { data: { items: [], total: 0 } }
  })
  render(<AgentMemory fullPage projects={[]} select={vi.fn()} />)
  await screen.findByText('agent.noMemories')
  expect(screen.queryByText('agent.memoryTotal')).toBeNull()
  expect(screen.queryByRole('button', { name: 'agent.memoryNext' })).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: 'agent.memoryView.activity' }))
  await screen.findByRole('button', { name: /agent.memoryUnassigned/ })
  expect(vi.mocked(api).mock.calls.some(call => call[1].includes('category=activity') && call[1].includes('offset=0'))).toBe(true)
})

it('embeds desktop memory without a second page header', async () => {
  install()
  history.replaceState({}, '', '#/settings/agent/memory')
  render(<AgentMemory fullPage embedded projects={[]} select={vi.fn()} />)
  await screen.findByText('Remembered preference')
  expect(document.querySelector('.memory-page > .tt-pagehead')).toBeNull()
  fireEvent.click(rows()[0])
  await detail().findByText('Original user preference')
  expect(location.hash.split('?')[0]).toBe('#/settings/agent/memory')
})

it('returns from mobile memory details to the list before leaving settings', async () => {
  install()
  mocks.layout.phone = true
  history.replaceState({}, '', '#/settings/agent/memory?memoryId=memory&memoryQuery=concise')
  const onBack = vi.fn()
  render(<AgentMemory fullPage embedded onBack={onBack} projects={[]} select={vi.fn()} />)
  await detail().findByText('Original user preference')
  const back = within(document.querySelector('[data-mobile-page] > header') as HTMLElement).getByRole('button', { name: 'common.back' })
  fireEvent.click(back)
  await waitFor(() => expect(location.hash).not.toContain('memoryId='))
  expect(location.hash).toContain('memoryQuery=concise')
  expect(onBack).not.toHaveBeenCalled()
  expect(document.querySelectorAll('[data-mobile-page]')).toHaveLength(1)
  fireEvent.click(back)
  expect(onBack).toHaveBeenCalledOnce()
})
