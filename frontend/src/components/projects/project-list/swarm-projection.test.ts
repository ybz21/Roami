// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { swarmProjectMatches } from './swarm-projection'

it('keeps a team with its explicit project even when an execution directory names another project', () => {
  const target = { projectId: 'promotion', directory: '/source' }
  expect(swarmProjectMatches(target, { key: 'source', dir: '/source' })).toBe(false)
  expect(swarmProjectMatches(target, { key: 'promotion', dir: '/promotion' })).toBe(true)
  expect(swarmProjectMatches(target, { dir: '/source' })).toBe(false)
})

it('matches a directory only for teams without an explicit project identity', () => {
  expect(swarmProjectMatches({ directory: '/promotion/' }, { key: 'promotion', dir: '/promotion' })).toBe(true)
  expect(swarmProjectMatches({}, { key: 'promotion', dir: '/promotion' })).toBe(false)
})
