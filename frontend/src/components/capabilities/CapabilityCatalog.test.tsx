// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { CapabilityCatalog } from './CapabilityCatalog'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../i18n', () => { const t = (key: string) => key; return { useI18n: () => ({ t, locale: 'en-US' }) } })
beforeAll(() => {
  const style = window.getComputedStyle
  window.getComputedStyle = element => style(element)
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.mocked(api).mockReset() })
const skill = { name: 'external-flow', text: '# Workflow instructions', version: 'abc123', source: 'managed', enabled: true, mutable: true }
const catalog = { skills: [skill], tools: [], cli: [], mcp: [], managed: { skills: { 'external-flow': { name: 'external-flow', text: skill.text } }, cli: {}, mcp: {} } }
it('persists a skill switch and keeps the saved state after a failure', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: catalog }).mockResolvedValueOnce({ data: { ...catalog, skills: [{ ...skill, enabled: false }] } }).mockRejectedValueOnce(new Error('offline'))
  render(<CapabilityCatalog kind="skills" />)
  const toggle = await screen.findByRole('switch')
  fireEvent.click(toggle)
  await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
  expect(api).toHaveBeenCalledWith('PUT', '/agent/capability-settings', { kind: 'skills', name: skill.name, enabled: false })
  fireEvent.click(toggle)
  await screen.findByRole('alert')
  expect(toggle.getAttribute('aria-checked')).toBe('false')
})
it('retries loading a failed catalog', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: catalog })
  render(<CapabilityCatalog kind="skills" />)
  fireEvent.click(await screen.findByRole('button', { name: 'agent.retry' }))
  expect(await screen.findByRole('switch')).toBeTruthy()
})
it('creates a skill and updates the visible catalog', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { ...catalog, skills: [] } }).mockResolvedValueOnce({ data: catalog })
  render(<CapabilityCatalog kind="skills" />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.createAction.skills' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.name' }), { target: { value: 'external-flow' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.instructions' }), { target: { value: skill.text } })
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'capabilities.createAction.skills' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/capability-imports/skills', { name: 'external-flow', description: '', text: skill.text }))
  expect(await screen.findByText('external-flow')).toBeTruthy()
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})
it('lets users review and edit pasted content and keeps it after a duplicate-name failure', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: catalog }).mockRejectedValueOnce(new Error('CAPABILITY_ALREADY_EXISTS'))
  render(<CapabilityCatalog kind="skills" />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.uploadFile' }))
  fireEvent.click(screen.getByText('capabilities.pasteInstead'))
  const content = '---\nname: external-flow\ndescription: Imported workflow\n---\nDo the work'
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.importContent' }), { target: { value: content } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.reviewImport' }))
  const instructions = await screen.findByRole('textbox', { name: 'capabilities.instructions' }) as HTMLTextAreaElement
  expect(instructions.value).toBe('Do the work')
  fireEvent.change(instructions, { target: { value: 'Reviewed instructions' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.confirmImport' }))
  await screen.findByRole('alert')
  expect(instructions.value).toBe('Reviewed instructions')
  expect(screen.getByRole('dialog')).toBeTruthy()
  expect(api).toHaveBeenCalledWith('POST', '/agent/capability-imports/skills', { name: 'external-flow', description: 'Imported workflow', text: 'Reviewed instructions' })
})
it('shows MCP connection failure without losing server configuration', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: { ...catalog, mcp: [{ name: 'fixture', transport: 'stdio', state: 'not_connected', tools: 0 }] } }).mockRejectedValueOnce(new Error('MCP_UNAVAILABLE'))
  render(<CapabilityCatalog kind="mcp" />)
  fireEvent.click(await screen.findByRole('button', { name: 'agent.capabilities.connectionDetails' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'capabilities.connect' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/agent/capability-imports/mcp/fixture/connect'))
  expect(await screen.findByRole('dialog')).toBeTruthy()
  await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
})
it('opens built-in reference documents while keeping the skill read-only', async () => {
  const builtin = { ...skill, name: 'roami-dispatch', source: 'builtin', mutable: false, references: { 'references/chrome.md': { text: '# Chrome operations\nUse roami chrome tabs.', version: 'r1' } } }
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, skills: [builtin] } })
  render(<CapabilityCatalog kind="skills" />)
  fireEvent.click(await screen.findByRole('button', { name: 'agent.capabilities.content' }))
  fireEvent.click(screen.getByRole('button', { name: 'chrome.md' }))
  expect(await screen.findByRole('heading', { name: 'Chrome operations' })).toBeTruthy()
  expect(screen.queryByRole('switch')).toBeNull()
  expect(screen.queryByRole('button', { name: 'capabilities.edit' })).toBeNull()
})
it('keeps MCP operations in their own category and shows mutable CLI registrations', async () => {
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, cli: [{ name: 'cli', commands: [{ name: 'cli_echo', description: 'Echo JSON', enabled: true, mutable: true, source: 'external' }, { name: 'mcp_fixture_echo', description: 'MCP echo', enabled: true, mutable: true, source: 'external' }] }] } })
  render(<CapabilityCatalog kind="cli" />)
  await screen.findByText('cli_echo')
  expect(screen.queryByText('mcp_fixture_echo')).toBeNull()
  expect(screen.getByRole('switch')).toBeTruthy()
})

