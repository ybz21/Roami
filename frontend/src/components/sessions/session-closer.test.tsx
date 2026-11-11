// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { useSessionCloser } from './session-closer'

const ui = vi.hoisted(() => ({ loading: vi.fn(), hide: vi.fn(), error: vi.fn(), confirm: vi.fn() }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', async original => ({ ...await original<typeof import('antd')>(), App: { useApp: () => ({ message: ui, modal: { confirm: ui.confirm } }) } }))
vi.mock('./CloseWorktreeModal', () => ({ CloseWorktreeModal: () => null }))

beforeEach(() => { vi.resetAllMocks(); ui.loading.mockReturnValue(ui.hide) })
afterEach(cleanup)

it('acknowledges the first click and checks once while a worktree response is pending', async () => {
  let respond!: (value: unknown) => void
  vi.mocked(api).mockReturnValue(new Promise(resolve => { respond = resolve }))
  const { result, rerender } = renderHook(() => useSessionCloser(vi.fn()))
  let first!: Promise<void>
  act(() => { first = result.current.beginClose('session') })
  expect(ui.loading).toHaveBeenCalledWith({ content: 'session.closeChecking', duration: 0 })
  expect(ui.confirm).not.toHaveBeenCalled()
  expect(ui.hide).not.toHaveBeenCalled()
  rerender()
  await act(() => result.current.beginClose('session'))
  expect(api).toHaveBeenCalledTimes(1)
  await act(async () => { respond({ data: { inWorktree: false } }); await first })
  expect(ui.hide).toHaveBeenCalledOnce()
  expect(ui.confirm).toHaveBeenCalledOnce()
})

it('reports a failed check and allows retry without falling through to a close confirmation', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: { inWorktree: false } })
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('session'))
  expect(ui.error).toHaveBeenCalledWith('session.closeCheckFailed')
  expect(ui.hide).toHaveBeenCalledOnce()
  expect(ui.confirm).not.toHaveBeenCalled()
  await act(() => result.current.beginClose('session'))
  expect(api).toHaveBeenCalledTimes(2)
  expect(ui.confirm).toHaveBeenCalledOnce()
})

it('opens unfinished worktree choices after the first check completes', async () => {
  const status = { inWorktree: true, dirty: 1, base: 'main', path: '/work' }
  vi.mocked(api).mockResolvedValue({ data: status })
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('session'))
  expect(result.current.node.props.info).toEqual({ name: 'session', st: status })
  expect(ui.hide).toHaveBeenCalledOnce()
  expect(ui.confirm).not.toHaveBeenCalled()
})

it('opens native session confirmation without a worktree check', async () => {
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('roami:native'))
  expect(api).not.toHaveBeenCalled()
  expect(ui.loading).not.toHaveBeenCalled()
  expect(ui.confirm).toHaveBeenCalledOnce()
})
