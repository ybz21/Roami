// @vitest-environment jsdom
import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ArtifactPreviewPage from './ArtifactPreviewPage'

vi.hoisted(() => {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: query === '(pointer: coarse)', addEventListener: vi.fn(), removeEventListener: vi.fn() })))
})
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../cluster/node-url', () => ({ nodePath: (path: string) => path }))
vi.mock('./TaskOutput', () => ({ canPreviewArtifact: () => true, TaskArtifactPreview: () => <div /> }))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('initializes compact touch layout when opened without the application workspace', async () => {
  delete document.documentElement.dataset.size
  delete document.documentElement.dataset.pointer
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: { id: 'report', name: 'report.html' } }) }))
  render(<ArtifactPreviewPage route={{ id: 'report', node: null, from: '#/home' }} />)
  await waitFor(() => {
    expect(document.documentElement.dataset.size).toBe('compact')
    expect(document.documentElement.dataset.pointer).toBe('coarse')
  })
})
