// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import MagpiePluginImport from './MagpiePluginImport'
import MagpieSourceSettings from './MagpieSourceSettings'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => '/api' + path }))
const provider = { id: 'workbuddy', name: 'WorkBuddy', methods: [{ type: 'api', label: 'API Key' }], options: [], signedIn: false, models: [] }
beforeEach(() => { window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) })
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })
it.each([false, true])('uploads folder paths or a ZIP and creates the chosen provider (ZIP=%s)', async zip => {
  let sent: FormData | undefined
  vi.stubGlobal('fetch', vi.fn(async (_url, options) => { sent = options.body; return { ok: true, json: async () => ({ data: { id: 'package-id', name: 'WorkBuddy', version: '1' } }) } }))
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.endsWith('/packages') ? [] : path.endsWith('/inspect') ? [provider] : {} }))
  const imported = vi.fn(), page = render(<App><MagpiePluginImport revision="catalog-r1" onImported={imported} /></App>)
  const file = new File(['fixture'], zip ? 'plugin.zip' : 'package.json')
  if (!zip) Object.defineProperty(file, 'webkitRelativePath', { value: 'workbuddy/package.json' })
  fireEvent.change(page.container.querySelector(zip ? 'input[accept]' : 'input[webkitdirectory]')!, { target: { files: [file] } })
  fireEvent.click(await screen.findByRole('button', { name: 'hub.plugin.addSource' }))
  await waitFor(() => expect(imported).toHaveBeenCalledOnce())
  expect(sent!.get('paths')).toBe(zip ? '' : 'workbuddy/package.json')
  expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/plugins/sources', { packageId: 'package-id', providerId: 'workbuddy', revision: 'catalog-r1' })
})
it('keeps plugin credentials after a rejected sign-in without storing them in page drafts', async () => {
  vi.mocked(api).mockImplementation(async (method, path, body) => {
    if (method === 'GET') return { data: { provider, options: {}, desktopUnavailable: false } }
    if (body.action === 'prompt') return { data: { prompt: null } }
    throw { apiError: { code: 'MODEL_PLUGIN_FAILED' } }
  })
  render(<App><MagpieSourceSettings sourceId="source-id" onChanged={() => {}} /></App>)
  const input = await screen.findByLabelText('agent.models.apiKey') as HTMLInputElement
  fireEvent.change(input, { target: { value: 'fixture-not-a-real-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.plugin.signIn' }))
  await screen.findByText('hub.plugin.failed')
  expect(input.value).toBe('fixture-not-a-real-key')
})
it('shows the Doubao desktop requirement and prevents login on Linux', async () => {
  vi.mocked(api).mockResolvedValue({ data: { provider: { ...provider, id: 'doubao-work', methods: [{ type: 'oauth', label: 'Desktop' }] }, options: {}, desktopUnavailable: true } })
  render(<App><MagpieSourceSettings sourceId="doubao-id" onChanged={() => {}} /></App>)
  await screen.findByText('hub.plugin.desktopUnavailable')
  expect((screen.getByRole('button', { name: 'hub.plugin.signIn' }) as HTMLButtonElement).disabled).toBe(true)
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'POST')).toBe(false)
})
