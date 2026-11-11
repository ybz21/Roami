// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { useSessionCloser } from './session-closer'

const ui = vi.hoisted(() => ({ error: vi.fn(), confirm: vi.fn() }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', async original => ({ ...await original<typeof import('antd')>(), App: { useApp: () => ({ message: ui, modal: { confirm: ui.confirm } }) } }))
vi.mock('./CloseWorktreeModal', () => ({ CloseWorktreeModal: () => null }))

beforeEach(() => { vi.resetAllMocks() })
afterEach(cleanup)

const checkDialog = (result: ReturnType<typeof useSessionCloser>) => result.node.props.children[0]

it('acknowledges the first click and checks once while a worktree response is pending', async () => {
  let respond!: (value: unknown) => void
  vi.mocked(api).mockReturnValue(new Promise(resolve => { respond = resolve }))
  const { result, rerender } = renderHook(() => useSessionCloser(vi.fn()))
  let first!: Promise<void>
  act(() => { first = result.current.beginClose('session') })
  const view = render(result.current.node)
  const dialog = within(screen.getByRole('dialog'))
  expect(dialog.getByRole('status').textContent).toBe('session.closeChecking')
  expect(dialog.getByRole('button', { name: 'session.close' }).hasAttribute('disabled')).toBe(true)
  expect(dialog.getByRole('button', { name: 'common.cancel' }).hasAttribute('disabled')).toBe(false)
  expect(ui.confirm).not.toHaveBeenCalled()
  rerender()
  await act(() => result.current.beginClose('session'))
  expect(api).toHaveBeenCalledTimes(1)
  await act(async () => { respond({ data: { inWorktree: false } }); await first })
  view.rerender(result.current.node)
  expect(checkDialog(result.current).props.open).toBe(false)
  expect(ui.confirm).toHaveBeenCalledOnce()
})

it('reports a failed check and allows retry without falling through to a close confirmation', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: { inWorktree: false } })
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('session'))
  expect(ui.error).toHaveBeenCalledWith('session.closeCheckFailed')
  expect(checkDialog(result.current).props.open).toBe(false)
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
  expect(result.current.node.props.children[1].props.info).toEqual({ name: 'session', st: status })
  expect(checkDialog(result.current).props.open).toBe(false)
  expect(ui.confirm).not.toHaveBeenCalled()
})

it('opens native session confirmation without a worktree check', async () => {
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('roami:native'))
  expect(api).not.toHaveBeenCalled()
  expect(checkDialog(result.current).props.open).toBe(false)
  expect(ui.confirm).toHaveBeenCalledOnce()
})

it('cancels a pending check without opening a late confirmation', async () => {
  let respond!: (value: unknown) => void
  vi.mocked(api).mockReturnValue(new Promise(resolve => { respond = resolve }))
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  let first!: Promise<void>
  act(() => { first = result.current.beginClose('session') })
  const signal = vi.mocked(api).mock.calls[0][3]!.signal!
  render(result.current.node)
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'common.cancel' }))
  expect(signal.aborted).toBe(true)
  expect(checkDialog(result.current).props.open).toBe(false)
  await act(async () => { respond({ data: { inWorktree: false } }); await first })
  expect(ui.confirm).not.toHaveBeenCalled()
  expect(ui.error).not.toHaveBeenCalled()
})

it('keeps a restarted check when a cancelled response arrives late', async () => {
  let oldResponse!: (value: unknown) => void
  let newResponse!: (value: unknown) => void
  vi.mocked(api).mockReturnValueOnce(new Promise(resolve => { oldResponse = resolve }))
    .mockReturnValueOnce(new Promise(resolve => { newResponse = resolve }))
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  let first!: Promise<void>
  let second!: Promise<void>
  act(() => { first = result.current.beginClose('session') })
  act(() => checkDialog(result.current).props.onCancel())
  act(() => { second = result.current.beginClose('other') })
  await act(async () => { oldResponse({ data: { inWorktree: false } }); await first })
  expect(checkDialog(result.current).props.open).toBe(true)
  expect(ui.confirm).not.toHaveBeenCalled()
  await act(async () => { newResponse({ data: { inWorktree: false } }); await second })
  expect(ui.confirm).toHaveBeenCalledOnce()
  expect(checkDialog(result.current).props.open).toBe(false)
})

it('aborts an unmounted check without displaying errors', async () => {
  let reject!: (error: Error) => void
  vi.mocked(api).mockReturnValue(new Promise((_resolve, no) => { reject = no }))
  const { result, unmount } = renderHook(() => useSessionCloser(vi.fn()))
  let pending!: Promise<void>
  act(() => { pending = result.current.beginClose('session') })
  const signal = vi.mocked(api).mock.calls[0][3]!.signal!
  unmount()
  expect(signal.aborted).toBe(true)
  await act(async () => { reject(new Error('aborted')); await pending })
  expect(ui.confirm).not.toHaveBeenCalled()
  expect(ui.error).not.toHaveBeenCalled()
})
