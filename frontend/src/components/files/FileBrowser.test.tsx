// @vitest-environment jsdom
import { App as AntApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FileBrowser from './FileBrowser'
import { I18nProvider } from '../../i18n'

vi.mock('../../App', () => ({ recentDirs: () => [] }))

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('FileBrowser folder context menu', () => {
  let nativeGetComputedStyle: typeof window.getComputedStyle

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    }))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/files?')) {
        return jsonResponse({
          data: {
            path: '/workspace',
            parent: '/',
            entries: [{ name: 'folder', dir: true, size: 0, mtime: 1, ctime: 1 }],
          },
        })
      }
      if (url.includes('/api/upload')) return jsonResponse({ data: { saved: ['/workspace/sample/note.txt'] } })
      return jsonResponse({ data: {} })
    }))
    nativeGetComputedStyle = window.getComputedStyle
    vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  const renderBrowser = () => render(
    <I18nProvider>
      <AntApp>
        {/* 原来这里套的是 FloatingFileDrawer（右侧 420 浮层）。它已经下线——文件树
            进了 Inspector 列（图纸 panels-desktop.html），容器只剩一个定宽的 flex 列。 */}
        <div style={{ display: 'flex', flexDirection: 'column', width: 420, height: 600 }}>
          <FileBrowser dir="/workspace" layout="dock" />
        </div>
      </AntApp>
    </I18nProvider>,
  )

  const openFolderMenu = async () => {
    const folder = await screen.findByText('folder')
    const row = folder.closest('.cc-filerow')
    expect(row).not.toBeNull()
    fireEvent.contextMenu(row!)
    return screen.findByText('重命名')
  }

  it('uploads a selected folder with its relative paths', async () => {
    const { container } = renderBrowser()
    fireEvent.click(screen.getByRole('button', { name: '上传到当前目录' }))
    fireEvent.click(await screen.findByText('上传文件夹'))

    const input = container.querySelector('input[webkitdirectory]') as HTMLInputElement
    expect(input).toBeTruthy()
    const file = new File(['content'], 'note.txt', { type: 'text/plain' })
    Object.defineProperty(file, 'webkitRelativePath', { value: 'sample/note.txt' })
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => {
      const request = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/api/upload'))
      expect(request).toBeTruthy()
      const form = request![1]?.body as FormData
      expect(form.get('dir')).toBe('/workspace')
      expect(form.getAll('paths')).toEqual(['sample/note.txt'])
      expect(form.getAll('files')).toHaveLength(1)
    })
  })

  it('uploads into the folder selected from its context menu', async () => {
    const { container } = renderBrowser()
    await openFolderMenu()
    fireEvent.click(screen.getByText('上传文件夹'))

    const file = new File(['content'], 'note.txt')
    Object.defineProperty(file, 'webkitRelativePath', { value: 'sample/note.txt' })
    fireEvent.change(container.querySelector('input[webkitdirectory]')!, { target: { files: [file] } })

    await waitFor(() => {
      const request = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/api/upload'))
      expect((request?.[1]?.body as FormData).get('dir')).toBe('/workspace/folder')
    })
  })

  it('refreshes the directory after the Android folder upload completes', async () => {
    renderBrowser()
    await screen.findByText('folder')
    const callsBefore = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/api/files?')).length
    window.dispatchEvent(new CustomEvent('roami-folder-upload', { detail: { saved: 2 } }))
    await waitFor(() => {
      const callsAfter = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/api/files?')).length
      expect(callsAfter).toBeGreaterThan(callsBefore)
    })
  })

  it('stays open while moving over items and runs the selected folder action', async () => {
    renderBrowser()
    const rename = await openFolderMenu()
    const menu = rename.closest('.ant-dropdown')
    expect(menu).not.toBeNull()
    expect(menu?.className.includes('slide-')).toBe(false)
    expect(menu?.classList.contains('tt-file-context-menu')).toBe(true)

    for (const label of ['新建目录', '移动到…', '属性', '重命名']) {
      const item = screen.getByText(label)
      fireEvent.mouseEnter(item)
      fireEvent.mouseMove(item)
      await new Promise((resolve) => setTimeout(resolve, 30))
      expect(menu?.classList.contains('ant-dropdown-hidden')).toBe(false)
      expect(screen.getByText('重命名')).toBeTruthy()
    }

    fireEvent.click(rename)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    expect(screen.getByDisplayValue('folder')).toBeTruthy()
  })

  it.each([
    ['新建目录', '新建目录'],
    ['移动到…', '移动到'],
    ['复制到…', '复制到'],
    ['属性', '属性'],
    ['删除', '删除此文件夹及其中所有内容？'],
  ])('runs the “%s” folder action', async (menuLabel, dialogText) => {
    renderBrowser()
    await openFolderMenu()
    fireEvent.click(screen.getByText(menuLabel))

    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain(dialogText)
  })

  it('runs the open-folder action and navigates to the target directory', async () => {
    renderBrowser()
    await openFolderMenu()
    fireEvent.click(screen.getByText('打开目录'))

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/files?path=%2Fworkspace%2Ffolder',
        expect.objectContaining({ method: 'GET' }),
      )
    })
  })
})

