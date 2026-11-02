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

it.each([
  '/home/ai/.roami/workspaces/agent-coding/index.html',
  '/home/ai/.roami/workspaces/agent-coding/shot-desktop.png',
  '/tmp/预览%20%2B%25.html?dl=1#part',
  '/Users/developer/report.pdf',
  '/var/tmp/report.md',
])('routes local output paths through the file endpoint on the message origin: %s', href => {
  setCurrentNode('different-node')
  expect(agentResourceUrl(href, 'origin')).toBe('/n/origin/api/file' + href)
  expect(agentResourceUrl(href, null)).toBe('/api/file' + href)
})

it.each(['/', '/home', '/projects', '/settings', '/homework/report.html'])('preserves application routes: %s', href => {
  expect(agentResourceUrl(href, 'origin')).toBe(href)
})
