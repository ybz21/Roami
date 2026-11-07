// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRecoverySettings } from './memory-settings'

const mocks = vi.hoisted(() => ({ api: vi.fn(), error: vi.fn() }))
vi.mock('../../api', () => ({ api: mocks.api }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: mocks.error } }) },
  Checkbox: ({ children, checked, disabled, onChange }: any) => <label><input type="checkbox" checked={checked} disabled={disabled} onChange={onChange} />{children}</label>,
  Button: ({ children, ...props }: any) => <a {...props}>{children}</a>,
  Tag: ({ children }: any) => <span>{children}</span>,
}))
afterEach(cleanup)
beforeEach(() => vi.clearAllMocks())

it('hydrates saved switches and persists changes without enabling host compression', async () => {
  mocks.api.mockImplementation((method: string, path: string) => Promise.resolve(method === 'PUT' ? {} : path === '/env' ? [{ key: 'ROAM_MEMORY_COMPACT', value: 'off' }] : { zram: false, zswap: false, swapFree: 0, swapTotal: 8e9 }))
  render(<MemoryRecoverySettings />)
  const compact = await screen.findByRole('checkbox', { name: 'set.mem.autoCompact' }) as HTMLInputElement
  expect(compact.checked).toBe(false)
  expect((screen.getByRole('checkbox', { name: 'set.mem.autoReclaim' }) as HTMLInputElement).checked).toBe(true)
  expect(screen.getByText('set.mem.compressionOff')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'set.mem.downloadSetup' }).getAttribute('href')).toBe('/memory/setup-script')
  fireEvent.click(compact)
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('PUT', '/env', { key: 'ROAM_MEMORY_COMPACT', value: 'on' }))
  await waitFor(() => expect(compact.checked).toBe(true))
})

it('shows recovery after a failed status read and actual compression metrics', async () => {
  mocks.api.mockRejectedValue(new Error('offline'))
  render(<MemoryRecoverySettings />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByRole('checkbox')).toBeNull()
  mocks.api.mockImplementation((_method: string, path: string) => Promise.resolve(path === '/env' ? [] : { zram: true, zswap: false, swapFree: 200, swapTotal: 500, original: 400, memory: 100, saved: 300 }))
  fireEvent.click(screen.getByRole('button', { name: 'inbox.retry' }))
  expect(await screen.findByText('set.mem.compressionStats')).toBeTruthy()
  expect(screen.queryByText('set.mem.downloadSetup')).toBeNull()
})
