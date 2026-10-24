import { useEffect, useState } from 'react'
import { getHashParams } from '../../route-hash'
import type { MemoryScope, MemoryView } from './memory-record'

export type MemoryRoute = { view: MemoryView; scope: MemoryScope; kind: string; entity: string; query: string; page: number; id: string; date: string }
const fields: Record<keyof MemoryRoute, string> = { view: 'memoryView', scope: 'memoryScope', kind: 'memoryType', entity: 'memoryEntity', query: 'memoryQuery', page: 'memoryPage', id: 'memoryId', date: 'memoryDate' }
export function readMemoryRoute(defaultScope: MemoryScope = 'all'): MemoryRoute {
  const params = getHashParams(), view = params.get(fields.view), scope = params.get(fields.scope), kind = params.get(fields.kind), page = Number(params.get(fields.page) || '0')
  return { view: ['saved', 'review', 'activity'].includes(view) ? view as MemoryView : 'saved', scope: ['all', 'personal', 'project', 'conversation', 'task'].includes(scope) ? scope as MemoryScope : defaultScope, kind: ['fact', 'decision', 'preference', 'summary'].includes(kind) ? kind : 'all', entity: params.get(fields.entity) || '', query: (params.get(fields.query) || '').slice(0, 1000), page: Number.isSafeInteger(page) && page >= 0 ? page : 0, id: params.get(fields.id) || '', date: /^\d{4}-\d{2}-\d{2}$/.test(params.get(fields.date) || '') ? params.get(fields.date) : '' }
}
export function writeMemoryRoute(next: MemoryRoute, push = false) {
  const params = getHashParams(), defaults = { view: 'saved', scope: 'all', kind: 'all', page: 0 }
  for (const [key, field] of Object.entries(fields)) {
    const value = next[key as keyof MemoryRoute]
    if (value && value !== defaults[key]) params.set(field, String(value)); else params.delete(field)
  }
  const target = (location.hash.split('?')[0] || '#/home') + (params.size ? '?' + params : '')
  if (target === location.hash) return
  const state = { ...history.state }
  if (push) state.roamiMemoryFrom = location.hash
  history[push ? 'pushState' : 'replaceState'](state, '', target)
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}
export function useMemoryRoute(defaultScope: MemoryScope = 'all') {
  const [value, setValue] = useState(() => readMemoryRoute(defaultScope))
  useEffect(() => { const read = () => setValue(readMemoryRoute(defaultScope)); window.addEventListener('hashchange', read); window.addEventListener('popstate', read); read(); return () => { window.removeEventListener('hashchange', read); window.removeEventListener('popstate', read) } }, [defaultScope])
  const change = (patch: Partial<MemoryRoute>, push = false) => writeMemoryRoute({ ...readMemoryRoute(defaultScope), ...patch }, push)
  const back = () => {
    const parent = history.state?.roamiMemoryFrom
    if (typeof parent === 'string' && !new URLSearchParams(parent.split('?')[1]).has('memoryId') && parent.split('?')[0] === location.hash.split('?')[0]) history.back()
    else change({ id: '' })
  }
  return { value, change, back }
}
