// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import { useTerminalRuntime } from './useTerminalRuntime'

vi.mock('../api', () => ({ api: vi.fn() }))
const sources = vi.hoisted(() => ({
  overview: vi.fn(() => ({ value: [] })),
  native: vi.fn(() => ({ value: [] })),
}))
vi.mock('../session-overview', () => ({ useSessionOverview: sources.overview }))
vi.mock('../components/sessions/native-session-list', () => ({ useNativeSessionList: sources.native }))

const inventory = {
  loaded: true, failed: false,
  value: { kinds: { one: 'codex', two: 'claude', three: 'opencode' }, alternatives: {} },
}
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

afterEach(() => { cleanup(); vi.useRealTimers(); vi.mocked(api).mockReset() })

it('probes only a visible session and only the Agent listed for it', async () => {
  vi.useFakeTimers()
  vi.mocked(api).mockResolvedValue({ data: { running: true } })
  const view = renderHook(({ session }: { session: string | null }) => useTerminalRuntime(session, inventory, false), {
    initialProps: { session: null },
  })
  await advance(30_000)
  expect(api).not.toHaveBeenCalled()
  view.rerender({ session: 'one' })
  await advance(5000)
  expect(vi.mocked(api).mock.calls.map(([, path]) => path)).toEqual(['/sessions/one/codex', '/sessions/one/codex'])
  view.rerender({ session: null })
  await advance(30_000)
  expect(api).toHaveBeenCalledTimes(2)
})

it('still discovers the chat options for a session with different Agents in its panes', async () => {
  vi.useFakeTimers()
  vi.mocked(api).mockResolvedValue({ data: { running: true } })
  renderHook(() => useTerminalRuntime('one', {
    ...inventory, value: { ...inventory.value, alternatives: { one: ['claude'] } },
  }, false))
  await advance(0)
  expect(vi.mocked(api).mock.calls.map(([, path]) => path)).toEqual(['/sessions/one/codex', '/sessions/one/claude'])
})

it('subscribes only to the session family needed by a standalone terminal', () => {
  const options = { workspaceActivity: false, desktopClaude: false }
  const view = renderHook(({ session }) => useTerminalRuntime(session, inventory, false, options), {
    initialProps: { session: 'one' },
  })
  expect(sources.overview).toHaveBeenLastCalledWith(true)
  expect(sources.native).toHaveBeenLastCalledWith(false)
  view.rerender({ session: 'roami:native-example' })
  expect(sources.overview).toHaveBeenLastCalledWith(false)
  expect(sources.native).toHaveBeenLastCalledWith(true)
})
