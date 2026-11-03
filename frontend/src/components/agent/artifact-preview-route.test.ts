// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { artifactPreviewHref, readArtifactPreviewRoute } from './artifact-preview-route'
vi.mock('../cluster/node-url', () => ({ currentNodeId: () => 'origin/node' }))

it('retains the source node and task route across a new tab', () => {
  history.replaceState(null, '', '#/home/task?node=origin%2Fnode')
  const href = artifactPreviewHref('report /版本')
  expect(readArtifactPreviewRoute(href)).toEqual({ id: 'report /版本', node: 'origin/node', from: '#/home/task?node=origin%2Fnode' })
})

it.each(['#/artifact/%ZZ', '#/artifact/', '#/artifact/a/b', '#/home'])('rejects malformed preview routes: %s', hash => {
  expect(readArtifactPreviewRoute(hash)).toBeNull()
})

it('keeps return navigation inside the application', () => {
  expect(readArtifactPreviewRoute('#/artifact/report?from=https%3A%2F%2Fexample.com')?.from).toBe('#/home')
})
