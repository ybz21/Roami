// @vitest-environment jsdom
// 中文输入法里的回车是「上屏候选词」，不是「发送」。
//
// 这条测试对着一个真实 bug：粘贴图片拿到一段 @路径，接着打一句中文，按回车上屏——
// 结果消息提前发出去了，发出去的还缺了没上屏的那半截；而 send() 清的是 React 态，
// 浏览器随后把组合前的值写回 DOM，于是那段文件路径又冒回输入框里。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ChatShell } from './ChatShell'
import { I18nProvider } from '../../i18n'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

/** 发出去的消息体（没发就是 null） */
function sentMessages(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls
    .filter(([url]) => String(url).includes('/tasks/_/send'))
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)).msg)
}

describe('对话输入框：回车与输入法组合态', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    }))
    fetchMock = vi.fn(async () => jsonResponse({ data: {} }))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  const renderShell = () => render(
    <I18nProvider><AntApp>
      <ChatShell name="s1" accent="var(--accent)" placeholder="说点什么"
        messages={[]} renderMessage={() => null} />
    </AntApp></I18nProvider>,
  )

  it('组合中的回车只上屏，不发送', async () => {
    renderShell()
    const box = await screen.findByPlaceholderText('说点什么')

    fireEvent.change(box, { target: { value: '/tmp/a.png 看下这张' } })
    fireEvent.compositionStart(box)
    // 输入法把这记回车吃掉去上屏；浏览器仍然派一个 isComposing 的 keydown 过来
    fireEvent.keyDown(box, { key: 'Enter', code: 'Enter', keyCode: 229, isComposing: true })

    expect(sentMessages(fetchMock)).toEqual([])
    expect((box as HTMLTextAreaElement).value).toBe('/tmp/a.png 看下这张')
  })

  it('上屏之后再按回车，整句发出去', async () => {
    renderShell()
    const box = await screen.findByPlaceholderText('说点什么')

    fireEvent.change(box, { target: { value: '/tmp/a.png 看下这张图' } })
    fireEvent.compositionStart(box)
    fireEvent.compositionEnd(box)
    fireEvent.keyDown(box, { key: 'Enter', code: 'Enter' })

    await waitFor(() => expect(sentMessages(fetchMock)).toEqual(['/tmp/a.png 看下这张图']))
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe(''))
    const request = fetchMock.mock.calls.find(([url]) => String(url).includes('/tasks/_/send'))
    expect(JSON.parse(String((request?.[1] as RequestInit).body)).activity).toBe('dialogue')
  })
})
