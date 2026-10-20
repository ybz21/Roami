// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { setCurrentNode } from '../cluster/node-url'
import { agentResourceUrl } from './agent-resource-url'

afterEach(() => setCurrentNode(null))

it('binds artifact and file URLs to their origin while preserving encoded paths and query parameters', () => {
  setCurrentNode('new-node')
  for (const href of ['/api/agent/artifacts/report/content', '/api/file/raw?path=%2Ftmp%2Fa%20b.txt&dl=1', '/api/file/serve/tmp/a%20b/index.html#part']) {
    expect(agentResourceUrl(href, 'old/node')).toBe('/n/old%2Fnode' + href)
    expect(agentResourceUrl(href, null)).toBe(href)
  }
})

it.each(['/n/explicit/api/agent/artifacts/id/content', 'https://github.com/ybz21/Roami/pull/353', 'https://example.com/api/file/raw?path=x', '//example.com/api/file/raw', '#section', '/api/file-not-a-resource', '/api/login'])('preserves explicit routes and unrelated links: %s', href => {
  expect(agentResourceUrl(href, 'node')).toBe(href)
})
