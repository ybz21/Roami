import { describe, expect, it } from 'vitest'
import { sessionBranches } from './session-lineage'
import type { TreeSession, TreeTask } from './task-tree'

const entries = (...sessions: TreeSession[]) => sessions.map(session => ({ session, task: null }))
describe('session ancestry', () => {
  it('puts children under their recorded parent even when the child arrived first', () => {
    const roots = sessionBranches(entries({ name: 'child', label: '回归', parent: 'parent' }, { name: 'grandchild', label: '数值', parent: 'child' }, { name: 'parent', label: 'RSI' }))
    expect(roots.map(n => n.session.name)).toEqual(['parent'])
    expect(roots[0].children[0].children[0].session.name).toBe('grandchild')
  })
  it('does not invent ancestry from similar names', () => {
    expect(sessionBranches(entries({ name: 'a', label: 'RSI回归' }, { name: 'b', label: 'RSI验证' })).length).toBe(2)
  })
  it('keeps a child in another workspace targeted at that workspace', () => {
    const task = { key: 'wt:/child', path: '/child' } as TreeTask
    const roots = sessionBranches([{ session: { name: 'p', label: 'Parent' }, task: null }, { session: { name: 'c', label: 'Child', parent: 'p' }, task }])
    expect(roots[0].children[0].task).toBe(task)
  })
  it('keeps missing parents, self references and cycles reachable', () => {
    const roots = sessionBranches(entries({ name: 'orphan', label: 'Orphan', parent: 'gone' }, { name: 'self', label: 'Self', parent: 'self' }, { name: 'a', label: 'A', parent: 'b' }, { name: 'b', label: 'B', parent: 'a' }))
    expect(roots.map(n => n.session.name)).toEqual(['orphan', 'self', 'a', 'b'])
  })
})
