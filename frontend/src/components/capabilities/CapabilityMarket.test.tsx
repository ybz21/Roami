// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { api } from '../../api'
import CapabilityMarket from './CapabilityMarket'
import CapabilityEditor from './CapabilityEditor'
import MarketSources from './MarketSources'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../i18n', () => { const t = (key: string) => key; return { useI18n: () => ({ t, locale: 'en-US' }) } })
beforeAll(() => {
  const style = window.getComputedStyle
  window.getComputedStyle = element => style(element)
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.mocked(api).mockReset() })
const sources = [{ id: 'skills-sh', name: 'skills.sh', provider: 'skills_sh' as const, url: 'https://skills.sh', enabled: true }]
const item = { id: 'owner/repo/workflow', name: 'workflow', description: 'Example', version: '', url: 'https://skills.sh/owner/repo/workflow' }
const entry = { name: 'workflow', text: '# Original instructions', files: { 'scripts/check.py': 'cHJpbnQoMSk=' }, origin: { source: 'skills-sh', id: item.id, version: 'abc123', url: 'https://github.com/owner/repo/tree/abc123' } }

it('searches only on submit and reviews a bundle before importing it', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockResolvedValueOnce({ data: { kind: 'skills', options: [{ label: 'workflow', entry }] } }).mockResolvedValueOnce({ data: {} })
  render(<CapabilityMarket />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'capabilities.market.sources' }).hasAttribute('disabled')).toBe(false))
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.market.query' }), { target: { value: 'workflow' } })
  expect(api).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.search' }))
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.view' }))
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.reviewImport' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.instructions' }), { target: { value: '# Reviewed instructions' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.createAction.skills' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/capability-imports/skills', { ...entry, description: '', text: '# Reviewed instructions' }))
  expect(await screen.findByText('capabilities.market.imported')).toBeTruthy()
})

it('keeps the previous results and query when a subsequent search fails', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockRejectedValueOnce(new Error('MARKET_UNAVAILABLE'))
  render(<CapabilityMarket />)
  await waitFor(() => expect(api).toHaveBeenCalledTimes(1))
  const input = screen.getByRole('textbox', { name: 'capabilities.market.query' })
  fireEvent.change(input, { target: { value: 'workflow' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.search' }))
  await screen.findByRole('button', { name: 'workflow' })
  fireEvent.change(input, { target: { value: 'new query' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.search' }))
  await screen.findByRole('alert')
  expect((input as HTMLInputElement).value).toBe('new query')
  expect(screen.getByRole('button', { name: 'workflow' })).toBeTruthy()
})

it('preserves edited sources when persistence fails', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('MARKET_UNAVAILABLE'))
  const saved = vi.fn()
  render(<MarketSources sources={sources} onClose={() => {}} onSaved={saved} />)
  const input = screen.getByRole('textbox', { name: 'capabilities.market.sourceUrl 1' })
  fireEvent.change(input, { target: { value: 'https://mirror.example.test' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.saveChanges' }))
  await screen.findByRole('alert')
  expect((input as HTMLInputElement).value).toBe('https://mirror.example.test')
  expect(saved).not.toHaveBeenCalled()
})

it('imports an SSE type alias into a remote URL form and preserves user edits after failure', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('MCP_UNAVAILABLE'))
  render(<CapabilityEditor kind="mcp" importing onClose={() => {}} onSaved={() => {}} />)
  fireEvent.click(screen.getByText('capabilities.pasteInstead'))
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.importContent' }), { target: { value: JSON.stringify({ name: 'legacy', config: { type: 'sse', url: 'https://example.test/sse', key_env: 'MCP_TOKEN' } }) } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.reviewImport' }))
  const url = await screen.findByRole('textbox', { name: 'capabilities.url' })
  expect((url as HTMLInputElement).value).toBe('https://example.test/sse')
  expect(screen.queryByRole('textbox', { name: 'capabilities.command' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.confirmImport' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/capability-imports/mcp', { name: 'legacy', config: { transport: 'sse', url: 'https://example.test/sse', key_env: 'MCP_TOKEN' } }))
  expect((url as HTMLInputElement).value).toBe('https://example.test/sse')
})

it('edits an existing SSE connection without requiring a local command', async () => {
  vi.mocked(api).mockResolvedValue({ data: {} })
  render(<CapabilityEditor kind="mcp" entry={{ name: 'legacy', config: { transport: 'sse', url: 'https://example.test/sse' } }} onClose={() => {}} onSaved={() => {}} />)
  const save = screen.getByRole('button', { name: 'capabilities.saveChanges' })
  expect(save.hasAttribute('disabled')).toBe(false)
  fireEvent.click(save)
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/capability-imports/mcp/legacy', { name: 'legacy', config: { transport: 'sse', url: 'https://example.test/sse' } }))
})

it('rejects conflicting MCP transport aliases before showing an editable configuration', async () => {
  render(<CapabilityEditor kind="mcp" importing onClose={() => {}} onSaved={() => {}} />)
  fireEvent.click(screen.getByText('capabilities.pasteInstead'))
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.importContent' }), { target: { value: JSON.stringify({ name: 'legacy', config: { type: 'sse', transport: 'streamable_http', url: 'https://example.test/sse' } }) } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.reviewImport' }))
  await screen.findByRole('alert')
  expect(screen.queryByRole('textbox', { name: 'capabilities.url' })).toBeNull()
  expect(api).not.toHaveBeenCalled()
})
