// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { ChatShell } from './ChatShell'
import { I18nProvider } from '../../i18n'

class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('ttmux-locale', 'zh-CN')
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
    matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(),
  }))
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ data: {} }), { status: 200 })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const messages = Array.from({ length: 60 }, (_, i) => ({ id: 'm' + i, role: 'assistant', blocks: [{ kind: 'text', text: 'm' + i }] }))

function mount(load: () => Promise<void>) {
  const view = render(
    <I18nProvider><AntApp>
      <ChatShell name="autoload" accent="var(--accent)" placeholder="说点什么"
        messages={messages as any} renderMessage={(m) => <div>{m.id}</div>} hasEarlier onLoadEarlier={load} />
    </AntApp></I18nProvider>,
  )
  const box = view.container.querySelector('.conversation-transcript')!.parentElement as HTMLDivElement
  const metrics = (scrollHeight: number, clientHeight: number) => {
    Object.defineProperty(box, 'scrollHeight', { configurable: true, value: scrollHeight })
    Object.defineProperty(box, 'clientHeight', { configurable: true, value: clientHeight })
  }
  const scrollTo = (top: number) => { box.scrollTop = top; fireEvent.scroll(box) }
  return { view, metrics, scrollTo }
}

it('上滑到自己顶就自动往回翻一页，停在那儿只翻一次', async () => {
  const load = vi.fn(async () => {})
  const { metrics, scrollTo } = mount(load)
  metrics(3000, 800)

  scrollTo(0)
  expect(load).toHaveBeenCalledTimes(1)
  await act(async () => {}) // 等这一页的请求落地，才轮得到下一次

  // 手指还贴着顶（锚定把位置推得不够远时也停在这儿）：不连着拉
  scrollTo(40)
  expect(load).toHaveBeenCalledTimes(1)

  // 往下滚出重上膛线，再滑回顶：下一批
  scrollTo(400)
  scrollTo(0)
  expect(load).toHaveBeenCalledTimes(2)
})

it('内容还没撑满一屏时不自动加载，留给那颗按钮', () => {
  const load = vi.fn(async () => {})
  const { metrics, scrollTo } = mount(load)
  metrics(800, 800)
  scrollTo(0)
  expect(load).not.toHaveBeenCalled()
})
