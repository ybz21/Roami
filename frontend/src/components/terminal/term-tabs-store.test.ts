// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { forgetTabs, loadTabs } from './term-tabs-store'

beforeEach(() => localStorage.clear())

describe('legacy workspace import', () => {
  it('reads node-local files and old session IDs for one-time import', () => {
    localStorage.setItem('roam.terms', JSON.stringify({
      a: { terms: ['session-a'], active: 'session-a', files: { '/repo': [{ path: '/repo/a.md', mode: 'preview' }] }, activeFile: { '/repo': '/repo/a.md' } },
      b: { terms: ['session-b'], active: 'session-b' },
    }))
    expect(loadTabs('a')).toEqual({ terms: ['session-a'], active: 'session-a', files: [{ path: '/repo/a.md', mode: 'preview', preview: false, task: '/repo' }], activeFile: '/repo/a.md' })
    forgetTabs('a')
    expect(loadTabs('a').terms).toEqual([])
    expect(loadTabs('b').terms).toEqual(['session-b'])
    forgetTabs('b')
    expect(localStorage.getItem('roam.terms')).toBeNull()
  })

  it('ignores broken local data and invalid file selection', () => {
    localStorage.setItem('roam.terms', '{{{')
    expect(loadTabs(null)).toEqual({ terms: [], active: '', files: [], activeFile: '' })
    localStorage.setItem('roam.terms', JSON.stringify({ '': { terms: [], files: [{ path: '/p', mode: 'rich' }, { preview: true }], activeFile: '/gone' } }))
    expect(loadTabs(null)).toEqual({ terms: [], active: '', files: [{ path: '/p', mode: 'source', preview: false, task: '' }], activeFile: '' })
  })
})
