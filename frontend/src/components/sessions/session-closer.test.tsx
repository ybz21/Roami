// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { useSessionCloser } from './session-closer'
import { closeSession } from './session-actions'
import { submitLifecycle } from './session-lifecycle'

const ui = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), confirm: vi.fn() }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', async original => ({ ...await original<typeof import('antd')>(), App: { useApp: () => ({ message: ui, modal: { confirm: ui.confirm } }) } }))
vi.mock('./session-actions', () => ({ closeSession: vi.fn(), sessionActionError: () => 'failed' }))
vi.mock('./session-lifecycle', () => ({ submitLifecycle: vi.fn(), lifecycleRequestError: () => 'failed' }))

beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const checkDialog = (result: ReturnType<typeof useSessionCloser>) => result.node

it.each([{ inWorktree: false }, { inWorktree: true, base: 'main' }, { inWorktree: true, dirty: 1, base: 'main' }, { inWorktree: true, others: 1 }])('keeps the same dialog and button after a check resolves to %j', async status => {
  let respond!: (value: unknown) => void
  vi.mocked(api).mockReturnValue(new Promise(resolve => { respond = resolve }))
  const { result, rerender } = renderHook(() => useSessionCloser(vi.fn()))
  let first!: Promise<void>
  act(() => { first = result.current.beginClose('session') })
  const view = render(result.current.node)
  const element = screen.getByRole('dialog')
  const dialog = within(element)
  const close = dialog.getByRole('button', { name: 'session.close' })
  expect(dialog.getByRole('status').textContent).toBe('session.closeChecking')
  expect(dialog.getByRole('button', { name: 'session.close' }).hasAttribute('disabled')).toBe(true)
  expect(dialog.getByRole('button', { name: 'common.cancel' }).hasAttribute('disabled')).toBe(false)
  expect(ui.confirm).not.toHaveBeenCalled()
  rerender()
  await act(() => result.current.beginClose('session'))
  expect(api).toHaveBeenCalledTimes(1)
  await act(async () => { respond({ data: status }); await first })
  view.rerender(result.current.node)
  expect(screen.getByRole('dialog')).toBe(element)
  expect(dialog.getByRole('button', { name: 'session.close' })).toBe(close)
  expect(close.hasAttribute('disabled')).toBe(false)
})

it('reports a failed check and allows retry without falling through to a close confirmation', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: { inWorktree: false } })
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('session'))
  expect(ui.error).toHaveBeenCalledWith('session.closeCheckFailed')
  expect(checkDialog(result.current).props.info).toBeNull()
  expect(ui.confirm).not.toHaveBeenCalled()
  await act(() => result.current.beginClose('session'))
  expect(api).toHaveBeenCalledTimes(2)
  expect(checkDialog(result.current).props.info).not.toBeNull()
})

it('opens unfinished worktree choices after the first check completes', async () => {
  const status = { inWorktree: true, dirty: 1, base: 'main', path: '/work' }
  vi.mocked(api).mockResolvedValue({ data: status })
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('session'))
  expect(checkDialog(result.current).props.info).toEqual({ name: 'session', st: status })
  expect(checkDialog(result.current).props.checking).toBe(false)
  expect(ui.confirm).not.toHaveBeenCalled()
})

it('opens native session confirmation without a worktree check', async () => {
  const { result } = renderHook(() => useSessionCloser(vi.fn()))
  await act(() => result.current.beginClose('roami:native'))
  expect(api).not.toHaveBeenCalled()
  expect(checkDialog(result.current).props.checking).toBe(false)
  expect(checkDialog(result.current).props.info.name).toBe('roami:native')
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
  expect(checkDialog(result.current).props.info).toBeNull()
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
  act(() => checkDialog(result.current).props.onClose())
  act(() => { second = result.current.beginClose('other') })
  await act(async () => { oldResponse({ data: { inWorktree: false } }); await first })
  expect(checkDialog(result.current).props.checking).toBe(true)
  expect(ui.confirm).not.toHaveBeenCalled()
  await act(async () => { newResponse({ data: { inWorktree: false } }); await second })
  expect(checkDialog(result.current).props.info.name).toBe('other')
  expect(checkDialog(result.current).props.checking).toBe(false)
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

it.each([true, false])('respects the clean worktree removal choice: %s', async remove => {
  const status = { inWorktree: true, base: 'main', path: '/work', snapshot: 'snapshot', sessionIdentity: 'identity' }
  vi.mocked(api).mockResolvedValue({ data: status })
  const done = vi.fn()
  const { result } = renderHook(() => useSessionCloser(done))
  await act(() => result.current.beginClose('session'))
  render(result.current.node)
  if (!remove) fireEvent.click(screen.getByRole('checkbox'))
  await act(async () => { fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'session.close' })) })
  expect(submitLifecycle).toHaveBeenCalledWith('close', { mode: remove ? 'discard' : 'keep', path: '/work', snapshot: 'snapshot', sessionIdentity: 'identity' }, 'session')
  expect(closeSession).not.toHaveBeenCalled()
  expect(done).toHaveBeenCalledWith('session')
})
