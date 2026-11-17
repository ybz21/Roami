import { expect, it, vi } from 'vitest'
import { WorkspaceStateStore } from './workspace-state'

it('isolates nodes, pages, and resource paths without key collisions', () => {
  const store = new WorkspaceStateStore()
  const file = store.scope('node', 'one', 'page', 'files').child('file', '/a/b')
  file.set('position', { line: 10 })
  expect(file.get('position')).toEqual({ line: 10 })
  expect(store.scope('node', 'two', 'page', 'files', 'file', '/a/b').get('position')).toBeUndefined()
  expect(store.scope('node', 'one', 'page', 'files', 'file', '/a', 'b').get('position')).toBeUndefined()
  expect(store.scope('node', 'one', 'page', 'browser').get('position')).toBeUndefined()
})
it('notifies only the affected key and skips equal writes', () => {
  const scope = new WorkspaceStateStore().scope('view'), selected = vi.fn(), draft = vi.fn()
  const release = scope.subscribe('selected', selected)
  scope.subscribe('draft', draft)
  scope.set('selected', 'one'); scope.set('selected', 'one')
  expect(selected).toHaveBeenCalledOnce(); expect(draft).not.toHaveBeenCalled()
  release(); scope.set('selected', 'two'); expect(selected).toHaveBeenCalledOnce()
})
it('bounds rebuildable cache by bytes and LRU entries while protecting drafts and choices', () => {
  const store = new WorkspaceStateStore({ cacheBytes: 16, cacheEntries: 2 }), scope = store.scope('view')
  scope.set('draft', 'unsaved text'.repeat(100), 'draft'); scope.set('selected', 'one')
  scope.set('first', '1234', 'cache'); scope.set('second', '1234', 'cache'); scope.get('first'); scope.set('third', '1234', 'cache')
  expect(scope.has('second')).toBe(false); expect(scope.has('first')).toBe(true)
  scope.set('oversize', 'x'.repeat(100), 'cache')
  expect(store.stats().cacheBytes).toBeLessThanOrEqual(16)
  expect(scope.get('draft')).toBe('unsaved text'.repeat(100)); expect(scope.get('selected')).toBe('one')
})
it('keeps subscribed cache values readable until their view releases them', () => {
  const store = new WorkspaceStateStore({ cacheBytes: 8, cacheEntries: 1 }), scope = store.scope('view')
  const stop = scope.subscribe('data', () => {})
  scope.set('data', 'large cache value', 'cache')
  expect(scope.get('data')).toBe('large cache value')
  stop(); expect(scope.has('data')).toBe(false); expect(store.stats().cacheBytes).toBe(0)
})
it('clears a closed view but preserves unsaved drafts with their restoration metadata', () => {
  const store = new WorkspaceStateStore(), scope = store.scope('node', 'one', 'files')
  scope.set('tabs', ['/one']); scope.child('file', '/one').set('edit', 'unsaved', 'draft'); scope.set('listing', [], 'cache')
  scope.clear({ preserveDrafts: true })
  expect(scope.has('listing')).toBe(false); expect(scope.get('tabs')).toEqual(['/one'])
  scope.child('file', '/one').delete('edit'); scope.clear({ preserveDrafts: true })
  expect(store.stats().entries).toBe(0)
})
it('rejects runtime resources, cycles, and invalid numbers without corrupting previous state', () => {
  const scope = new WorkspaceStateStore().scope('view')
  scope.set('value', 'valid')
  for (const invalid of [() => {}, new Date(), new Map(), { handler: () => {} }, NaN, Infinity]) expect(() => scope.set('value', invalid)).toThrow(TypeError)
  const cycle: any = {}; cycle.self = cycle
  expect(() => scope.set('value', cycle)).toThrow(TypeError)
  expect(scope.get('value')).toBe('valid')
})

it('distinguishes the local node from a remote node named local', () => {
  const store = new WorkspaceStateStore()
  store.node(null).set('selected', 'local machine')
  store.node('local').set('selected', 'remote machine')
  expect(store.node(null).get('selected')).toBe('local machine')
  expect(store.node('local').get('selected')).toBe('remote machine')
})
