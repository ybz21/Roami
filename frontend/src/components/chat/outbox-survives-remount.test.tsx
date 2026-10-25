// @vitest-environment jsdom
// 手机上切一下会话（点切换单里的另一条）、再切回来，排队中的气泡就没了——
// 其实消息已经真的发出去、排进了 TUI 队列，消失的只是本地这个提示。
//
// 根因：手机同一时间只挂一个 <ChatShell>（省终端连接），切走再切回来是真的卸载再重挂。
// 「排队中」原来存在 useState 里，组件一卸载这份状态就没了。
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

describe('排队中气泡扛得住手机切会话式的卸载重挂', () => {
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

  const shell = (name: string) => (
    <I18nProvider><AntApp>
      <ChatShell name={name} accent="var(--accent)" placeholder="说点什么" busy
        messages={[]} renderMessage={() => null} />
    </AntApp></I18nProvider>
  )

  it('发一条 → 卸载（切到另一个会话）→ 换个会话名重挂（那也是另一个会话）不串味 → 用原名重挂，气泡还在', async () => {
    const view = render(shell('s1'))
    const box = await screen.findByPlaceholderText('说点什么')
    fireEvent.change(box, { target: { value: '先跑一下测试' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(screen.getByText('先跑一下测试')).toBeTruthy())
    expect(screen.getByText('排队中，等它忙完')).toBeTruthy()

    // 手机上切到另一个会话：s1 的 ChatShell 被整个卸载
    view.unmount()

    // 中途看了眼别的会话——它自己的队列是空的，不该看到 s1 的气泡
    const other = render(shell('s2'))
    expect(other.queryByText('先跑一下测试')).toBeNull()
    other.unmount()

    // 切回 s1：气泡应该还在，不是发消息那一刻才存在的临时态
    render(shell('s1'))
    expect(await screen.findByText('先跑一下测试')).toBeTruthy()
    expect(screen.getByText('排队中，等它忙完')).toBeTruthy()
  })

  it('转录里真出现这句话之后，重挂不会把已经对过账的气泡翻出来', async () => {
    const view = render(shell('s1'))
    const box = await screen.findByPlaceholderText('说点什么')
    fireEvent.change(box, { target: { value: '跑一下测试' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(screen.getByText('排队中，等它忙完')).toBeTruthy())
    view.unmount()

    // 转录已经把这句话收进去了：这次带着 messages 重挂
    render(
      <I18nProvider><AntApp>
        <ChatShell name="s1" accent="var(--accent)" placeholder="说点什么" busy
          messages={[{ id: 'm1', role: 'user', blocks: [{ kind: 'text', text: '跑一下测试' }] } as any]}
          renderMessage={() => <div>已收进转录</div>} />
      </AntApp></I18nProvider>,
    )
    await screen.findByText('已收进转录')
    expect(screen.queryByText('排队中，等它忙完')).toBeNull()
  })
})
