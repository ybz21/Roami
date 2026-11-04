import { expect, it } from 'vitest'
import { buildSessionProjects } from './session-project'

it('assigns every non-Git session by saved home even beyond the truncated project summary', () => {
  const projects = [{ key: 'code', name: 'Roami', dir: '/code', git: true }, { key: 'promotion', name: 'Promotion', dir: '/promotion', git: false, top: [{ name: 'writer' }] }]
  const placements = buildSessionProjects(projects, { writer: { home: '/promotion' }, data: { home: '/promotion/data' }, developer: { home: '/code', primary: { repo: '/code', worktree: '/code/.worktrees/dev', branch: 'dev' } } })
  expect(placements.data).toEqual({ key: 'promotion', name: 'Promotion', dir: '/promotion' })
  expect(placements.developer).toMatchObject({ key: 'code', worktree: '/code/.worktrees/dev' })
})

it('uses the deepest registered non-Git project without matching sibling path prefixes', () => {
  const projects = [{ key: 'parent', name: 'Parent', dir: '/work', git: false }, { key: 'child', name: 'Child', dir: '/work/promotion/', git: false }]
  const placements = buildSessionProjects(projects, { nested: { home: '/work/promotion/data' }, sibling: { home: '/work/promotion-extra' } })
  expect(placements.nested.key).toBe('child')
  expect(placements.sibling.key).toBe('parent')
})