describe('FileBrowser file moves', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    localStorage.setItem('ttmux.fileBrowseMode', 'tree')
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    }))
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('moves a dragged file into a folder and refreshes the expanded tree', async () => {
    let moved = false
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/file/move')) {
        expect(init?.method).toBe('POST')
        expect(JSON.parse(String(init?.body))).toEqual({ path: '/workspace/report.md', target: '/workspace/folder' })
        moved = true
        return jsonResponse({ data: { path: '/workspace/folder/report.md' } })
      }
      if (url.includes('/api/files?')) {
        const path = new URL(url, 'http://x').searchParams.get('path')
        return jsonResponse({ data: {
          path,
          parent: path === '/workspace' ? '/' : '/workspace',
          entries: path === '/workspace'
            ? [{ name: 'folder', dir: true, size: 0, mtime: 1, ctime: 1 }, ...(!moved ? [{ name: 'report.md', dir: false, size: 1, mtime: 1, ctime: 1 }] : [])]
            : moved ? [{ name: 'report.md', dir: false, size: 1, mtime: 1, ctime: 1 }] : [],
        } })
      }
      return jsonResponse({ data: {} })
    }))
    render(<I18nProvider><AntApp><FileBrowser dir="/workspace" layout="dock" /></AntApp></I18nProvider>)
    const folder = (await screen.findByText('folder')).closest('.cc-filerow')!
    fireEvent.click(folder)
    const source = (await screen.findByText('report.md')).closest('.cc-filerow')!
    const values = new Map<string, string>()
    const dataTransfer = {
      types: [] as string[],
      setData(type: string, value: string) { values.set(type, value); this.types.push(type) },
      getData(type: string) { return values.get(type) || '' },
      effectAllowed: 'uninitialized',
      dropEffect: 'none',
    }
    fireEvent.dragStart(source, { dataTransfer })
    expect(dataTransfer.effectAllowed).toBe('copyMove')
    fireEvent.dragOver(folder, { dataTransfer })
    expect(folder.classList.contains('tt-file-drop-target')).toBe(true)
    fireEvent.drop(folder, { dataTransfer })
    await waitFor(() => expect(moved).toBe(true))
    await waitFor(() => expect(source.isConnected).toBe(false))
    expect(screen.getByText('report.md')).toBeTruthy()
  })
})

// 对话里点 Read/Edit 的文件名 → 在这个浏览器里打开它。
// 之前这条路走的是「跳去文件页」，人被带离会话页，看到的是文件页左边那棵树。
describe('FileBrowser openRequest（对话里点文件名）', () => {
  let seenDirs: string[] = []

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    seenDirs = []
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    }))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/files?')) {
        const dir = new URL(url, 'http://x').searchParams.get('path') || ''
        seenDirs.push(dir)
        return jsonResponse({ data: { path: dir || '/workspace', parent: '/', entries: [] } })
      }
      if (url.includes('/api/file?')) {
        return jsonResponse({ data: { content: 'hello', truncated: false } })
      }
      return jsonResponse({ data: {} })
    }))
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  const renderWith = (openRequest?: { path: string; nonce: number }) => render(
    <I18nProvider>
      <AntApp>
        <div style={{ display: 'flex', flexDirection: 'column', width: 420, height: 600 }}>
          <FileBrowser dir="/workspace" layout="dock" openRequest={openRequest} />
        </div>
      </AntApp>
    </I18nProvider>,
  )

  it('把树导航到文件所在目录，而不是让文件凭空出现', async () => {
    renderWith({ path: '/workspace/frontend/src/App.tsx', nonce: 1 })
    await waitFor(() => expect(seenDirs).toContain('/workspace/frontend/src'))
  })

  it('没有 openRequest 时不导航到别处（保持原有行为）', async () => {
    renderWith()
    await waitFor(() => expect(seenDirs.length).toBeGreaterThan(0))
    expect(seenDirs.every((d) => !d.includes('/frontend/src'))).toBe(true)
  })

  it('同一文件再点一次：nonce 变了才重新打开', async () => {
    const { rerender } = renderWith({ path: '/workspace/a.ts', nonce: 1 })
    await waitFor(() => expect(seenDirs).toContain('/workspace'))
    const before = seenDirs.length
    // 同 nonce 重渲染：不该再跑一次
    rerender(
      <I18nProvider><AntApp>
        <div><FileBrowser dir="/workspace" layout="dock" openRequest={{ path: '/workspace/a.ts', nonce: 1 }} /></div>
      </AntApp></I18nProvider>,
    )
    expect(seenDirs.length).toBe(before)
  })
})

