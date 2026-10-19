// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, expect, it, vi } from 'vitest'
import { EnvVarsSettings } from './env-vars'
import { TwoFactorSettings } from './security-settings'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it.each([EnvVarsSettings, TwoFactorSettings])('SET-03 keeps a failed read unknown and offers retry', async Component => {
  vi.mocked(api).mockRejectedValueOnce(new Error('HTTP 503')).mockResolvedValue(Component === EnvVarsSettings ? [] : { data: { totp: true } })
  render(<App><Component /></App>)
  await screen.findByRole('alert')
  expect(screen.queryByText('env.empty')).toBeNull()
  expect(screen.queryByRole('button', { name: 'twoFactor.enable' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'env.add' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  if (Component === TwoFactorSettings) await screen.findByText('twoFactor.on')
  else await screen.findByText('env.empty')
})
