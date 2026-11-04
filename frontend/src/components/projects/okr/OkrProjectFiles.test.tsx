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
  return <I18nProvider><AntApp><OkrProjectFiles dir="/project" bundleRoot=".roami/okr" active {...props} /></AntApp></I18nProvider>
}

it('opens the actual saved bundle and returns to assets or the bundle from nested directories', async () => {
  render(view())
  expect(await screen.findByText('okr.json')).toBeTruthy()
  expect(state.dirs[0]).toBe('/project/.roami/okr')
  fireEvent.click(screen.getByText('agents'))
  await screen.findByText('main.md')
  fireEvent.click(screen.getByRole('button', { name: '项目目录' }))
  expect(await screen.findByText('artifacts')).toBeTruthy()
  expect(screen.queryByText('.roami')).toBeNull()
  expect(screen.queryByTestId('desktop-file')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'OKR 配置' }))
  await screen.findByText('dashboard.json')
  expect(state.dirs[state.dirs.length - 1]).toBe('/project/.roami/okr')
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

it('shows assets and an honest hint before an OKR bundle has been saved', async () => {
  render(view({ bundleRoot: undefined }))
  await screen.findByText('artifacts')
  expect(screen.getByText('保存 OKR 后，此处会显示项目中的配置文件。')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'OKR 配置' })).toBeNull()
  expect(state.dirs).toEqual(['/project'])
})

it('retains the real missing-directory error and offers assets without stale bundle entries', async () => {
  render(view())
  await screen.findByText('okr.json')
  fireEvent.click(screen.getByRole('button', { name: '项目目录' }))
  await screen.findByText('artifacts')
  state.missing = true
  fireEvent.click(screen.getByRole('button', { name: 'OKR 配置' }))
  expect((await screen.findByRole('alert')).textContent).toBe('Fixture directory does not exist')
  expect(screen.queryByText('artifacts')).toBeNull()
  expect(screen.queryByText('okr.json')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '项目目录' }))
  await screen.findByText('artifacts')
})

it('opens team, memory, connectors and existing dated or historical directories directly', async () => {
  state.history = true
  render(view())
  await screen.findByRole('button', { name: '2026 年产物' })
  for (const [label, path] of [['团队', '/project/.roami/okr/agents'], ['记忆', '/project/.roami/okr/memory'], ['数据连接', '/project/.roami/okr/connectors'], ['2026 年产物', '/project/2026'], ['历史资料', '/project/archive']]) {
    fireEvent.click(screen.getByRole('button', { name: label }))
    await waitFor(() => expect(state.dirs).toContain(path))
    expect(screen.getByRole('button', { name: label }).getAttribute('aria-pressed')).toBe('true')
  }
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true)
})

it('keeps the goal file list focused and opens a preview only for a selected file', async () => {
  render(view())
  await screen.findByText('okr.json')
  expect(screen.queryByText('选择左侧文件查看预览')).toBeNull()
  expect(document.activeElement?.tagName).not.toBe('INPUT')
  fireEvent.click(screen.getByText('okr.json'))
  expect((await screen.findByTestId('desktop-file')).textContent).toBe('/project/.roami/okr/okr.json')
})
