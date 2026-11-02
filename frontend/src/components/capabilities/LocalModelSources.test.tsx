// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import LocalModelSources from './LocalModelSources'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('keeps local source credentials on the server and imports only after confirmation', async () => {
  const imported = vi.fn()
  vi.mocked(api).mockImplementation(async () => ({ data: { revision: 'catalog-r1', sources: [{ id: 'native1', revision: 'native-r1', agentKind: 'opencode', name: 'Work', baseUrl: 'https://fixture.example/v1', hasKey: true }, { id: 'native2', revision: 'r2', agentKind: 'claude', name: 'Dynamic', baseUrl: 'https://dynamic.example', unavailable: true }] } }))
  render(<App><LocalModelSources onImported={imported} /></App>)
  const row = await screen.findByRole('article', { name: 'Work' })
  expect(api).toHaveBeenCalledTimes(1)
  expect((within(await screen.findByRole('article', { name: 'Dynamic' })).getByRole('button') as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(within(row).getByRole('button', { name: 'hub.local.import' }))
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'hub.local.import' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/catalog/local-sources', { id: 'native1', revision: 'native-r1', catalogRevision: 'catalog-r1' }))
  expect(imported).toHaveBeenCalledTimes(1)
})
