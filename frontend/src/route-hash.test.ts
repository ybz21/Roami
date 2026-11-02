// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { getHashParams, normalizeRoute, readTermTokens, setHashParams } from './route-hash'

const at = (hash: string) => { location.hash = hash }

describe('旧工作区链接导入', () => {
  beforeEach(() => at('#/projects'))

  it('未指定会话时返回空的导入列表', () => {
    expect(readTermTokens()).toEqual({ terms: [], active: '' })
  })
  it('旧镜像页的 terms=none 不导入会话', () => {
    at('#/browser?terms=none')
    expect(readTermTokens()).toEqual({ terms: [], active: '' })
  })
  it('读取旧链接中的会话列表与选择', () => {
    at('#/projects?terms=a,b&active=b')
    expect(readTermTokens()).toEqual({ terms: ['a', 'b'], active: 'b' })
  })
})

describe('legacy inbox links', () => {
  it('opens the project page for the old inbox root', () => {
    expect(normalizeRoute('inbox')).toBe('projects')
  })
  it('keeps session deep links for the app to open directly', () => {
    expect(normalizeRoute('inbox/session-a')).toBe('inbox/session-a')
  })
})


it('keeps the exact task browser target when node parameters change', () => {
  at('#/browser/task/browser-instance/exact-tab')
  setHashParams({ node: 'node-a' })
  expect(normalizeRoute(location.hash.replace(/^#\/?/, ''))).toBe('browser/task/browser-instance/exact-tab')
  expect(getHashParams().get('node')).toBe('node-a')
})

it('migrates plugin and settings capability links without losing their selection', () => {
  expect(normalizeRoute('plugins')).toBe('capabilities/plugins')
  expect(normalizeRoute('plugins/roam.cron')).toBe('capabilities/plugins/roam.cron')
  for (const kind of ['skills', 'mcp', 'cli', 'tools']) expect(normalizeRoute('settings/agent/' + kind)).toBe('capabilities/' + kind)
  expect(normalizeRoute('settings/agent/capabilities')).toBe('capabilities/skills')
})

it('moves professional agent links into capabilities and preserves the selected agent', () => {
  expect(normalizeRoute('settings/agent/bin')).toBe('capabilities/agents')
  expect(normalizeRoute('settings/agent/bin/codex')).toBe('capabilities/agents/codex')
})

it('moves legacy model pricing and usage links to their matching capability section', () => {
  expect(normalizeRoute('settings/agent/runtime?node=n1&modelTab=prices')).toBe('capabilities/models/prices')
  expect(normalizeRoute('settings/agent/runtime?modelTab=proxy')).toBe('capabilities/models/usage')
  expect(normalizeRoute('settings/agent/runtime')).toBe('capabilities/models/catalog')
  expect(normalizeRoute('env/agent/runtime?modelTab=prices')).toBe('capabilities/models/prices')
})

it.each([
  ['settings/common', 'settings/ui/look'],
  ['settings/ui/status', 'settings/ui/look'],
  ['settings/ui/keys/more', 'settings/ui/keys'],
])('keeps retired settings links usable: %s', (old, current) => {
  expect(normalizeRoute(old + '?node=n1')).toBe(current)
})

it('merges old model-source links into the unified model page', () => {
  expect(normalizeRoute('capabilities/models/sources')).toBe('capabilities/models/catalog')
  expect(normalizeRoute('capabilities/models/sources/source/upstream')).toBe('capabilities/models/catalog/source/upstream')
})
