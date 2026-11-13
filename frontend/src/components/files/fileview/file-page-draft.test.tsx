// @vitest-environment jsdom
import { App as AntApp } from 'antd'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../../i18n'
import { FilePageMemoryProvider } from '../file-page-memory'
import { FileView } from './FileView'

vi.mock('../../../api', () => ({ api: vi.fn(async () => ({ data: { content: 'original', mtime: 1 } })) }))
vi.mock('../../../agent-registry', () => ({ useRegisteredAgents: () => [] }))
vi.mock('../../../theme', () => ({ useThemeMode: () => ({ mode: 'dark' }) }))
vi.mock('./CodeView', () => ({ CodeView: ({ value, onChange }: any) => <textarea aria-label="editor" value={value} onChange={event => onChange(event.target.value)} /> }))
vi.mock('./MarkdownView', () => ({ MarkdownView: () => <div data-testid="preview" /> }))
afterEach(cleanup)

it('restores unsaved text and source/preview mode after leaving the file page', async () => {
  localStorage.setItem('ttmux-locale', 'en-US')
  const memory = new Map()
  const dirty = vi.fn()
  const mount = () => render(<I18nProvider><AntApp><FilePageMemoryProvider memory={memory}>
    <FileView path="/workspace/note.md" accent="var(--accent)" inline tabbed onClose={() => {}} onOpenPath={() => {}} onDirtyChange={dirty} />
  </FilePageMemoryProvider></AntApp></I18nProvider>)
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
