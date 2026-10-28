// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { readMemoryRoute, writeMemoryRoute } from './memory-browser-route'
import { normalizeRoute } from '../../route-hash'

afterEach(() => { history.replaceState(null, '', '#/home'); vi.restoreAllMocks() })
it('stores a shareable selection without losing node or terminal parameters', () => {
  history.replaceState({ host: 'keep' }, '', '#/home/memory/home%2Fc?node=n1&terms=s1&active=s1')
  const before = history.length
  writeMemoryRoute({ ...readMemoryRoute(), scope: 'project', entity: 'project/one', query: 'Codex 偏好', page: 2, id: 'memory/one' }, true)
  expect(readMemoryRoute()).toMatchObject({ scope: 'project', entity: 'project/one', query: 'Codex 偏好', page: 2, id: 'memory/one' })
  expect(new URLSearchParams(location.hash.split('?')[1]).get('node')).toBe('n1')
  expect(new URLSearchParams(location.hash.split('?')[1]).get('terms')).toBe('s1')
  expect(history.length).toBe(before + 1)
  expect(history.state.host).toBe('keep')
  expect(history.state.roamiMemoryFrom).not.toContain('memoryId')
})
it('replaces typing and filtering instead of adding back entries', () => {
  history.replaceState(null, '', '#/home?terms=s1')
  const before = history.length, listener = vi.fn()
  window.addEventListener('hashchange', listener)
  writeMemoryRoute({ ...readMemoryRoute(), query: 'first' })
  writeMemoryRoute({ ...readMemoryRoute(), query: 'second', view: 'review' })
  expect(history.length).toBe(before)
  expect(readMemoryRoute()).toMatchObject({ query: 'second', view: 'review' })
  expect(listener).toHaveBeenCalledTimes(2)
  window.removeEventListener('hashchange', listener)
})
it('validates unknown filters and invalid page numbers from external links', () => {
  history.replaceState(null, '', '#/home?memoryView=unknown&memoryScope=unsafe&memoryType=other&memoryPage=-2&memoryDate=no')
  expect(readMemoryRoute()).toMatchObject({ view: 'saved', scope: 'all', kind: 'all', page: 0, date: '' })
  expect(normalizeRoute('settings/agent/memory')).toBe('settings/agent/memory')
})

it('keeps settings navigation and query state while reading a memory', () => {
  history.replaceState({}, '', '#/settings/agent/memory?node=n1&terms=s1')
  writeMemoryRoute({ ...readMemoryRoute(), view: 'review', query: 'preference', id: 'memory/one' }, true)
  expect(normalizeRoute(location.hash.slice(2))).toBe('settings/agent/memory')
  expect(readMemoryRoute()).toMatchObject({ view: 'review', query: 'preference', id: 'memory/one' })
  expect(new URLSearchParams(location.hash.split('?')[1]).get('node')).toBe('n1')
  expect(new URLSearchParams(location.hash.split('?')[1]).get('terms')).toBe('s1')
})
