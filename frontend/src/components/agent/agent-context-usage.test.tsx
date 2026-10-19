// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentContextUsage from './AgentContextUsage'
import { useAgentContext } from './useAgentContext'
import { api } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', async () => {
  const strings = (await import('../../i18n/locales/en-US')).default
  return { useI18n: () => ({ locale: 'en-US', t: (key: keyof typeof strings, values: Record<string, string | number> = {}) => Object.entries(values).reduce((s, [k, v]) => s.split('{' + k + '}').join(String(v)), strings[key] || key) }) }
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers() })
const props = { cid: 'main', node: null, model: 'model', revision: 'one', active: false, onOpen: vi.fn() }

it('shows estimated tokens and the actual capacity, and opens the existing details entry', async () => {
  vi.mocked(api).mockResolvedValue({ data: { estimatedTokens: 12400, contextWindow: 128000, compactionThreshold: 96000 } })
  const open = vi.fn(); render(<AgentContextUsage {...props} onOpen={open} />)
  const meter = await screen.findByRole('button', { name: 'Context: ~12.4K / 128K tokens · 10%' })
  expect(meter.title).toContain('12,400 / 128,000')
  fireEvent.click(meter); expect(open).toHaveBeenCalledOnce()
})

it('keeps unknown model capacity unknown instead of inventing a denominator or percentage', async () => {
  vi.mocked(api).mockResolvedValue({ data: { estimatedTokens: 12400, contextWindow: null } })
  render(<AgentContextUsage {...props} />)
  expect(await screen.findByRole('button', { name: 'Context: ~12.4K tokens · capacity unknown' })).toBeTruthy()
})

it('warns at the server threshold and preserves percentages above capacity', async () => {
  vi.mocked(api).mockResolvedValue({ data: { estimatedTokens: 1100000, contextWindow: 1000000, compactionThreshold: 750000 } })
  render(<AgentContextUsage {...props} />)
  expect((await screen.findByRole('button', { name: 'Context: ~1.1M / 1M tokens · 110%' })).className).toContain('is-near-limit')
})

it('never shows another node or models delayed context response', async () => {
  let resolveOld!: (value: any) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockResolvedValue({ data: { estimatedTokens: 25, contextWindow: null } })
  const hook = renderHook(({ node, model }) => useAgentContext('main', node, model, 'one', false), { initialProps: { node: 'old', model: 'old' } })
  hook.rerender({ node: 'new', model: 'new' })
  await waitFor(() => expect(hook.result.current.data?.estimatedTokens).toBe(25))
  await act(async () => { resolveOld({ data: { estimatedTokens: 999, contextWindow: 4000 } }) })
  expect(hook.result.current.data?.estimatedTokens).toBe(25)
})

it('marks cached usage stale after refresh fails instead of clearing it to zero', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { estimatedTokens: 12400, contextWindow: 128000 } }).mockRejectedValueOnce(Error('offline'))
  const page = render(<AgentContextUsage {...props} />)
  await screen.findByRole('button', { name: 'Context: ~12.4K / 128K tokens · 10%' })
  page.rerender(<AgentContextUsage {...props} revision="two" />)
  expect(await screen.findByRole('button', { name: 'Context: ~12.4K / 128K tokens · 10% · update failed' })).toBeTruthy()
})

it('refreshes during active execution but stops polling when idle', async () => {
  vi.useFakeTimers();vi.mocked(api).mockResolvedValue({ data: { estimatedTokens: 100 } })
  const hook = renderHook(({ active }) => useAgentContext('main', null, 'model', 'one', active), { initialProps: { active: true } })
  await act(async () => {});expect(api).toHaveBeenCalledTimes(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) });expect(api).toHaveBeenCalledTimes(2)
  hook.rerender({ active: false });await act(async () => {});const count = vi.mocked(api).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) });expect(api).toHaveBeenCalledTimes(count)
})
