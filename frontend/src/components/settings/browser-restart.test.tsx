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
    return { data: {} }
  })
  render(<BrowserSettings onRestartReady={run => { ready = run }} />)
  await waitFor(() => expect(ready).toBeTypeOf('function'))
  fireEvent.change(screen.getByDisplayValue('1920,1080'), { target: { value: '1280,720' } })
  void ready!()
  const save = onOk()
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/browser/config', expect.objectContaining({ windowSize: '1280,720' })))
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'POST')).toBe(false)
  const done = fail ? expect(save).rejects.toThrow('SAVE_FAILED') : expect(save).resolves.toBeUndefined()
  complete(); await done
  expect(vi.mocked(api).mock.calls.some(([, path]) => path === '/browser/relaunch')).toBe(!fail)
})
