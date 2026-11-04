// @vitest-environment jsdom
import { App as AntApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../../i18n'
import OkrProjectFiles from './OkrProjectFiles'

const state = vi.hoisted(() => ({ phone: false, missing: false, history: false, dirs: [] as string[] }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: state.phone }) }))
vi.mock('../../files/fileview', () => ({
  Viewer: ({ path }: { path: string }) => <div data-testid="desktop-file">{path}</div>,
  FileView: ({ path, onBack }: { path: string; onBack: () => void }) => <div data-testid="phone-file">{path}<button onClick={onBack}>Close preview</button></div>,
}))

const entry = (name: string, dir = false) => ({ name, dir, size: 12, mtime: 1, ctime: 1 })
beforeEach(() => {
  state.phone = false; state.missing = false; state.history = false; state.dirs = []
  localStorage.clear(); localStorage.setItem('ttmux-locale', 'zh-CN'); localStorage.setItem('ttmux.fileBrowseMode', 'flat')
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://fixture')
    const path = url.searchParams.get('path') || ''
    if (url.pathname === '/api/files') {
      state.dirs.push(path)
      if (state.missing && path === '/project/.roami/okr') return new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'Fixture directory does not exist' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })
      const entries = path === '/project' ? [entry('.roami', true), entry('artifacts', true), ...(state.history ? [entry('2026', true), entry('archive', true)] : [])]
        : path === '/project/.roami/okr' ? [entry('okr.json'), entry('dashboard.json'), entry('agents', true), entry('skills', true)]
          : path.endsWith('/agents') ? [entry('main.md')] : []
      return new Response(JSON.stringify({ data: { path, parent: path.replace(/\/[^/]+$/, ''), entries } }), { headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ data: {} }), { headers: { 'Content-Type': 'application/json' } })
  }))
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function view(props: Partial<Parameters<typeof OkrProjectFiles>[0]> = {}) {
  return <I18nProvider><AntApp><OkrProjectFiles dir="/project" active {...props} /></AntApp></I18nProvider>
}

it('opens the entire project root without extra configuration navigation or focus', async () => {
  render(view())
  await screen.findByText('artifacts')
  expect(state.dirs[0]).toBe('/project')
  expect(screen.queryByRole('button', { name: 'OKR 配置' })).toBeNull()
  expect(screen.queryByTestId('desktop-file')).toBeNull()
  expect(document.activeElement?.tagName).not.toBe('INPUT')
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true)
})

it('keeps existing external file requests and phone preview/back navigation', async () => {
  state.phone = true
  const { rerender } = render(view({ openRequest: { path: '/project/.roami/okr/agents/main.md', nonce: 1 } }))
  expect((await screen.findByTestId('phone-file')).textContent).toContain('/project/.roami/okr/agents/main.md')
  expect(screen.queryByTestId('desktop-file')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Close preview' }))
  await waitFor(() => expect(screen.queryByTestId('phone-file')).toBeNull())
  rerender(view({ openRequest: { path: '/project/.roami/okr/agents/main.md', nonce: 2 } }))
  expect((await screen.findByTestId('phone-file')).textContent).toContain('/project/.roami/okr/agents/main.md')
  expect(state.dirs).toContain('/project/.roami/okr/agents')
  rerender(view({ openRequest: { path: '/project/artifacts/tutorial.mp4', nonce: 3 } }))
  await waitFor(() => expect(screen.getByTestId('phone-file').textContent).toContain('/project/artifacts/tutorial.mp4'))
  await waitFor(() => expect(state.dirs).toContain('/project/artifacts'))
})

it('uses the requested memory directory as a normal file workspace', async () => {
  render(view({ dir: '/project/.roami/okr/memory' }))
  await waitFor(() => expect(state.dirs).toContain('/project/.roami/okr/memory'))
  expect(screen.queryByRole('button', { name: 'OKR 配置' })).toBeNull()
})

it('retains the actual missing-directory error without switching to another root', async () => {
  state.missing = true
  render(view({ dir: '/project/.roami/okr' }))
  expect((await screen.findByRole('alert')).textContent).toBe('Fixture directory does not exist')
  expect(state.dirs.every(path => path === '/project/.roami/okr')).toBe(true)
})
