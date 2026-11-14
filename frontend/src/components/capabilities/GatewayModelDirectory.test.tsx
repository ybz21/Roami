// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayModelDirectory from './GatewayModelDirectory'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
beforeEach(() => { window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('lists advertised capabilities, preserves unknowns, filters and never configures a source', async () => {
 vi.mocked(api).mockResolvedValue({ data: { models: ['vendor/free', 'vendor/unknown'], details: [{ id: 'vendor/free', name: 'Free vision', tools: true, context: 131072, inputModalities: ['image'], inputPrice: 0, outputPrice: 0 }, { id: 'vendor/unknown' }] } })
 render(<GatewayModelDirectory catalog={{ revision: 'r1', baseUrl: '', drafts: [], uses: {}, models: [], sources: [{ id: 'a', name: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', protocol: 'openai-completions', authMode: 'bearer' }] }} onSource={vi.fn()} />)
 expect(await screen.findByText('Free vision')).toBeTruthy()
 expect(screen.getByText('131,072')).toBeTruthy()
 expect(screen.getByText('directory.unknownCapabilities')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('directory.search'), { target: { value: 'unknown' } })
 expect(screen.queryByText('Free vision')).toBeNull()
 expect(screen.getAllByText('vendor/unknown').length).toBeGreaterThan(0)
 await waitFor(() => expect(api).toHaveBeenCalledTimes(1))
 expect(vi.mocked(api).mock.calls[0][1]).toContain('/discover')
})
