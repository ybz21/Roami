// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { installRadixTestEvents } from '../ui/radix-test-events'
import { api } from '../../api'
import { clearAgentDataCache } from '../agent/agent-data-cache'
import GatewayModelDirectory from './GatewayModelDirectory'
import type { ModelCatalog } from './model-hub-api'
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
beforeEach(() => { installRadixTestEvents(); window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
afterEach(() => { cleanup(); clearAgentDataCache(); vi.clearAllMocks() })
const catalog: ModelCatalog = { revision: 'r1', baseUrl: '', drafts: [], uses: { 'team-model': ['roami', 'roami', 'codex'], pool: ['claude'] }, models: [{ id: 'team-model', name: 'Team alias', protocol: 'openai-completions', strategy: 'fixed', candidates: [{ sourceId: 'a', model: 'vendor/model' }] }, { id: 'pool', name: 'Team pool', aggregate: true, protocol: 'openai-completions', strategy: 'order', freeOnly: true, candidates: [{ sourceId: 'a', model: 'vendor/model' }] }], sources: [{ id: 'a', name: 'Source A', baseUrl: 'https://example.test', protocol: 'openai-completions', authMode: 'bearer' }] }
const row = (id: string, patch = {}) => ({ id, name: id, kind: 'single', configured: false, enabled: true, capabilities: {}, candidates: [{ sourceId: 'a', model: id }], ...patch })
it('defaults to configured routes with aggregates first and shows per-route users in gateway details', async () => {
 vi.mocked(api).mockResolvedValue({ data: { revision:'r1', models: [row('paid-upstream'), row('team-model', {configured:true,name:'Team alias'})] } })
 const writeText = vi.fn().mockResolvedValue(undefined), onSource=vi.fn()
 Object.defineProperty(navigator, 'clipboard', { configurable:true, value:{writeText} })
 render(<App><GatewayModelDirectory catalog={catalog} onSource={onSource} /></App>)
 await waitFor(() => expect(api).toHaveBeenCalled())
 expect(document.querySelector('.tt-directory-model-name strong')?.textContent).toBe('Team pool')
 expect(screen.queryByText('paid-upstream')).toBeNull()
 fireEvent.click(screen.getByRole('button', {name:/Team alias/}))
 const inspector=await screen.findByLabelText('gatewayWorkspace.modelDetails', {selector:'aside'})
 expect(inspector.textContent).toContain('vendor/model')
 expect(inspector.textContent).toContain('roami, codex')
 expect(inspector.textContent).not.toContain('claude')
 fireEvent.click(within(inspector).getByRole('button', {name:'gatewayWorkspace.copyModel'}))
 await waitFor(() => expect(writeText).toHaveBeenCalledWith('team-model'))
 fireEvent.click(within(inspector).getByRole('button', {name:'gatewayWorkspace.viewSource'}))
 expect(onSource).toHaveBeenCalledWith('a')
})
it('keeps paid upstream models out of the default directory and never infers free pricing from a source name', async () => {
 vi.mocked(api).mockResolvedValue({ data: { revision:'r1', models:[row('paid-claude',{name:'Claude paid',pricing:'metered',inputModalities:['text','image'],outputModalities:['text']})] } })
 render(<App><GatewayModelDirectory catalog={{...catalog,sources:[{...catalog.sources[0],name:'openrouter-free'}]}} onSource={vi.fn()} /></App>)
 expect(screen.queryByRole('tab')).toBeNull()
 fireEvent.keyDown(screen.getByRole('combobox',{name:'gatewayWorkspace.kind'}),{key:'ArrowDown'})
 fireEvent.keyDown(await screen.findByRole('option',{name:'gatewayWorkspace.kind.upstream'}),{key:'Enter'})
 expect(await screen.findByText('Claude paid')).toBeTruthy()
 expect(screen.getByText('gatewayOptions.price.metered')).toBeTruthy()
 expect(screen.queryByText('gatewayOptions.price.confirmed-free')).toBeNull()
 expect(screen.getByText(/directory.inputs.*directory.modality.text.*directory.modality.image/)).toBeTruthy()
 expect(vi.mocked(api).mock.calls[0][1]).toContain('/agent/model-gateway/models?all=true&refresh=true')
 expect(vi.mocked(api).mock.calls.some(([method])=>method!=='GET')).toBe(false)
 expect(screen.queryByRole('button', { name: 'directory.testModel' })).toBeNull()
})

it('tests the selected gateway route even when discovery fails and shows the final 503 and upstream 502', async () => {
 let complete: (payload: unknown) => void = () => {}
 vi.mocked(api).mockImplementation(async method => {
   if (method === 'GET') throw Object.assign(new Error('AGENT_RUNTIME_UNAVAILABLE'), { status: 503 })
   return new Promise(resolve => { complete = resolve })
 })
 render(<App><GatewayModelDirectory catalog={catalog} onSource={vi.fn()} /></App>)
 await screen.findByText('directory.loadFailed')
 const pool = screen.getByRole('region', { name: 'gatewayWorkspace.kind.pool' })
 const test = within(pool).getByRole('button', { name: 'directory.testModel' })
 expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'POST')).toHaveLength(0)
 fireEvent.click(test)
 fireEvent.click(test)
 expect(vi.mocked(api).mock.calls.filter(([method]) => method === 'POST')).toHaveLength(1)
 expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/monitor/check', { routeId: 'pool', rule: 'answer' }, expect.anything())
 expect(test.hasAttribute('disabled')).toBeTruthy()
 complete({ data: {
   success: false, status: 503, error: 'MODEL_ROUTE_NO_AVAILABLE_MEMBER', durationMs: 12, attempts: 2,
   sourceId: 'a', upstreamModel: 'vendor/model', upstreamStatus: 502,
 } })
 expect(await within(pool).findByText('gatewayTrace.exhausted · HTTP 503')).toBeTruthy()
 expect(within(pool).getByText('Source A · vendor/model · directory.testUpstreamStatus')).toBeTruthy()
 expect(test.hasAttribute('disabled')).toBe(false)
})

