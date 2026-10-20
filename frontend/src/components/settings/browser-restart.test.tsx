// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, expect, it, vi } from 'vitest'
import { BrowserSettings } from './browser-settings'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
const t = (key: string) => key
vi.mock('../../i18n', () => ({ useI18n: () => ({ t }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks() })
it.each([false, true])('SET-06 awaits the latest save and prevents restart on failure (%s)', async fail => {
  let onOk: () => Promise<void> = async () => {}
  let ready: (() => Promise<void>) | null = null
  vi.spyOn(App, 'useApp').mockReturnValue({ message: { error: vi.fn(), success: vi.fn() }, modal: { confirm: (options: any) => { onOk = options.onOk } } } as any)
  let complete!: () => void
  const delayed = new Promise<void>(resolve => { complete = resolve })
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'GET') return { data: {} }
    if (method === 'PUT') { await delayed; if (fail) throw new Error('SAVE_FAILED') }
    return { data: { ok: true } }
  })
  render(<BrowserSettings onRestartReady={run => { ready = run }} />)
  await waitFor(() => expect(ready).toBeTypeOf('function'))
  fireEvent.change(screen.getByDisplayValue('1920,1080'), { target: { value: '1280,720' } })
  const restart = ready!()
  const restartDone = fail ? expect(restart).rejects.toThrow('SAVE_FAILED') : expect(restart).resolves.toBeUndefined()
  const save = onOk()
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/browser/config', expect.objectContaining({ windowSize: '1280,720' })))
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'POST')).toBe(false)
  const done = fail ? expect(save).rejects.toThrow('SAVE_FAILED') : expect(save).resolves.toBeUndefined()
  complete(); await done; await restartDone
  expect(vi.mocked(api).mock.calls.some(([, path]) => path === '/browser/relaunch')).toBe(!fail)
})
it.each([false, true])('restart failure settles the page action and re-enables inputs (%s)', async rejects => {
  let onOk!: () => Promise<void>
  let ready: (() => Promise<void>) | null = null
  const success = vi.fn()
  vi.spyOn(App, 'useApp').mockReturnValue({ message: { error: vi.fn(), success }, modal: { confirm: (options: any) => { onOk = options.onOk } } } as any)
  vi.mocked(api).mockImplementation(async (method) => {
    if (method === 'POST') {
      if (rejects) throw new Error('RESTART_FAILED')
      return { data: { ok: false, attached: true } }
    }
    return { data: {} }
  })
  render(<BrowserSettings onRestartReady={run => { ready = run }} />)
  await waitFor(() => expect(ready).toBeTypeOf('function'))
  const result = ready!()
  const outer = expect(result).rejects.toThrow(rejects ? 'RESTART_FAILED' : 'settings.browserRestartFailed')
  await expect(onOk()).rejects.toThrow()
  await outer
  expect(success).not.toHaveBeenCalled()
  await waitFor(() => expect((screen.getByDisplayValue('1920,1080') as HTMLInputElement).disabled).toBe(false))
})
it('recovery switch is saved immediately without a pending restart', async () => {
  vi.spyOn(App, 'useApp').mockReturnValue({ message: { error: vi.fn() }, modal: {} } as any)
  vi.mocked(api).mockResolvedValue({ data: { autoRecover: true } })
  render(<BrowserSettings />)
  const toggle = await screen.findByRole('switch', { name: 'settings.browserAutoRecover' })
  fireEvent.click(toggle)
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/browser/config', expect.objectContaining({ autoRecover: false })))
  expect(screen.queryByText('settings.browserPendingRestart')).toBeNull()
})
