// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import { PromptPanel } from './prompt'

vi.mock('../api', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.useRealTimers(); vi.mocked(api).mockReset() })

const question = (text: string) => `${text}\n   ❯ 1. Yes\n     2. No\n   Enter to select\n`
const posts = () => vi.mocked(api).mock.calls.filter(([method]) => method === 'POST')

it('does not apply an option to a different prompt', async () => {
  vi.useFakeTimers()
  vi.mocked(api).mockResolvedValueOnce({ data: question('Do you want to run this command?') })
    .mockResolvedValueOnce({ data: question('Do you want to apply these changes?') })
  render(<PromptPanel name="one" accent="var(--accent)" />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: /yes/i }))
  await act(async () => {})
  expect(posts()).toHaveLength(0)
  expect(screen.getByText('Do you want to apply these changes?')).toBeTruthy()
})

it('does not send Enter when a numbered choice already advances to the next prompt', async () => {
  vi.useFakeTimers()
  const before = { data: question('Do you want to run this command?') }
  vi.mocked(api).mockResolvedValueOnce(before).mockResolvedValueOnce(before)
    .mockResolvedValueOnce({ data: {} })
    .mockResolvedValueOnce({ data: question('Do you want to apply these changes?') })
  render(<PromptPanel name="one" accent="var(--accent)" />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: /yes/i }))
  await act(async () => { await vi.advanceTimersByTimeAsync(350) })
  expect(posts().map(([, , body]) => body)).toEqual([{ keys: ['1'] }])
  expect(screen.getByText('Do you want to apply these changes?')).toBeTruthy()
})
