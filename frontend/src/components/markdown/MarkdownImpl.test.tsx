// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import Markdown from './MarkdownImpl'
import { resetStack, stackSize } from '../shell/useBackDismiss'

const device = vi.hoisted(() => ({ phone: true }))
vi.mock('../../layout', () => ({ useLayout: () => device }))
vi.mock('../files/fileview/FileView', () => ({ FileView: ({ path }: { path: string }) => <div data-testid="file-view">{path}</div> }))
vi.mock('../documents/DocumentPreview', async importOriginal => ({ ...await importOriginal<any>(), default: ({ src, name }: { src: string; name: string }) => <div data-testid="document-preview" data-src={src}>{name}</div> }))

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, headers: new Headers() }))) })
afterEach(() => { cleanup(); resetStack(); device.phone = true; vi.unstubAllGlobals() })

const show = (href = '/api/file/serve/tmp/demo.html', onLinkClick?: (href: string, event: React.MouseEvent<HTMLAnchorElement>) => void) => render(
  <I18nProvider><Markdown onLinkClick={onLinkClick}>{`[demo](${href})`}</Markdown></I18nProvider>,
)

describe('Markdown mobile file navigation', () => {
  it('can render private reviews without loading model-authored image URLs', () => {
    const content = 'Review evidence.\n\n![untrusted image](https://example.invalid/image?evidence=private)'
    const { container } = render(<I18nProvider><Markdown allowImages={false}>{content}</Markdown></I18nProvider>)
    expect(screen.getByText('Review evidence.')).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })
  it('previews PDF and PPTX artifacts and keeps a named download on the originating node', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ data: { id: 'report', name: '架构.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', sizeBytes: 512 } }), { headers: { 'Content-Type': 'application/json' } }))
    show('/n/other/api/agent/artifacts/report/content')
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    const preview = await screen.findByTestId('document-preview')
    expect(preview.textContent).toBe('架构.pptx')
    expect(preview.getAttribute('data-src')).toContain('/n/other/api/agent/artifacts/report/content')
    expect(screen.getByRole('link', { name: /下载|Download/ }).getAttribute('download')).toBe('架构.pptx')
    expect(screen.getByRole('link', { name: /下载|Download/ }).getAttribute('href')).toContain('/n/other/api/agent/artifacts/report/content?dl=1')
  })
  it('opens one full-screen preview and returns without leaving the conversation', async () => {
    show()
    const originalURL = location.href
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    const frame = await screen.findByTitle('demo.html')
    expect(frame.getAttribute('src')).toContain('/api/file/serve/tmp/demo.html')
    expect(stackSize()).toBe(1)
    expect(location.href).toBe(originalURL)
    fireEvent.click(screen.getByRole('button', { name: /返回|Back/ }))
    await waitFor(() => expect(screen.queryByTitle('demo.html')).toBeNull())
    expect(screen.getByRole('link', { name: 'demo' })).toBeTruthy()
    expect(stackSize()).toBe(0)
  })
  it('uses the existing viewer for query paths', async () => {
    show('/api/file/raw?path=%2Ftmp%2Fnotes.md')
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    expect((await screen.findByTestId('file-view')).textContent).toBe('/tmp/notes.md')
  })
  it('resolves relative aliases before rendering Markdown', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { headers: { 'X-Roami-File-Path': encodeURIComponent('/workspace/docs/说明.md') } }))
    show('/api/file/docs/说明.md')
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    expect((await screen.findByTestId('file-view')).textContent).toBe('/workspace/docs/说明.md')
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/file/docs/'), expect.objectContaining({ method: 'HEAD', cache: 'no-store' }))
  })
  it('keeps the return bar available when a file cannot load', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 404 }))
    show('/api/file/tmp/missing.md')
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    expect((await screen.findByRole('alert')).textContent).toContain('404')
    fireEvent.click(screen.getByRole('button', { name: /返回|Back/ }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })
  it('closes with the system back action', async () => {
    show()
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    await screen.findByTitle('demo.html')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.queryByTitle('demo.html')).toBeNull())
  })
  it('preserves desktop navigation and explicit click handlers', async () => {
    device.phone = false
    show()
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    expect(screen.queryByTitle('demo.html')).toBeNull()
    cleanup()
    device.phone = true
    show(undefined, (_, event) => event.preventDefault())
    fireEvent.click(screen.getByRole('link', { name: 'demo' }))
    expect(screen.queryByTitle('demo.html')).toBeNull()
  })
})