// 抽屉里的预览必须**就地铺开**，不能弹模态框：
// 抽屉本来就是一块常驻侧栏，从里面再弹一个居中浮层等于把它整个盖住。
describe('FileBrowser dock 预览不弹模态框', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    }))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/files?')) {
        const dir = new URL(url, 'http://x').searchParams.get('path') || ''
        return jsonResponse({ data: { path: dir || '/workspace', parent: '/', entries: [] } })
      }
      if (url.includes('/api/file?')) return jsonResponse({ data: { content: 'hello', truncated: false } })
      return jsonResponse({ data: {} })
    }))
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('打开文件后没有 .ant-modal，预览就在面板里', async () => {
    const { container } = render(
      <I18nProvider><AntApp>
        <div style={{ display: 'flex', flexDirection: 'column', width: 420, height: 600 }}>
          <FileBrowser dir="/workspace" layout="dock" openRequest={{ path: '/workspace/a.md', nonce: 1 }} />
        </div>
      </AntApp></I18nProvider>,
    )
    // 预览起来了（内容或加载态出现在面板内），且**没有**模态框
    await waitFor(() => expect(container.textContent || '').toContain('a.md'))
    expect(document.querySelector('.ant-modal')).toBeNull()
  })

  // 换会话（dir 变了）→ 上个会话那个文件不能还挂在预览里：树都回新工作目录了，
  // 右边留着别的项目的文件，看起来就是「文件面板自己带出个旧文件」。
  it('换会话就收掉上个会话的预览', async () => {
    const view = (dir: string) => (
      <I18nProvider><AntApp>
        <div style={{ display: 'flex', flexDirection: 'column', width: 420, height: 600 }}>
          <FileBrowser dir={dir} layout="dock" openRequest={{ path: '/workspace/a.md', nonce: 1 }} />
        </div>
      </AntApp></I18nProvider>
    )
    const { container, rerender } = render(view('/workspace'))
    await waitFor(() => expect(container.textContent || '').toContain('a.md'))

    rerender(view('/other'))
    await waitFor(() => expect(container.textContent || '').not.toContain('a.md'))
  })
})

// 抽屉够宽时「文件夹 / 文件」并排两栏，中间可拖；窄了自动退回单栏。
// jsdom 不排版，所以用 getBoundingClientRect 桩来喂宽度。
describe('FileBrowser dock 两栏与分界拖动', () => {
  let panelWidth = 800
  let nativeRect: typeof Element.prototype.getBoundingClientRect

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    class RO {
      constructor(private cb: () => void) {}
      observe() { this.cb() }
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', RO)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    }))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/files?')) {
        const dir = new URL(url, 'http://x').searchParams.get('path') || ''
        return jsonResponse({ data: { path: dir || '/workspace', parent: '/', entries: [] } })
      }
      if (url.includes('/api/file?')) return jsonResponse({ data: { content: 'hello', truncated: false } })
      return jsonResponse({ data: {} })
    }))
    nativeRect = Element.prototype.getBoundingClientRect
    Element.prototype.getBoundingClientRect = function () {
      return { width: panelWidth, height: 600, top: 0, left: 0, right: panelWidth, bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect
    }
  })
  afterEach(() => {
    Element.prototype.getBoundingClientRect = nativeRect
    cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals()
  })

  const renderDock = () => render(
    <I18nProvider><AntApp>
      <div style={{ display: 'flex', flexDirection: 'column', height: 600 }}>
        <FileBrowser dir="/workspace" layout="dock" openRequest={{ path: '/workspace/a.md', nonce: 1 }} />
      </div>
    </AntApp></I18nProvider>,
  )

  it('够宽时并排两栏，中间有可拖的分界', async () => {
    panelWidth = 800
    const { container } = renderDock()
    await waitFor(() => expect(container.querySelector('[data-resize-handle="filetree"]')).not.toBeNull())
    expect(document.querySelector('.ant-modal')).toBeNull()
  })

  it('窄到放不下两栏时退回单栏——宁可少一栏，也不要两栏都残', async () => {
    panelWidth = 420
    const { container } = renderDock()
    await waitFor(() => expect(container.textContent || '').toContain('a.md'))
    expect(container.querySelector('[data-resize-handle="filetree"]')).toBeNull()
  })

  // 面板是从屏幕右缘拉出来的：列表钉在右缘，文件内容往它左边长。
  // 反过来的话，一点开文件，你刚点的那一列自己跑到左半边去了。
  it('列表在右、内容在左', async () => {
    panelWidth = 800
    const { container } = renderDock()
    const rail = await waitFor(() => {
      const r = container.querySelector('[data-resize-handle="filetree"]')
      if (!r) throw new Error('rail not ready')
      return r
    })
    const cols = Array.from(rail.parentElement!.children)
    const railAt = cols.indexOf(rail)
    // 把手左边是预览（带文件名），右边是列表（带路径输入框）
    expect(cols[railAt - 1].textContent || '').toContain('a.md')
    expect(cols[railAt + 1].querySelector('input')).not.toBeNull()
  })
})
