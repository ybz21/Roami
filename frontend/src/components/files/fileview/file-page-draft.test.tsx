// @vitest-environment jsdom
import { WorkspaceStateStore, type ViewStateScope } from '../../../workspace-state'
import { App as AntApp } from 'antd'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../../i18n'
import { FileWorkspaceStateProvider } from '../file-workspace-state'
import { api } from '../../../api'
import ViewBoundary from '../../../app/ViewBoundary'
import { FileView } from './FileView'

vi.mock('../../../api', () => ({ api: vi.fn(async () => ({ data: { content: 'original', mtime: 1 } })) }))
vi.mock('../../../agent-registry', () => ({ useRegisteredAgents: () => [] }))
vi.mock('../../../theme', () => ({ useThemeMode: () => ({ mode: 'dark' }) }))
vi.mock('./CodeView', () => ({ CodeView: ({ value, onChange }: any) => <textarea aria-label="editor" value={value} onChange={event => onChange(event.target.value)} /> }))
vi.mock('./MarkdownView', () => ({ MarkdownView: () => <div data-testid="preview" /> }))
afterEach(cleanup)
beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(api).mockResolvedValue({ data: { content: 'original', mtime: 1 } }) })

it('restores unsaved text and source/preview mode after leaving the file page', async () => {
  localStorage.setItem('ttmux-locale', 'en-US')
  const memory = new WorkspaceStateStore().scope('files')
  const dirty = vi.fn()
  const mount = () => render(<I18nProvider><AntApp><FileWorkspaceStateProvider scope={memory}>
    <FileView path="/workspace/note.md" accent="var(--accent)" inline tabbed onClose={() => {}} onOpenPath={() => {}} onDirtyChange={dirty} />
  </FileWorkspaceStateProvider></AntApp></I18nProvider>)
  const first = mount()
  fireEvent.change(await screen.findByRole('textbox', { name: 'editor' }), { target: { value: 'unsaved draft' } })
  expect(dirty).toHaveBeenLastCalledWith('/workspace/note.md', true)
  fireEvent.click(screen.getByRole('button', { name: /预览|Preview/ }))
  expect(screen.getByTestId('preview')).toBeTruthy()
  first.unmount()
  const second = mount()
  expect(screen.getByTestId('preview')).toBeTruthy()
  expect(dirty).toHaveBeenLastCalledWith('/workspace/note.md', true)
  fireEvent.click(screen.getByRole('button', { name: /源码|Source/ }))
  expect((screen.getByRole('textbox', { name: 'editor' }) as HTMLTextAreaElement).value).toBe('unsaved draft')
  second.unmount()
})

it('loads only active file tabs, aborts reads, and evicts clean content', async () => {
  const memory = new WorkspaceStateStore().scope('files')
  const view = (active: boolean, path = '/workspace/one.txt') => <AntApp><FileWorkspaceStateProvider scope={memory}>
    <FileView path={path} active={active} accent="var(--accent)" inline onClose={() => {}} onOpenPath={() => {}} />
  </FileWorkspaceStateProvider></AntApp>
  const rendered = render(view(false))
  expect(api).not.toHaveBeenCalled()
  rendered.rerender(view(true))
  expect((await screen.findByRole('textbox', { name: 'editor' }) as HTMLTextAreaElement).value).toBe('original')
  const signal = vi.mocked(api).mock.calls[0][3]?.signal
  expect(memory.store.stats().entries).toBeLessThan(4)
  rendered.rerender(view(false))
  expect(signal?.aborted).toBe(true)
  rendered.rerender(view(true))
  await screen.findByRole('textbox', { name: 'editor' })
  expect(api).toHaveBeenCalledTimes(2)
  vi.mocked(api).mockResolvedValueOnce({ data: { content: 'second file', mtime: 2 } })
  rendered.rerender(view(true, '/workspace/two.txt'))
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'editor' }) as HTMLTextAreaElement).value).toBe('second file'))
})

it('finishes a save across navigation and releases its saved baseline', async () => {
  const memory = new WorkspaceStateStore().scope('files')
  let finish!: (value: any) => void
  const view = (active: boolean) => <I18nProvider><ViewBoundary page="files" active={active} mobile={false} hasDock={false}>
    <FileWorkspaceStateProvider scope={memory}><FileView path="/workspace/save.txt" accent="var(--accent)" inline onClose={() => {}} onOpenPath={() => {}} /></FileWorkspaceStateProvider>
  </ViewBoundary></I18nProvider>
  const rendered = render(view(true))
  fireEvent.change(await screen.findByRole('textbox', { name: 'editor' }), { target: { value: 'saved text' } })
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  fireEvent.click(screen.getByRole('button', { name: /Save|保\s*存/ }))
  rendered.rerender(view(false))
  await act(async () => { finish({ data: { mtime: 2 } }) })
  expect(!!memory.child('file', '/workspace/save.txt', 'source').get('edit')).toBe(false)
  expect(rendered.container.querySelector('[data-page=files]')?.childElementCount).toBe(0)
  vi.mocked(api).mockResolvedValueOnce({ data: { content: 'saved text', mtime: 2 } })
  rendered.rerender(view(true))
  expect((await screen.findByRole('textbox', { name: 'editor' }) as HTMLTextAreaElement).value).toBe('saved text')
})
