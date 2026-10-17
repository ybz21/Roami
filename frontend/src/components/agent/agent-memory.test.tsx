// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentMemory from './AgentMemory'
import { api } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <div>{children}</div> }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: vi.fn() }, modal: { confirm: vi.fn() } }) },
  Button: ({ children, loading: _loading, danger: _danger, ...props }: any) => <button {...props}>{children}</button>,
  Input: { Search: (props: any) => <input {...props} /> },
  Modal: () => null,
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
    return { data: [{ id: 'new-memory', title: 'Current memory', body: 'Current fact', state: 'active' }] }
  })
  const view = render(<AgentMemory cid="old" projects={[]} select={vi.fn()} />)
  await waitFor(() => expect(oldSignal).toBeDefined())
  view.rerender(<AgentMemory cid="new" projects={[]} select={vi.fn()} />)
  await screen.findByText('Current fact')
  expect(oldSignal?.aborted).toBe(true)
  await act(async () => { finishOld({ data: [{ id: 'old-memory', title: 'Previous memory', body: 'Previous fact', state: 'active' }] }); await old })
  expect(screen.queryByText('Previous fact')).toBeNull()
  expect(screen.getByText('Current fact')).toBeTruthy()
  expect(screen.queryByRole('progressbar')).toBeNull()
})