it('keeps discovered MCP tool switches scoped to the selected server', async () => {
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, mcp: [{ name: 'fixture', transport: 'stdio', state: 'connected', tools: 1, toolNames: ['mcp_fixture_echo'] }], cli: [{ name: 'mcp', commands: [{ name: 'mcp_fixture_echo', description: 'Echo', enabled: true, mutable: true, source: 'external' }, { name: 'mcp_fixture_other_echo', description: 'Other server', enabled: true, mutable: true, source: 'external' }] }] } })
  render(<CapabilityCatalog kind="mcp" />)
  fireEvent.click(await screen.findByRole('button', { name: 'agent.capabilities.connectionDetails' }))
  expect(screen.getAllByRole('switch')).toHaveLength(1)
  expect(screen.queryByText('Other server')).toBeNull()
  fireEvent.click(screen.getByRole('switch'))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/capability-settings', { kind: 'tools', name: 'mcp_fixture_echo', enabled: false }))
})

it('opens editing directly from a managed card and saves the existing identity', async () => {
  vi.mocked(api).mockResolvedValue({ data: catalog })
  render(<CapabilityCatalog kind="skills" />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.edit' }))
  expect((screen.getByRole('textbox', { name: 'capabilities.name' }) as HTMLInputElement).disabled).toBe(true)
  const instructions = screen.getByRole('textbox', { name: 'capabilities.instructions' }) as HTMLTextAreaElement
  expect(instructions.value).toBe(skill.text)
  fireEvent.change(instructions, { target: { value: '# Updated workflow' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.saveChanges' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/capability-imports/skills/external-flow', { name: 'external-flow', description: '', text: '# Updated workflow' }))
})
it('starts a new skill from a template and previews the written instructions', async () => {
  vi.mocked(api).mockResolvedValue({ data: catalog })
  render(<CapabilityCatalog kind="skills" />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.createAction.skills' }))
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.useTemplate' }))
  expect((screen.getByRole('textbox', { name: 'capabilities.name' }) as HTMLInputElement).value).toBe('')
  expect((screen.getByRole('textbox', { name: 'capabilities.instructions' }) as HTMLTextAreaElement).value).toBe('capabilities.template.instructions')
  fireEvent.click(screen.getByText('capabilities.preview', { exact: true }))
  expect(screen.queryByRole('textbox', { name: 'capabilities.instructions' })).toBeNull()
})

it('shows command families with their skill guide while retaining external CLI actions', async () => {
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, skills: [{ name: 'browser_use', text: '# Browser guide', source: 'builtin', version: 'v1', enabled: true }], cli: [{ name: 'commands', commands: [{ name: 'roami chrome', description: 'Browser', source: 'builtin', enabled: true, mutable: false, skill: 'browser_use', schema: { commands: [{ argv: ['roami', 'chrome', 'new', 'URL'] }] } }] }] } })
  render(<CapabilityCatalog kind="cli" />)
  fireEvent.click(await screen.findByRole('button', { name: 'roami chrome' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText('capabilities.relatedSkill')).toBeTruthy()
  expect(within(dialog).getByText(/"chrome"/)).toBeTruthy()
  expect(screen.queryByRole('switch')).toBeNull()
  expect(screen.queryByText('browser_open')).toBeNull()
})

it('edits a Chinese MCP name and description while preserving its tool identity and failed draft', async () => {
  const entry = { name: 'exa', displayName: '网页搜索', description: '搜索网页', config: { transport: 'streamable_http', url: 'https://example.com/mcp' } }
  const data = { ...catalog, mcp: [{ name: 'exa', displayName: entry.displayName, description: entry.description, transport: 'streamable_http', state: 'connected', tools: 1, toolNames: ['mcp_exa_echo'] }], managed: { ...catalog.managed, mcp: { exa: entry } } }
  vi.mocked(api).mockResolvedValueOnce({ data }).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: { ...data, mcp: [{ ...data.mcp[0], displayName: '资料检索', description: '查找和读取资料' }] } })
  render(<CapabilityCatalog kind="mcp" />)
  expect(await screen.findByRole('button', { name: '网页搜索' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'capabilities.connect' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.edit' }))
  const name = screen.getByRole('textbox', { name: 'capabilities.name' }) as HTMLInputElement
  const description = screen.getByRole('textbox', { name: 'capabilities.description' }) as HTMLInputElement
  expect(name.disabled).toBe(false)
  fireEvent.change(name, { target: { value: '资料检索' } })
  fireEvent.change(description, { target: { value: '查找和读取资料' } })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.saveChanges' }))
  await screen.findByRole('alert')
  expect(name.value).toBe('资料检索')
  expect(description.value).toBe('查找和读取资料')
  expect(api).toHaveBeenLastCalledWith('PUT', '/agent/capability-imports/mcp/exa', { ...entry, displayName: '资料检索', description: '查找和读取资料' })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.saveChanges' }))
  expect(await screen.findByRole('button', { name: '资料检索' })).toBeTruthy()
  fireEvent.change(screen.getByRole('textbox', { name: 'agent.capabilities.search' }), { target: { value: '读取资料' } })
  expect(screen.getByRole('button', { name: '资料检索' })).toBeTruthy()
})

it('creates an MCP with a Chinese name without asking for an internal identifier', async () => {
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, mcp: [] } })
  render(<CapabilityCatalog kind="mcp" />)
  fireEvent.click(await screen.findByRole('button', { name: 'capabilities.createAction.mcp' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.name' }), { target: { value: '知识库检索' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.description' }), { target: { value: '查找团队文档' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'capabilities.url' }), { target: { value: 'https://example.com/mcp' } })
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'capabilities.createAction.mcp' }))
  await waitFor(() => expect(api).toHaveBeenLastCalledWith('POST', '/agent/capability-imports/mcp', { displayName: '知识库检索', description: '查找团队文档', config: { transport: 'streamable_http', url: 'https://example.com/mcp' } }))
})
