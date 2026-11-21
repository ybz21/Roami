// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { readSessionScreen, useSessionScreen } from './session-screen'

vi.mock('../../api', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.useRealTimers(); vi.mocked(api).mockReset() })
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

it('shares capture for a prompt and live output, then stops with the last view', async () => {
  vi.useFakeTimers()
  vi.mocked(api).mockResolvedValue({ data: 'screen' })
  const prompt = renderHook(() => useSessionScreen('one'))
  const tail = renderHook(() => useSessionScreen('one', 800))
  await advance(0)
  expect(api).toHaveBeenCalledTimes(1)
  expect(prompt.result.current).toBe(tail.result.current)
  await advance(800)
  expect(api).toHaveBeenCalledTimes(2)
  tail.unmount()
  await advance(800)
  expect(api).toHaveBeenCalledTimes(3)
  prompt.unmount()
  await advance(10_000)
  expect(api).toHaveBeenCalledTimes(3)
})

it('does not let a scheduled capture overwrite a newer interaction read', async () => {
  vi.useFakeTimers()
  let finish!: (value: unknown) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValueOnce({ data: 'next question' })
  const view = renderHook(() => useSessionScreen('one'))
  await act(async () => { await readSessionScreen('one', null) })
  await act(async () => { finish({ data: 'old question' }) })
  expect(view.result.current).toEqual({ raw: 'next question', fresh: true })
})
