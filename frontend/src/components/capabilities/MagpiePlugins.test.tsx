// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { clearAgentDataCache } from '../agent/agent-data-cache'
import MagpiePluginImport from './MagpiePluginImport'
import MagpieSourceSettings from './MagpieSourceSettings'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => '/api' + path }))
const provider = { id: 'workbuddy', name: 'WorkBuddy', methods: [{ type: 'api', label: 'API Key' }], options: [], signedIn: false, models: [] }
const communityPath = '/agent/model-gateway/plugins/community'
beforeEach(() => { window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) })
afterEach(() => { cleanup(); clearAgentDataCache(); vi.clearAllMocks(); vi.unstubAllGlobals() })
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

it('renders account capabilities from the loaded plugin and refreshes allowance after a manual check-in', async () => {
  let claimed = false
  vi.mocked(api).mockImplementation(async (_method, path) => {
    if (path.endsWith('/info')) return { data: { provider: { ...provider, id: 'another-provider', signedIn: true, usage: true, checkin: true }, options: {} } }
    if (path.endsWith('/usage')) return { data: { balance: claimed ? '35 credits' : '30 credits', windows: [] } }
    claimed = true
    return { data: { outcome: 'claimed', credit: 5, streak: 2 } }
  })
  render(<App><MagpieSourceSettings sourceId="account-id" onChanged={() => {}} /></App>)
  await screen.findByText('30 credits')
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'POST')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'hub.plugin.checkInNow' }))
  await screen.findByText('35 credits')
  expect(screen.getByText('hub.plugin.checkIn.claimed')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'hub.plugin.checkIn.done' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/plugins/sources/account-id/check-in', {}, expect.anything())
})

it('omits check-in when the signed-in provider only declares allowance', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.endsWith('/info')
    ? { provider: { ...provider, id: 'workbuddy-ai', signedIn: true, usage: true, checkin: false }, options: {} }
    : { balance: '30 credits' } }))
  render(<App><MagpieSourceSettings sourceId="account-id" onChanged={() => {}} /></App>)
  await screen.findByText('30 credits')
  expect(screen.queryByRole('button', { name: 'hub.plugin.checkInNow' })).toBeNull()
})

it('lists detected capabilities before sign-in and loads vendor calls only when expanded', async () => {
  const capabilities = { ...provider, id: 'history-provider', usage: false, checkin: false, calls: true, renews: true }
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.endsWith('/info')
    ? { provider: { ...capabilities, signedIn: path.includes('/signed/') }, options: {} }
    : [{ t: Date.UTC(2026, 10, 21), model: 'Vendor model', in: 20, out: 4, cost: 0 }] }))
  const page = render(<App><MagpieSourceSettings sourceId="unsigned" onChanged={() => {}} /></App>)
  expect(await screen.findByText('hub.plugin.callHistory · hub.plugin.renewsCredentials')).toBeTruthy()
  expect(vi.mocked(api).mock.calls.some(([, path]) => path.endsWith('/calls'))).toBe(false)
  page.rerender(<App><MagpieSourceSettings key="signed" sourceId="signed" onChanged={() => {}} /></App>)
  const summary = await screen.findByText('hub.plugin.callHistory')
  expect(vi.mocked(api).mock.calls.some(([, path]) => path.endsWith('/calls'))).toBe(false)
  const details = summary.closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  expect(await screen.findByText('Vendor model')).toBeTruthy()
  expect(screen.getByText('$0.00')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'hub.plugin.checkInNow' })).toBeNull()
})

it('discovers every plugin in an imported collection and adds from the matching package', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ data: { packages: [{ id: 'first', name: 'First plugin' }, { id: 'second', name: 'Second plugin' }], skipped: ['repo/broken/package.json'] } }) })))
  vi.mocked(api).mockImplementation(async (_method, path, body) => ({ data: path.endsWith('/packages') ? [] : path.endsWith('/inspect') ? [{ ...provider, ...(body.packageId === 'first' ? { name: 'First cloud', usage: true, checkin: true } : { name: 'Second cloud', calls: true }) }] : {} }))
  const imported = vi.fn(), page = render(<App><MagpiePluginImport revision="r1" onImported={imported} /></App>)
  fireEvent.change(page.container.querySelector('input[accept]')!, { target: { files: [new File(['zip'], 'repository.zip')] } })
  await screen.findByText('First cloud')
  await screen.findByText('Second cloud')
  expect(screen.getByText('hub.plugin.accountQuota · hub.plugin.checkIn')).toBeTruthy()
  expect(screen.getByText('hub.plugin.callHistory')).toBeTruthy()
  expect(screen.getByText('repo/broken/package.json')).toBeTruthy()
  const buttons = screen.getAllByRole('button', { name: 'hub.plugin.addSource' })
  fireEvent.click(buttons[1])
  await waitFor(() => expect(imported).toHaveBeenCalledOnce())
  expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/plugins/sources', { packageId: 'second', providerId: provider.id, revision: 'r1' })
})

