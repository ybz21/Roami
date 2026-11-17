// @vitest-environment jsdom
import { WorkspaceStateStore, type ViewStateScope } from '../../workspace-state'
import { App as AntApp } from 'antd'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FileWorkspace from './FileWorkspace'
import { FileWorkspaceStateProvider } from './file-workspace-state'
import { I18nProvider } from '../../i18n'
import { requestIntent, OPEN_FILE_INTENT } from '../../intents'

vi.mock('./FileBrowser', () => ({ default: () => <div data-testid="file-browser" /> }))
vi.mock('./fileview', () => ({ FileView: () => <div data-testid="file-view" /> }))

class PointerEventStub extends MouseEvent {
  readonly pointerId: number

  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init)
    this.pointerId = init.pointerId ?? 0
  }
}

describe('FileWorkspace resize shield', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    vi.stubGlobal('CSS', { escape: (value: string) => value })
    vi.stubGlobal('PointerEvent', PointerEventStub)
    Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', {
      configurable: true,
      value: vi.fn(),
    })
    Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', {
      configurable: true,
      value: vi.fn(() => false),
    })
  })

  afterEach(() => {
    cleanup()
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  const renderWorkspace = (memory?: ViewStateScope) => render(
    <I18nProvider>
      <AntApp>
        <FileWorkspaceStateProvider scope={memory}><FileWorkspace dir="/workspace" /></FileWorkspaceStateProvider>
      </AntApp>
    </I18nProvider>,
  )

  it('restores tab order, selection and closed tabs after navigation', () => {
    const memory = new WorkspaceStateStore().scope('files')
    const first = renderWorkspace(memory)
    act(() => requestIntent(OPEN_FILE_INTENT, { path: '/workspace/one.txt' }))
    act(() => requestIntent(OPEN_FILE_INTENT, { path: '/workspace/two.txt' }))
    const firstTab = first.container.querySelector<HTMLElement>('[data-tab-key="/workspace/one.txt"]')!
    fireEvent.click(firstTab)
    first.unmount()
    const second = renderWorkspace(memory)
    expect([...second.container.querySelectorAll('[data-tab-key]')].map(tab => tab.getAttribute('data-tab-key'))).toEqual(['/workspace/one.txt', '/workspace/two.txt'])
    expect(memory.get('workspace.activeA')).toBe('/workspace/one.txt')
    const tab = second.container.querySelector<HTMLElement>('[data-tab-key="/workspace/one.txt"]')!
    fireEvent.click(tab.querySelector('.cc-tabx')!)
    second.unmount()
    const third = renderWorkspace(memory)
    expect([...third.container.querySelectorAll('[data-tab-key]')].map(tab => tab.getAttribute('data-tab-key'))).toEqual(['/workspace/two.txt'])
  })

  it('keeps dock resize events above iframe previews until pointerup', () => {
    const { container } = renderWorkspace()
    const handle = container.querySelector<HTMLElement>('[data-resize-handle="dock"]')!
    const dock = handle.previousElementSibling as HTMLElement

    // 起点按**当前实际宽度**取，别写死默认值：默认宽度调过一次（280 → 240），
    // 写死的话这条测的就成了「默认值有没有被改」，而它想测的是「拖动跟不跟手」。
    const startW = parseInt(dock.style.flex.split(' ')[2], 10)
    fireEvent.pointerDown(handle, { pointerId: 7, clientX: startW })

    const shield = document.body.querySelector<HTMLElement>('[data-pointer-resize-shield="true"]')!
    expect(shield).not.toBeNull()
    expect(document.body.style.userSelect).toBe('none')
    expect(document.body.style.cursor).toBe('col-resize')

    fireEvent.pointerMove(shield, { pointerId: 7, clientX: startW + 80 })
    expect(dock.style.flex).toBe(`0 0 ${startW + 80}px`)

    fireEvent.pointerUp(shield, { pointerId: 7, clientX: startW + 80 })
    expect(document.body.querySelector('[data-pointer-resize-shield="true"]')).toBeNull()
    expect(document.body.style.userSelect).toBe('')
    expect(document.body.style.cursor).toBe('')
    expect(localStorage.getItem('ttmux.fileDockW')).toBe(String(startW + 80))
  })

  it('removes the shield and restores page styles when the window loses focus', () => {
    const { container } = renderWorkspace()
    const handle = container.querySelector<HTMLElement>('[data-resize-handle="dock"]')!
    document.body.style.userSelect = 'text'
    document.body.style.cursor = 'default'

    fireEvent.pointerDown(handle, { pointerId: 9, clientX: 280 })
    fireEvent.blur(window)

    expect(document.body.querySelector('[data-pointer-resize-shield="true"]')).toBeNull()
    expect(document.body.style.userSelect).toBe('text')
    expect(document.body.style.cursor).toBe('default')
  })
})

// 从对话里点 Read/Edit 的路径开文件：必须开到**右栏**。
// A 栏的首 tab 是会话（终端/对话）本身，开在那儿等于把你正在看的对话顶掉——
// 而点这个路径的动机恰恰是「一边对着看」。
describe('FileWorkspace 从对话打开文件', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    vi.stubGlobal('CSS', { escape: (value: string) => value })
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  const renderWithSession = () => render(
    <I18nProvider>
      <AntApp>
        <FileWorkspace dir="/workspace" leadingTab={<span data-testid="lead-tab" />} leadingTitle="sess"
          leadingContent={<div data-testid="chat" />} />
      </AntApp>
    </I18nProvider>,
  )

  const tabTexts = (container: HTMLElement) =>
    [...container.querySelectorAll('[data-tab-key]')].map((e) => (e.textContent || '').trim())

  it('side 意图把文件开成第二栏，会话首 tab 仍在', () => {
    const { container } = renderWithSession()
    expect(container.querySelectorAll('[data-drop-group]').length).toBeGreaterThan(0)

    act(() => { requestIntent(OPEN_FILE_INTENT, { path: '/workspace/a.ts', side: true }) })

    const keys = [...container.querySelectorAll('[data-tab-key]')].map((e) => e.getAttribute('data-tab-key'))
    expect(keys).toContain('lead')                      // 会话首 tab 还在
    expect(keys).toContain('/workspace/a.ts')           // 文件开出来了
    // 两个编辑组 → 分栏成立（B 栏非空才会渲染第二个 pane）
    expect(container.querySelectorAll('[data-drop-content="1"]').length).toBe(2)
    expect(tabTexts(container).length).toBeGreaterThan(1)
  })

  it('不带 side 时沿用旧行为：开在 A 栏（⌘K 搜索那条路）', () => {
    const { container } = renderWithSession()
    act(() => { requestIntent(OPEN_FILE_INTENT, { path: '/workspace/b.ts' }) })
    expect(container.querySelectorAll('[data-drop-content="1"]').length).toBe(1)
  })

  it('没有会话首 tab 时（纯文件页）side 不生效，不该无故拆出空的一栏', () => {
    const { container } = render(
      <I18nProvider><AntApp><FileWorkspace dir="/workspace" /></AntApp></I18nProvider>,
    )
    act(() => { requestIntent(OPEN_FILE_INTENT, { path: '/workspace/c.ts', side: true }) })
    expect(container.querySelectorAll('[data-drop-content="1"]').length).toBe(1)
  })
})
