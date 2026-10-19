// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { TaskArtifactPreview, canPreviewArtifact } from './TaskOutput'
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => '/api' + path }))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('isolates HTML reports from scripts, same-origin access and network requests', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, text: async () => '<h1>Report</h1><script>parent.location="/"</script>' }))
  render(<TaskArtifactPreview artifact={{ id: 'report', name: 'report.html', mimeType: 'text/html', sizeBytes: 80 }} />)
  const frame = await screen.findByTitle('report.html')
  expect(frame.getAttribute('sandbox')).toBe('')
  expect(frame.getAttribute('srcdoc')).toContain("default-src 'none'")
  expect(frame.getAttribute('srcdoc')).toContain("form-action 'none'")
})
it('keeps large files and unsupported formats downloadable without eager preview', () => {
  expect(canPreviewArtifact({ id: 'ppt', name: 'slides.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', sizeBytes: 100 })).toBe(false)
  expect(canPreviewArtifact({ id: 'pdf', name: 'report.pdf', mimeType: 'application/pdf', sizeBytes: 9 * 1024 * 1024 })).toBe(false)
  expect(canPreviewArtifact({ id: 'pdf', name: 'report.pdf', mimeType: 'application/pdf', sizeBytes: 1024 })).toBe(true)
})