it('keeps compatible providers visible when another imported plugin cannot load', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ data: { packages: [{ id: 'broken', name: 'Broken plugin' }, { id: 'valid', name: 'Valid plugin' }] } }) })))
  vi.mocked(api).mockImplementation(async (_method, path, body) => {
    if (path.endsWith('/packages') || path.startsWith(communityPath + '?')) return { data: [] }
    if (body.packageId === 'broken') throw { apiError: { code: 'MODEL_PLUGIN_FAILED' } }
    return { data: [{ ...provider, name: 'Available cloud' }] }
  })
  const page = render(<App><MagpiePluginImport revision="r1" onImported={() => {}} /></App>)
  fireEvent.change(page.container.querySelector('input[accept]')!, { target: { files: [new File(['zip'], 'repository.zip')] } })
  await screen.findByText('Available cloud')
  expect(screen.getByRole('alert').textContent).toContain('hub.plugin.failed')
})

it('lists registry plugins and downloads only the one chosen', async () => {
  const pkg = { id: 'release-id', name: '@magpie-community/opencode-workbuddy-auth', version: '0.2.37' }
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (path.startsWith(communityPath + '?')) return { data: [
      { package: pkg.name, name: 'WorkBuddy', providers: ['workbuddy'], version: pkg.version, summary: { zh: '接入 WorkBuddy', en: 'Connect WorkBuddy' } },
      { package: '@magpie-community/other', name: 'Other', providers: ['other'], version: '1.0.0' },
    ] }
    if (path === communityPath && method === 'POST') return { data: pkg }
    if (path.endsWith('/inspect')) return { data: [provider] }
    return { data: [] }
  })
  render(<App><MagpiePluginImport revision="r1" onImported={vi.fn()} /></App>)
  await screen.findByText('WorkBuddy')
  expect(screen.getByText('Connect WorkBuddy')).toBeTruthy()
  expect(screen.getByText('Other')).toBeTruthy()
  fireEvent.change(screen.getByRole('textbox', { name: 'hub.plugin.communitySearch' }), { target: { value: 'work' } })
  expect(screen.queryByText('Other')).toBeNull()
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'POST')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'hub.plugin.download' }))
  await screen.findByRole('button', { name: 'hub.plugin.addSource' })
  expect(api).toHaveBeenCalledWith('POST', communityPath, { channel: 'github', package: pkg.name, version: pkg.version })
  expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/plugins/inspect', { packageId: pkg.id }, expect.anything())
})

it('filters repository metadata, dependencies and environment files before a folder upload', async () => {
  let sent: FormData | undefined
  vi.stubGlobal('fetch', vi.fn(async (_url, options) => { sent = options.body; return { ok: true, json: async () => ({ data: { id: 'package', name: 'Plugin' } }) } }))
  vi.mocked(api).mockImplementation(async (_method, path) => ({ data: path.endsWith('/inspect') ? [provider] : [] }))
  const page = render(<App><MagpiePluginImport revision="r1" onImported={() => {}} /></App>)
  const files = ['repo/packages/plugin/package.json', 'repo/.git/config', 'repo/node_modules/pkg/index.js', 'repo/packages/plugin/.env.local'].map(path => { const file = new File(['content'], path.split('/').pop()!); Object.defineProperty(file, 'webkitRelativePath', { value: path }); return file })
  fireEvent.change(page.container.querySelector('input[webkitdirectory]')!, { target: { files } })
  await waitFor(() => expect(sent).toBeTruthy())
  expect(sent!.getAll('paths')).toEqual(['repo/packages/plugin/package.json'])
})
