// @vitest-environment jsdom
// 「停止」两级：Esc → Ctrl+C。
//
// 这条测试对着一个真实抱怨：终止按钮按了没反应。它只发 Esc，而 Esc 打断的是 TUI 的
// 当前回合——agent 卡在一个跑了十分钟的 bash 里时，底下那个子进程压根收不到信号。
// 所以 Esc 之后按钮要改口成 ^C（真中断），并且发完锁一小会儿：Claude Code 里
// 短时间连按两次 Ctrl+C 是退出整个 TUI，不是中断。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ChatShell } from './ChatShell'
import { I18nProvider } from '../../i18n'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

/** 注入过的按键，按发送顺序 */
function injectedKeys(fetchMock: ReturnType<typeof vi.fn>): string[][] {
  return fetchMock.mock.calls
    .filter(([url]) => String(url).includes('/keys'))
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)).keys)
}

describe('对话输入框：终止按钮', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    }))
    fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: {} }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  const renderShell = (busy = true) => render(
    <I18nProvider><AntApp>
      <ChatShell name="s1" accent="var(--accent)" placeholder="说点什么" busy={busy}
        messages={[]} renderMessage={() => null} />
    </AntApp></I18nProvider>,
  )

  it('managed Main stop and model commands use the host without native key injection', async () => {
    const command = vi.fn(async () => {})
    render(<I18nProvider><AntApp><ChatShell name="managed-main" accent="var(--accent)" placeholder="message" busy
      agent="claude" status={{ model: 'free' }} messages={[]} renderMessage={() => null} onCommand={command} /></AntApp></I18nProvider>)
    fireEvent.click(await screen.findByLabelText('停止'))
    await waitFor(() => expect(command).toHaveBeenCalledWith('/stop'))
    fireEvent.click(screen.getByLabelText('点击切换模型'))
    await waitFor(() => expect(command).toHaveBeenCalledWith('/model'))
    expect(injectedKeys(fetchMock)).toEqual([])
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/tasks/_/send'))).toBe(false)
  })

  it('第一下发 Esc，第二下发 Ctrl+C', async () => {
    renderShell()
    fireEvent.click(await screen.findByLabelText('停止'))
    await waitFor(() => expect(injectedKeys(fetchMock)).toEqual([['Escape']]))

    // Esc 没停住 → 按钮改口成强制中断
    const force = await screen.findByLabelText('强制中断 (Ctrl+C)')
    fireEvent.click(force)
    await waitFor(() => expect(injectedKeys(fetchMock)).toEqual([['Escape'], ['C-c']]))
  })

  it('发完 ^C 锁住按钮，手快点两下不会把 agent 关掉', async () => {
    vi.useFakeTimers()
    try {
      renderShell()
      fireEvent.click(screen.getByLabelText('停止'))
      const force = screen.getByLabelText('强制中断 (Ctrl+C)')
      fireEvent.click(force)
      fireEvent.click(force)
      fireEvent.click(force)
      expect(injectedKeys(fetchMock)).toEqual([['Escape'], ['C-c']])

      act(() => { vi.advanceTimersByTime(2600) })
      fireEvent.click(screen.getByLabelText('强制中断 (Ctrl+C)'))
      expect(injectedKeys(fetchMock)).toEqual([['Escape'], ['C-c'], ['C-c']])
    } finally { vi.useRealTimers() }
  })

  it('agent 停下来了，按钮退回 Esc 那一档', async () => {
    const { rerender } = renderShell()
    fireEvent.click(await screen.findByLabelText('停止'))
    await screen.findByLabelText('强制中断 (Ctrl+C)')

    rerender(
      <I18nProvider><AntApp>
        <ChatShell name="s1" accent="var(--accent)" placeholder="说点什么" busy={false}
          messages={[]} renderMessage={() => null} />
      </AntApp></I18nProvider>,
    )
    // 不忙了：那枚钮回到「发送」，下一轮生成重新从温和的 Esc 起步
    expect(screen.queryByLabelText('强制中断 (Ctrl+C)')).toBeNull()
  })
})
