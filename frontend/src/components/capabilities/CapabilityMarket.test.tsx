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

it('loads popular skills on entry and installs the reviewed bundle to all targets', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [{ ...item, installs: 12500 }], nextCursor: '' } }).mockResolvedValueOnce({ data: { previewId: 'pinned-preview', kind: 'skills', options: [{ label: 'workflow', entry }] } }).mockResolvedValueOnce({ data: {} })
  render(<CapabilityMarket />)
  expect(await screen.findByText('capabilities.market.popular')).toBeTruthy()
  await waitFor(() => expect(api).toHaveBeenCalledWith('GET', '/agent/capability-markets/skills-sh/search?query=', undefined, expect.anything()))
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.view' }))
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.install' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/capability-markets/install', { previewId: 'pinned-preview', option: 0, targets: ['local', 'claude', 'opencode', 'roami'] }))
  expect(await screen.findByText('capabilities.market.installed')).toBeTruthy()
})

it('keeps the previous results and query when a subsequent search fails', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [], nextCursor: '' } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockRejectedValueOnce(new Error('MARKET_UNAVAILABLE'))
  render(<CapabilityMarket />)
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
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

it('returns from search results to the popular list without another search term', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValue({ data: { items: [item], nextCursor: '' } })
  render(<CapabilityMarket />)
  await screen.findByRole('button', { name: 'workflow' })
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.market.query' }), { target: { value: 'workflow' } })
  expect(api).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.search' }))
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.backPopular' }))
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'capabilities.market.query' }) as HTMLInputElement).value).toBe(''))
  expect(api).toHaveBeenLastCalledWith('GET', '/agent/capability-markets/skills-sh/search?query=', undefined, expect.anything())
})

it('reloads popular skills after saving changes to the selected source', async () => {
  const changed = [{ ...sources[0], url: 'https://mirror.example.test' }]
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockResolvedValueOnce({ data: { sources: changed } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } })
  render(<CapabilityMarket />)
  await screen.findByRole('button', { name: 'workflow' })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.sources' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.market.sourceUrl 1' }), { target: { value: changed[0].url } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.saveChanges' }))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(4))
  expect(await screen.findByRole('button', { name: 'workflow' })).toBeTruthy()
})

it('keeps the selected install targets and pinned preview after installation fails', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockResolvedValueOnce({ data: { previewId: 'pinned-preview', kind: 'skills', options: [{ label: 'workflow', entry }] } }).mockRejectedValueOnce(new Error('SKILL_TARGET_EXISTS'))
  render(<CapabilityMarket />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.view' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'capabilities.market.target.claude' }))
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.install' }))
  await screen.findByRole('alert')
  expect((screen.getByRole('checkbox', { name: 'capabilities.market.target.claude' }) as HTMLInputElement).checked).toBe(false)
  expect(api).toHaveBeenLastCalledWith('POST', '/agent/capability-markets/install', { previewId: 'pinned-preview', option: 0, targets: ['local', 'opencode', 'roami'] })
  expect(screen.getByRole('button', { name: 'capabilities.market.install' }).hasAttribute('disabled')).toBe(false)
})

it('loads trending and hot JSON rankings and uses the correct install period', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockResolvedValueOnce({ data: { items: [{ ...item, installs: 100 }], nextCursor: '' } }).mockResolvedValueOnce({ data: { items: [{ ...item, installs: 5 }], nextCursor: '' } })
  render(<CapabilityMarket />)
  await screen.findByRole('button', { name: 'workflow' })
  fireEvent.click(screen.getByText('capabilities.market.ranking.trending'))
  await screen.findByText('capabilities.market.installs.trending')
  expect(api).toHaveBeenLastCalledWith('GET', '/agent/capability-markets/skills-sh/search?query=&view=trending', undefined, expect.anything())
  fireEvent.click(screen.getByText('capabilities.market.ranking.hot'))
  await screen.findByText('capabilities.market.installs.hot')
  expect(api).toHaveBeenLastCalledWith('GET', '/agent/capability-markets/skills-sh/search?query=&view=hot', undefined, expect.anything())
})

it('keeps the previous ranking and query draft when switching rankings fails', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [{ ...item, installs: 1000 }], nextCursor: '' } }).mockRejectedValueOnce(new Error('MARKET_UNAVAILABLE')).mockResolvedValueOnce({ data: { items: [{ ...item, installs: 5 }], nextCursor: '' } })
  render(<CapabilityMarket />)
  await screen.findByRole('button', { name: 'workflow' })
  const input = screen.getByRole('textbox', { name: 'capabilities.market.query' }) as HTMLInputElement
  fireEvent.change(input, { target: { value: 'draft' } })
  fireEvent.click(screen.getByText('capabilities.market.ranking.hot'))
  await screen.findByRole('alert')
  expect(input.value).toBe('draft')
  expect(screen.getByText('capabilities.market.installs.all-time')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByText('capabilities.market.installs.hot')
  expect(input.value).toBe('draft')
  expect(api).toHaveBeenLastCalledWith('GET', '/agent/capability-markets/skills-sh/search?query=&view=hot', undefined, expect.anything())
})

