// @vitest-environment jsdom
// 右栏分隔条的位置存了，就必须读得回来。
//
// 这条测试对着一个真实回归：偏好是异步 GET 的，而 useWorkspaceLayout 里那句
// 「只同步一次」用的是"effect 跑过没有"——mount 那一跑手里还是默认值，标志位就此置上，
// 真正带着用户宽度的那一跑被 early-return 挡掉。表现是宽度一直在写进
// preferences.json，界面却每次刷新都把分隔条挪回默认位。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

const SAVED = 1100
const VIEWPORT = 1920

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

// 偏好模块在**导入时**就读一次本地镜像，所以每个用例都要在布好 localStorage 之后重新导入
async function freshModules() {
  vi.resetModules()
  const prefs = await import('../../preferences')
  const layout = await import('./useWorkspaceLayout')
  return { ...prefs, ...layout }
}

describe('工作区分隔条位置的恢复', () => {
  beforeEach(() => {
    localStorage.clear()
    window.innerWidth = VIEWPORT
    // large 档才有右栏这一列；min-width 一律命中 → 'large'，指针留在细指针档
    vi.stubGlobal('matchMedia', vi.fn((q: string) => ({
      matches: q.includes('min-width'),
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    })))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/api/preferences')) {
        // /api 统一 { data } 包一层
        return jsonResponse({ data: { _migrated: true, workspace: { inspectorWidth: SAVED, navCollapsed: true } } })
      }
      return jsonResponse({ data: {} })
    }))
  })

  afterEach(() => { vi.unstubAllGlobals() })

  it('偏好从服务端回来后，inspectorWidth 用的是存下来的值', async () => {
    const m = await freshModules()
    const { result } = renderHook(() => m.useWorkspaceLayout(true))

    // 首帧还没有偏好：拿默认宽。旧实现正是在这一刻把标志位置上，于是到此为止
    expect(result.current.inspectorWidth).toBe(m.INSPECTOR_DEFAULT)

    await m.loadPreferences()
    await waitFor(() => expect(result.current.inspectorWidth).toBe(SAVED))
  })

  it('本地镜像让首帧就画在存下来的位置上（不必等 GET 回来才跳一次）', async () => {
    localStorage.setItem('ttmux.workspace', JSON.stringify({ inspectorWidth: SAVED, navCollapsed: true }))
    const m = await freshModules()
    const { result } = renderHook(() => m.useWorkspaceLayout(true))
    expect(result.current.inspectorWidth).toBe(SAVED)
  })

  it('用户拖过之后不再被服务端那份盖掉', async () => {
    const m = await freshModules()
    const { result } = renderHook(() => m.useWorkspaceLayout(true))
    result.current.setInspectorWidth(700)
    await waitFor(() => expect(result.current.inspectorWidth).toBe(700))

    await m.loadPreferences()
    await waitFor(() => expect(localStorage.getItem('ttmux.workspace')).toBeTruthy())
    expect(result.current.inspectorWidth).toBe(700)
  })
})

describe('右栏：第一次进来收着，拉开过就记住', () => {
  beforeEach(() => {
    localStorage.clear()
    window.innerWidth = VIEWPORT
    vi.stubGlobal('matchMedia', vi.fn((q: string) => ({
      matches: q.includes('min-width'),
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    })))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/api/preferences')) {
        return jsonResponse({ data: { _migrated: true, workspace: { inspectorCollapsed: false } } })
      }
      return jsonResponse({ data: {} })
    }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('没存过偏好 → 收着（新用户开门看见的是会话和终端，不是一列面板）', async () => {
    const m = await freshModules()
    const { result } = renderHook(() => m.useWorkspaceLayout(true, true))
    expect(result.current.inspectorCollapsed).toBe(true)
  })

  it('拉开之后写进偏好，本地镜像里也有 → 下次首帧就是开着的', async () => {
    const m = await freshModules()
    const { result } = renderHook(() => m.useWorkspaceLayout(true, true))
    result.current.toggleInspectorCollapsed()
    await waitFor(() => expect(result.current.inspectorCollapsed).toBe(false))
    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem('ttmux.workspace') || '{}')
      expect(saved.inspectorCollapsed).toBe(false)
    })

    const m2 = await freshModules()
    const { result: r2 } = renderHook(() => m2.useWorkspaceLayout(true, true))
    expect(r2.current.inspectorCollapsed).toBe(false)
  })

  it('服务端那份说开着，就按开着来（本机没记过时）', async () => {
    localStorage.clear()
    const m = await freshModules()
    const { result } = renderHook(() => m.useWorkspaceLayout(true, true))
    expect(result.current.inspectorCollapsed).toBe(true) // 首帧用默认
    await m.loadPreferences()
    await waitFor(() => expect(result.current.inspectorCollapsed).toBe(false))
  })
  it('explicitly opening a panel reveals a collapsed inspector without changing its width', async () => {
    localStorage.setItem('ttmux.workspace', JSON.stringify({ inspectorWidth: SAVED, inspectorCollapsed: true, navCollapsed: true }))
    const m = await freshModules()
    const { result } = renderHook(() => m.useWorkspaceLayout(true))
    const width = result.current.inspectorWidth
    expect(result.current.inspectorCollapsed).toBe(true)
    const { revealInspector } = await import('./inspector')
    act(() => revealInspector())
    expect(result.current.inspectorCollapsed).toBe(false)
    expect(result.current.inspectorWidth).toBe(width)
  })

})
