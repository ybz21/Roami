// @vitest-environment jsdom
// 观感项（主题 / 语言）本地优先的回归用例。
//
// 多机之后这条才有分量：偏好存在服务端，切到另一台机器读的是那台的值，
// 于是界面当着面换一副样子。这里钉死的是——**本地存过就以本地为准**，
// 服务端那份只在这台浏览器还没表过态时作数。
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

beforeEach(() => { vi.useFakeTimers(); getMock.mockReset(); getMock.mockResolvedValue({ data: {} }); localStorage.clear() })
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers() })

const getMock = vi.fn()
vi.mock('./api', () => ({
  api: (method: string, path: string, body?: unknown) => getMock(method, path, body),
}))

async function freshModule() {
  vi.resetModules()
  return await import('./preferences')
}

describe('观感项本地优先', () => {
  beforeEach(() => {
    localStorage.clear()
    getMock.mockReset()
    getMock.mockResolvedValue({ data: {} })
  })

  it('本地存过主题时，服务端的值不覆盖它', async () => {
    localStorage.setItem('ttmux.look', JSON.stringify({ theme: 'light', locale: 'en-US' }))
    getMock.mockResolvedValue({ data: { theme: 'dark', locale: 'zh-CN', claudeCommand: 'cc' } })
    const prefs = await freshModule()
    await prefs.loadPreferences()
    expect(prefs.getPreferences().theme).toBe('light')
    expect(prefs.getPreferences().locale).toBe('en-US')
    // 非观感项仍以服务端为准：那是机器的事实，不是口味
    expect(prefs.getPreferences().claudeCommand).toBe('cc')
  })

  it('本地没表过态时，跟随服务端', async () => {
    getMock.mockResolvedValue({ data: { theme: 'light', locale: 'en-US' } })
    const prefs = await freshModule()
    await prefs.loadPreferences()
    expect(prefs.getPreferences().theme).toBe('light')
    expect(prefs.getPreferences().locale).toBe('en-US')
  })

  it('改主题会写进本地镜像，下次首帧就是对的', async () => {
    const prefs = await freshModule()
    prefs.savePreferences({ theme: 'light' })
    expect(JSON.parse(localStorage.getItem('ttmux.look') || '{}').theme).toBe('light')

    // 换一次模块实例＝模拟刷新：首帧（还没拉到服务端）就该读出 light
    const again = await freshModule()
    expect(again.getPreferences().theme).toBe('light')
  })

  it('改别的偏好不动观感镜像', async () => {
    const prefs = await freshModule()
    prefs.savePreferences({ claudeCommand: 'cc' })
    expect(localStorage.getItem('ttmux.look')).toBeNull()
  })
})

it('SET-01 reports failure, retains the draft, and retries with a real receipt', async () => {
  const prefs = await freshModule()
  getMock.mockRejectedValueOnce(new Error('HTTP 500')).mockResolvedValue({ data: 'ok' })
  const saved = prefs.savePreferences({ quickCommands: ['echo test'] })
  expect(await prefs.flushPreferences()).toBe(false)
  expect(await saved).toBe(false)
  expect(prefs.getPreferences().quickCommands).toEqual(['echo test'])
  expect(await prefs.flushPreferences()).toBe(true)
  expect(getMock).toHaveBeenLastCalledWith('PUT', '/preferences', expect.objectContaining({ quickCommands: ['echo test'] }))
})
it('SET-01 serializes writes so an older request cannot replace the latest draft', async () => {
  const prefs = await freshModule()
  let finish!: () => void
  getMock.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve })).mockResolvedValue({})
  const first = prefs.savePreferences({ quickCommands: ['first'] })
  const firstWrite = prefs.flushPreferences()
  await Promise.resolve()
  const second = prefs.savePreferences({ quickCommands: ['second'] })
  const secondWrite = prefs.flushPreferences()
  expect(getMock).toHaveBeenCalledTimes(1)
  finish()
  await Promise.all([first, second, firstWrite, secondWrite])
  expect(getMock).toHaveBeenLastCalledWith('PUT', '/preferences', expect.objectContaining({ quickCommands: ['second'] }))
})