it('reports a partial refresh separately and shows the cooldown before any upstream call', async () => {
 vi.mocked(api).mockImplementation(async method => method === 'GET'
   ? { data: { revision: 'r1', models: [], refreshFailures: ['a'] } }
   : { data: { success: false, status: 503, error: 'MODEL_ROUTE_NO_AVAILABLE_MEMBER', durationMs: 0, attempts: 0, blocks: { cooldown: 2 } } })
 render(<App><GatewayModelDirectory catalog={catalog} onSource={vi.fn()} /></App>)
 await screen.findByText('directory.partialRefresh')
 const pool = screen.getByRole('region', { name: 'gatewayWorkspace.kind.pool' })
 fireEvent.click(within(pool).getByRole('button', { name: 'directory.testModel' }))
 expect(await within(pool).findByText('gatewayTrace.blockedBeforeSend · HTTP 503')).toBeTruthy()
 expect(within(pool).getByText('directory.testBlockedReason')).toBeTruthy()
})

it('shows a 503 from the test service and allows a successful retry', async () => {
 const probe = vi.fn()
   .mockRejectedValueOnce(Object.assign(new Error('AGENT_RUNTIME_UNAVAILABLE'), { status: 503 }))
   .mockResolvedValueOnce({ data: { success: true, status: 200, durationMs: 25, attempts: 1 } })
 vi.mocked(api).mockImplementation(async method => method === 'GET' ? { data: { revision: 'r1', models: [] } } : probe())
 render(<App><GatewayModelDirectory catalog={catalog} onSource={vi.fn()} /></App>)
 const pool = screen.getByRole('region', { name: 'gatewayWorkspace.kind.pool' })
 const test = within(pool).getByRole('button', { name: 'directory.testModel' })
 fireEvent.click(test)
 await within(pool).findByText('directory.testUnavailable · HTTP 503')
 fireEvent.click(test)
 await within(pool).findByText('directory.testPassed · HTTP 200')
 expect(probe).toHaveBeenCalledTimes(2)
})

it('labels an upstream 400 as a request rejection instead of failed failover', async () => {
 vi.mocked(api).mockImplementation(async method => method === 'GET'
   ? { data: { revision: 'r1', models: [] } }
   : { data: { success: false, status: 400, error: 'MODEL_HTTP_400', durationMs: 12, attempts: 1, upstreamStatus: 400 } })
 render(<App><GatewayModelDirectory catalog={catalog} onSource={vi.fn()} /></App>)
 const pool = screen.getByRole('region', { name: 'gatewayWorkspace.kind.pool' })
 fireEvent.click(within(pool).getByRole('button', { name: 'directory.testModel' }))
 await within(pool).findByText('gatewayTrace.upstreamRejected · HTTP 400')
 expect(within(pool).queryByText(/gatewayTrace.exhausted/)).toBeNull()
})
