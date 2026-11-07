// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useSwarmConversationSelection } from './swarm-conversation-selection'

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

it('retains group and original member selections after responsive remounts', () => {
  const key = 'selection:remount'
  const first = renderHook(() => useSwarmConversationSelection(key, 'remount-main-request'))
  act(() => first.result.current[1]('group'))
  first.unmount()
  const next = renderHook(() => useSwarmConversationSelection(key, 'remount-main-request'))
  expect(next.result.current[0]).toBe('group')
  act(() => next.result.current[1]('original-member'))
  next.unmount()
  const last = renderHook(() => useSwarmConversationSelection(key, 'remount-main-request'))
  expect(last.result.current[0]).toBe('original-member')
})

it('handles each explicit Main request once without overriding a later selection', () => {
  const key = 'selection:requests'
  const view = renderHook(({ request }) => useSwarmConversationSelection(key, request), { initialProps: { request: 'request-first' } })
  act(() => view.result.current[1]('group'))
  view.rerender({ request: 'request-second' })
  expect(view.result.current[0]).toBe('main')
  act(() => view.result.current[1]('original-member'))
  view.unmount()
  const next = renderHook(() => useSwarmConversationSelection(key, 'request-second'))
  expect(next.result.current[0]).toBe('original-member')
})

it('hydrates the new node and Swarm before showing the previous recipient', () => {
  const first = 'selection:node-a:swarm-a', second = 'selection:node-a:swarm-b', remote = 'selection:node-b:swarm-a'
  const view = renderHook(({ key }) => useSwarmConversationSelection(key), { initialProps: { key: first } })
  act(() => view.result.current[1]('group'))
  view.rerender({ key: second })
  expect(view.result.current[0]).toBe('main')
  act(() => view.result.current[1]('member-b'))
  view.rerender({ key: remote })
  expect(view.result.current[0]).toBe('main')
  view.rerender({ key: first })
  expect(view.result.current[0]).toBe('group')
  view.rerender({ key: second })
  expect(view.result.current[0]).toBe('member-b')
})

it('keeps an unavailable saved recipient explicit instead of selecting another actor', () => {
  localStorage.setItem('selection:unavailable', 'closed-member')
  const view = renderHook(() => useSwarmConversationSelection('selection:unavailable'))
  expect(view.result.current[0]).toBe('closed-member')
})

it('keeps the current conversation usable if preference storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('unavailable') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('unavailable') })
  const view = renderHook(() => useSwarmConversationSelection('selection:denied'))
  expect(view.result.current[0]).toBe('main')
  act(() => view.result.current[1]('group'))
  expect(view.result.current[0]).toBe('group')
})
