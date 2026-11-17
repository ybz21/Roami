// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import AgentContextDetails from './AgentContextDetails'
import AgentCompactionStatus from './AgentCompactionStatus'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../markdown/Markdown', () => ({ default: ({ children }: any) => <div>{children}</div> }))
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers() })
const props = { cid: 'main', node: null, branch: 'history', compaction: { operationId: 'compact', state: 'running' }, running: false, readOnly: false, onCompact: vi.fn(), onCancel: vi.fn() }
const context = { estimatedTokens: 1000, contextWindow: 128000, snapshotId: 'snapshot' }

it('keeps the same summary mounted when completion refreshes usage without changing the snapshot', async () => {
  let refresh!: (value: any) => void
  vi.mocked(api).mockResolvedValueOnce({ data: context }).mockResolvedValueOnce({ data: { summary: { text: 'Stable summary' } } }).mockImplementationOnce(() => new Promise(resolve => { refresh = resolve }))
  const page = render(<AgentContextDetails {...props} />)
  const text = await screen.findByText('Stable summary')
  expect(vi.mocked(api).mock.calls[0][1]).toBe('/agent/conversations/main/context?branch=history')
  page.rerender(<AgentContextDetails {...props} compaction={{ ...props.compaction, state: 'completed' }} />)
  await waitFor(() => expect(api).toHaveBeenCalledTimes(3))
  expect(screen.getByText('Stable summary')).toBe(text)
  await act(async () => { refresh({ data: { ...context, estimatedTokens: 2000 } }) })
  expect(screen.getByText('Stable summary')).toBe(text)
  vi.useFakeTimers()
  await act(async () => { await vi.advanceTimersByTimeAsync(12000) })
  expect(api).toHaveBeenCalledTimes(3)
  expect(text.isConnected).toBe(true)
})

it('aborts a closed details request and never reads its snapshot after a late response', async () => {
  let complete!: (value: any) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
  const page = render(<AgentContextDetails {...props} />)
  const signal = vi.mocked(api).mock.calls[0][3]!.signal!
  page.unmount()
  expect(signal.aborted).toBe(true)
  await act(async () => { complete({ data: context }) })
  expect(api).toHaveBeenCalledTimes(1)
})

it('retains an already loaded summary through an error and provides an explicit retry', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: context }).mockResolvedValueOnce({ data: { summary: { text: 'Retained summary' } } }).mockRejectedValueOnce(Error('offline')).mockResolvedValue({ data: context })
  const page = render(<AgentContextDetails {...props} />)
  const text = await screen.findByText('Retained summary')
  page.rerender(<AgentContextDetails {...props} compaction={{ ...props.compaction, state: 'completed' }} />)
  await screen.findByRole('alert')
  expect(text.isConnected).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(screen.getByText('Retained summary')).toBe(text)
  expect(api).toHaveBeenCalledTimes(4)
})

it.each(['failed', 'cancelled', 'skipped', 'unknown'])('keeps %s distinct from successful compaction', state => {
  const open = vi.fn()
  render(<AgentCompactionStatus value={{ operationId: 'compact', state }} onOpen={open} />)
  expect(screen.queryByText('agent.compaction.completed')).toBeNull()
  fireEvent.click(screen.getByRole('button'))
  expect(open).toHaveBeenCalledOnce()
  expect(screen.getByRole('status').textContent).toContain('agent.compaction.' + state)
})
