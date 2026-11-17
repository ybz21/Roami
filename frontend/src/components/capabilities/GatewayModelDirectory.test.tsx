// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { clearAgentDataCache } from '../agent/agent-data-cache'
import GatewayModelDirectory from './GatewayModelDirectory'
import type { ModelCatalog } from './model-hub-api'
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
beforeEach(() => { window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
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
 fireEvent.click(screen.getByRole('tab',{name:'gatewayWorkspace.kind.upstream'}))
 expect(await screen.findByText('Claude paid')).toBeTruthy()
 expect(screen.getByText('gatewayOptions.price.metered')).toBeTruthy()
 expect(screen.queryByText('gatewayOptions.price.confirmed-free')).toBeNull()
 expect(screen.getByText(/directory.inputs.*directory.modality.text.*directory.modality.image/)).toBeTruthy()
 expect(vi.mocked(api).mock.calls[0][1]).toContain('/agent/model-gateway/models?all=true&refresh=true')
 expect(vi.mocked(api).mock.calls.some(([method])=>method!=='GET')).toBe(false)
})
