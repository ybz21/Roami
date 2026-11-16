// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayModelDirectory from './GatewayModelDirectory'
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
beforeEach(() => { window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('lists advertised capabilities, preserves unknowns, filters and never configures a source', async () => {
 vi.mocked(api).mockResolvedValue({ data: { models: ['vendor/free', 'vendor/unknown'], details: [{ id: 'vendor/free', name: 'Free vision', tools: true, context: 131072, inputModalities: ['image'], inputPrice: 0, outputPrice: 0 }, { id: 'vendor/unknown' }] } })
 render(<App><GatewayModelDirectory catalog={{ revision: 'r1', baseUrl: '', drafts: [], uses: {}, models: [], sources: [{ id: 'a', name: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', protocol: 'openai-completions', authMode: 'bearer' }] }} onSource={vi.fn()} /></App>)
 fireEvent.click(screen.getByRole('tab', { name: 'gatewayWorkspace.kind.upstream' }))
 expect(await screen.findByText('Free vision')).toBeTruthy()
 expect(screen.getByText('131,072')).toBeTruthy()
 expect(screen.getByText('directory.unknownCapabilities')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('directory.search'), { target: { value: 'unknown' } })
 expect(screen.queryByText('Free vision')).toBeNull()
 expect(screen.getAllByText('vendor/unknown').length).toBeGreaterThan(0)
 await waitFor(() => expect(api).toHaveBeenCalledTimes(1))
 expect(vi.mocked(api).mock.calls[0][1]).toContain('/discover')
})

it('shows the public gateway ID separately from the upstream ID and retains source scope in details', async () => {
 vi.mocked(api).mockResolvedValue({ data: { models: ['vendor/model'], details: [{ id: 'vendor/model', context: 32000, tools: true }] } })
 const writeText = vi.fn().mockResolvedValue(undefined)
 Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
 const onSource = vi.fn()
 render(<App><GatewayModelDirectory catalog={{ revision: 'r2', baseUrl: '', drafts: [], uses: {}, models: [{ id: 'team-model', name: 'Team alias', protocol: 'openai-completions', strategy: 'fixed', candidates: [{ sourceId: 'a', model: 'vendor/model' }] }], sources: [{ id: 'a', name: 'Source A', baseUrl: 'https://example.test', protocol: 'openai-completions', authMode: 'bearer' }] }} onSource={onSource} /></App>)
 fireEvent.click(await screen.findByRole('button', { name: /Team alias/ }))
 const inspector = await screen.findByLabelText('gatewayWorkspace.modelDetails', { selector: 'aside' })
 expect(inspector.textContent).toContain('team-model')
 expect(inspector.textContent).toContain('vendor/model')
 expect(inspector.textContent).toContain('Source A')
 fireEvent.click(within(inspector).getByRole('button', { name: 'gatewayWorkspace.copyModel' }))
 await waitFor(() => expect(writeText).toHaveBeenCalledWith('team-model'))
 fireEvent.click(within(inspector).getByRole('button', { name: 'gatewayWorkspace.viewSource' }))
 expect(onSource).toHaveBeenCalledWith('a')
})
