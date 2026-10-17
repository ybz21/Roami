// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useVisibleAgentReads } from './useVisibleAgentReads'
import { api } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn(async () => ({ data: {} })) }))
let callback: IntersectionObserverCallback
let sentinel: HTMLSpanElement, root: HTMLDivElement
const fire = () => callback([{ isIntersecting: true, target: sentinel, intersectionRect: { left: 0, top: 0, width: 10, height: 1 } } as unknown as IntersectionObserverEntry], {} as IntersectionObserver)
const observe = vi.fn()

beforeEach(() => {
  vi.useFakeTimers(); vi.mocked(api).mockClear(); observe.mockClear()
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  root = document.createElement('div'); sentinel = document.createElement('span'); sentinel.dataset.eventId = '19'; root.append(sentinel); document.body.append(root)
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn(() => sentinel) })
  vi.stubGlobal('IntersectionObserver', class { constructor(cb: IntersectionObserverCallback) { callback = cb } observe = observe; disconnect() {} })
})
afterEach(() => { root.remove(); vi.useRealTimers(); vi.unstubAllGlobals() })

it('acknowledges only visible, unobscured completed messages', async () => {
  const done = vi.fn()
  const hook = renderHook(() => useVisibleAgentReads('c', { current: root }, '19', done))
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: () => document.body })
  act(fire); await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  expect(api).not.toHaveBeenCalled()
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: () => sentinel })
  act(fire); await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/c/read', { eventId: 19 })
  expect(done).toHaveBeenCalledOnce()
  hook.unmount()
})

it('does not consume a pending read after switching conversations or opening a panel', async () => {
  const done = vi.fn(), ref = { current: root }
  const hook = renderHook(({ cid }) => useVisibleAgentReads(cid, ref, '19', done), { initialProps: { cid: 'old' } })
  act(fire); hook.rerender({ cid: '' })
  await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  expect(api).not.toHaveBeenCalled()
  hook.unmount()
})

it('does not mark a background browser tab as read', async () => {
  const hook = renderHook(() => useVisibleAgentReads('c', { current: root }, '19', vi.fn()))
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
  act(fire); await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  expect(api).not.toHaveBeenCalled()
  hook.unmount()
})

it('observes messages again when a closing modal stops covering them', async () => {
  const modal = document.createElement('div'); modal.className = 'ant-modal-wrap'; document.body.append(modal)
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: () => modal })
  const hook = renderHook(() => useVisibleAgentReads('c', { current: root }, '19', vi.fn()))
  act(fire)
  await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  expect(api).not.toHaveBeenCalled()
  observe.mockClear()
  await act(async () => { modal.style.display = 'none' })
  expect(observe).toHaveBeenCalledWith(sentinel)
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: () => sentinel })
  act(fire)
  await act(async () => { await vi.advanceTimersByTimeAsync(300) })
  expect(api).toHaveBeenCalledWith('POST', '/agent/conversations/c/read', { eventId: 19 })
  hook.unmount(); modal.remove()
})
