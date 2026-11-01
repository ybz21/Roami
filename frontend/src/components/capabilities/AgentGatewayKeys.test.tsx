// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import AgentGatewayKeys from './AgentGatewayKeys'
import LocalModelSources from './LocalModelSources'
import { gatewayAgentNames } from './gateway-agent'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
const keys = { revision: 'r1', keys: Object.keys(gatewayAgentNames).map(agentKind => ({ agentKind, suffix: 'fixture', keyId: 'legacy', connected: agentKind === 'opencode', disabled: false, configChanged: false, unavailable: false, configRevision: agentKind + '-r1', updatedMs: 0 })) }
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'GET') return { data: structuredClone(keys) }
    return { data: { ...structuredClone(keys), revision: 'r2' }, key: path.endsWith('/rotate') ? 'fixture-issued-once' : undefined }
  })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('uses the five default agents and opens their usage without creating another identity', async () => {
  const usage = vi.fn()
  render(<App><AgentGatewayKeys onUsage={usage} /></App>)
  const row = await screen.findByRole('article', { name: 'OpenCode' })
  expect(screen.getAllByRole('article')).toHaveLength(5)
  expect(screen.queryByRole('button', { name: /add|create/i })).toBeNull()
  fireEvent.click(within(row).getByRole('button', { name: 'hub.keys.usage' }))
  expect(usage).toHaveBeenCalledWith('opencode')
})
it('rotates only the selected agent with revisions and clears the one-time secret on close', async () => {
  render(<App><AgentGatewayKeys onUsage={() => {}} /></App>)
  const row = await screen.findByRole('article', { name: 'OpenCode' })
  fireEvent.click(within(row).getByRole('button', { name: 'hub.keys.rotate' }))
  const confirm = await screen.findByRole('tooltip')
  fireEvent.click(within(confirm).getByRole('button', { name: 'hub.keys.rotate' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/keys/opencode/rotate', { revision: 'r1', configRevision: 'opencode-r1' }))
  const secret = await screen.findByLabelText('hub.keys.secret') as HTMLTextAreaElement
  expect(secret.value).toBe('fixture-issued-once')
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'common.close' }))
  await waitFor(() => expect((screen.queryByLabelText('hub.keys.secret') as HTMLTextAreaElement | null)?.value || '').toBe(''))
})
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