it('opens full skill details and a usable install action from a single preview request', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockResolvedValueOnce({ data: { previewId: 'pinned-preview', kind: 'skills', options: [{ label: 'workflow', entry }] } })
  render(<CapabilityMarket />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.view' }))
  expect(await screen.findByRole('heading', { name: 'Original instructions' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'capabilities.market.install' }).hasAttribute('disabled')).toBe(false)
  expect(api).toHaveBeenCalledTimes(3)
})

it('renders the skill purpose and examples before exposing the original bundle', async () => {
  const text = '---\nname: workflow\ndescription: >\n  Build polished pages.\n  Preview the result.\n---\n\n# Workflow\n\n## Examples\n\n**Before and after**\n\n[Read reference](references/example.md)\n\n![Result](assets/result.png)\n\n![Remote result](https://raw.githubusercontent.com/o/r/main/hero.png)\n\n<script>window.bad = true</script>'
  const rich = { ...entry, text, files: { 'references/example.md': btoa('# Reference example'), 'assets/result.png': 'iVBORw0KGgo=' } }
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockResolvedValueOnce({ data: { previewId: 'pinned-preview', kind: 'skills', options: [{ label: 'workflow', entry: rich, images: { 'https://raw.githubusercontent.com/o/r/main/hero.png': 'data:image/png;base64,iVBORw0KGgo=' } }] } })
  render(<CapabilityMarket />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.market.view' }))
  expect(await screen.findByText('Build polished pages. Preview the result.')).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Examples' })).toBeTruthy()
  expect(screen.queryByText(/name: workflow/)).toBeNull()
  expect(document.querySelector('.tt-skill-document script')).toBeNull()
  expect(screen.getByRole('img', { name: 'Result' }).getAttribute('src')).toBe('data:image/png;base64,iVBORw0KGgo=')
  expect(screen.getByRole('img', { name: 'Remote result' }).getAttribute('src')).toBe('data:image/png;base64,iVBORw0KGgo=')
  fireEvent.click(screen.getByRole('button', { name: 'Read reference' }))
  expect(await screen.findByLabelText('references/example.md')).toBeTruthy()
  expect(screen.getByText('# Reference example')).toBeTruthy()
  fireEvent.click(screen.getByText('capabilities.market.overview'))
  fireEvent.click(screen.getByText('capabilities.market.files'))
  expect(screen.getByText('# Reference example')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.backResults' }))
  expect(await screen.findByRole('button', { name: 'workflow' })).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(3)
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
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/capability-imports/mcp', { name: 'legacy', displayName: 'legacy', description: '', config: { transport: 'sse', url: 'https://example.test/sse', key_env: 'MCP_TOKEN' } }))
  expect((url as HTMLInputElement).value).toBe('https://example.test/sse')
})

it('edits an existing SSE connection without requiring a local command', async () => {
  vi.mocked(api).mockResolvedValue({ data: {} })
  render(<CapabilityEditor kind="mcp" entry={{ name: 'legacy', config: { transport: 'sse', url: 'https://example.test/sse' } }} onClose={() => {}} onSaved={() => {}} />)
  const save = screen.getByRole('button', { name: 'capabilities.saveChanges' })
  expect(save.hasAttribute('disabled')).toBe(false)
  fireEvent.click(save)
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/capability-imports/mcp/legacy', { name: 'legacy', displayName: 'legacy', description: '', config: { transport: 'sse', url: 'https://example.test/sse' } }))
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


it('opens an official skill URL directly and keeps the current results', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], total: 9902, nextCursor: '' } }).mockResolvedValueOnce({ data: { previewId: 'pinned-preview', kind: 'skills', options: [{ label: 'workflow', entry }] } })
  render(<CapabilityMarket />)
  await screen.findByRole('button', { name: 'workflow' })
  expect(screen.getByText('9,902')).toBeTruthy()
  const url = 'https://skills.sh/owner/repo/workflow'
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.market.query' }), { target: { value: url } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.search' }))
  expect(await screen.findByRole('heading', { name: 'Original instructions' })).toBeTruthy()
  expect(api).toHaveBeenLastCalledWith('POST', '/agent/capability-markets/preview', { source: 'skills-sh', id: item.id, version: '' }, expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.backResults' }))
  expect((screen.getByRole('textbox', { name: 'capabilities.market.query' }) as HTMLInputElement).value).toBe(url)
  expect(screen.getByText('9,902')).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(3)
})

