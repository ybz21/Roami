// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ArtifactPreviewPage from './ArtifactPreviewPage'
import { TaskArtifactLink } from './TaskArtifactLink'
const layout = vi.hoisted(() => ({ phone: false }))
vi.mock('../../layout', () => ({ useLayout: () => layout }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../cluster/node-url', () => ({ currentNodeId: () => 'other-node', nodePath: (path: string, node: string) => node ? '/n/' + encodeURIComponent(node) + path : path }))
vi.mock('./TaskOutput', () => ({ canPreviewArtifact: () => true, TaskArtifactPreview: ({ contentUrl }: any) => <div data-testid="reader">{contentUrl}</div> }))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); layout.phone = false })
const artifact = { id: 'report', name: 'report.html', mimeType: 'text/html', sizeBytes: 500 }

it('addresses metadata and content to the source node independently of the selected node', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: artifact }) })
  vi.stubGlobal('fetch', fetch)
  render(<ArtifactPreviewPage route={{ id: 'report', node: 'source-node', from: '#/home/tasks' }} />)
  expect((await screen.findByTestId('reader')).textContent).toBe('/n/source-node/api/agent/artifacts/report/content')
  expect(fetch.mock.calls[0][0]).toBe('/n/source-node/api/agent/artifacts/report')
  expect(screen.getByRole('link', { name: 'agent.task.download' }).getAttribute('href')).toBe('/n/source-node/api/agent/artifacts/report/content?dl=1')
  expect(screen.getByRole('link', { name: 'common.back' }).getAttribute('href')).toBe('#/home/tasks')
})

it('offers recovery when a retained artifact cannot be loaded', async () => {
  const fetch = vi.fn().mockResolvedValueOnce({ ok: false }).mockResolvedValue({ ok: true, json: async () => ({ data: artifact }) })
  vi.stubGlobal('fetch', fetch)
  render(<ArtifactPreviewPage route={{ id: 'report', node: null, from: '#/home' }} />)
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByTestId('reader')
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('opens desktop previews in a new tab without changing task content', () => {
  const open = vi.fn()
  render(<TaskArtifactLink artifact={artifact} onPreview={open} />)
  const link = screen.getByRole('link')
  expect(link.getAttribute('target')).toBe('_blank')
  expect(link.getAttribute('rel')).toContain('noopener')
  fireEvent.click(link)
  expect(open).not.toHaveBeenCalled()
})

it('uses a full-screen mobile preview and preserves modified link clicks', () => {
  layout.phone = true
  const open = vi.fn()
  render(<TaskArtifactLink artifact={artifact} onPreview={open} />)
  const link = screen.getByRole('link')
  fireEvent.click(link, { ctrlKey: true })
  expect(open).not.toHaveBeenCalled()
  fireEvent.click(link)
  expect(open).toHaveBeenCalledWith('report')
})