it('shows only authoritative ranking counts and retains the successful tab on failure', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], total: 9902, nextCursor: '' } }).mockRejectedValueOnce(new Error('MARKET_UNAVAILABLE')).mockResolvedValueOnce({ data: { items: [item], total: 3349, nextCursor: '' } })
  render(<CapabilityMarket />)
  await screen.findByText('9,902')
  expect(screen.queryByText('1')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: 'capabilities.market.ranking.hot' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('tab', { name: /capabilities.market.ranking.all-time/ }).getAttribute('aria-selected')).toBe('true')
  fireEvent.click(screen.getByRole('tab', { name: 'capabilities.market.ranking.hot' }))
  await screen.findByText('3,349')
  expect(screen.getByText('9,902')).toBeTruthy()
  expect(screen.getByRole('tab', { name: /capabilities.market.ranking.hot/ }).getAttribute('aria-selected')).toBe('true')
})

it('retries the initial ranking without submitting a newly typed draft', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockRejectedValueOnce(Object.assign(new Error('The runtime is offline'), { apiError: { code: 'AGENT_RUNTIME_UNAVAILABLE' }, status: 503 })).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } })
  render(<CapabilityMarket />)
  await screen.findByRole('alert')
  expect(screen.getByText('AGENT_RUNTIME_UNAVAILABLE · HTTP 503')).toBeTruthy()
  const input = screen.getByRole('textbox', { name: 'capabilities.market.query' }) as HTMLInputElement
  fireEvent.change(input, { target: { value: 'unfinished draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByRole('button', { name: 'workflow' })
  expect(api).toHaveBeenLastCalledWith('GET', '/agent/capability-markets/skills-sh/search?query=', undefined, expect.anything())
  expect(input.value).toBe('unfinished draft')
  expect(screen.queryByRole('alert')).toBeNull()
})

it('retries the failed preview instead of searching and restores the original opener', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } }).mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce({ data: { previewId: 'pinned-preview', kind: 'skills', options: [{ label: 'workflow', entry }] } })
  render(<CapabilityMarket />)
  const opener = await screen.findByRole('button', { name: 'capabilities.market.view' })
  opener.focus()
  fireEvent.click(opener)
  await screen.findByText('capabilities.market.error.network')
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByRole('heading', { name: 'Original instructions' })
  expect(api).toHaveBeenLastCalledWith('POST', '/agent/capability-markets/preview', { source: 'skills-sh', id: item.id, version: '' }, expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.backResults' }))
  await waitFor(() => expect(document.activeElement).toBe(opener))
  expect(api).toHaveBeenCalledTimes(4)
})

it('retries the failed page with its original query and cursor without replacing prior results', async () => {
  const second = { ...item, id: 'owner/repo/second', name: 'second' }
  vi.mocked(api).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [], nextCursor: '' } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: 'page-2' } }).mockRejectedValueOnce(new Error('HTTP 502')).mockResolvedValueOnce({ data: { items: [item, second], nextCursor: '' } })
  render(<CapabilityMarket />)
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  const input = screen.getByRole('textbox', { name: 'capabilities.market.query' }) as HTMLInputElement
  fireEvent.change(input, { target: { value: 'workflow' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.search' }))
  await screen.findByRole('button', { name: 'workflow' })
  fireEvent.change(input, { target: { value: 'next draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.market.more' }))
  await screen.findByText('capabilities.market.error.loadFailed')
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByRole('button', { name: 'second' })
  expect(api).toHaveBeenLastCalledWith('GET', '/agent/capability-markets/skills-sh/search?query=workflow&cursor=page-2', undefined, expect.anything())
  expect(screen.getAllByRole('button', { name: 'workflow' })).toHaveLength(1)
  expect(input.value).toBe('next draft')
  const heading = screen.getByText('capabilities.market.results')
  expect(heading.previousElementSibling).toBe(screen.getByRole('button', { name: 'capabilities.market.backPopular' }))
})

it('reloads sources before loading the ranking when source discovery fails', async () => {
  vi.mocked(api).mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce({ data: { sources } }).mockResolvedValueOnce({ data: { items: [item], nextCursor: '' } })
  render(<CapabilityMarket />)
  await screen.findByText('capabilities.market.error.network')
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByRole('button', { name: 'workflow' })
  expect(vi.mocked(api).mock.calls.map(call => call[1])).toEqual(['/agent/capability-markets', '/agent/capability-markets', '/agent/capability-markets/skills-sh/search?query='])
})
