// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentCapabilities } from './agent-capabilities'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../i18n', () => { const t = (key: string) => key; return { useI18n: () => ({ t }) } })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const skill = { name: 'roami-dispatch', text: 'Dispatch through the CLI', version: 'abc123456789', source: 'configured', enabled: true, mutable: true }
const catalog = { skills: [skill], tools: [], mcp: [] }
it('persists a skill switch and retains the saved state after an API failure', async () => {
  vi.mocked(api).mockResolvedValueOnce({ data: catalog }).mockResolvedValueOnce({ data: { ...catalog, skills: [{ ...skill, enabled: false }] } }).mockRejectedValueOnce(new Error('offline'))
  render(<AgentCapabilities kind="skills" />)
  const toggle = await screen.findByRole('switch')
  expect(toggle.getAttribute('aria-checked')).toBe('true')
  fireEvent.click(toggle)
  await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
  expect(api).toHaveBeenCalledWith('PUT', '/agent/capability-settings', { kind: 'skills', name: 'roami-dispatch', enabled: false })
  fireEvent.click(toggle)
  await screen.findByRole('alert')
  expect(toggle.getAttribute('aria-checked')).toBe('false')
  fireEvent.click(screen.getByRole('button', { name: 'agent.capabilities.content' }))
  expect(await screen.findByText('Dispatch through the CLI')).toBeTruthy()
})
it('shows a retry when the capability catalog cannot be loaded', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: catalog })
  render(<AgentCapabilities kind="skills" />)
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  expect(await screen.findByRole('switch')).toBeTruthy()
})

it('marks the upload entry as reserved without pretending to import files', async () => {
  vi.mocked(api).mockResolvedValue({ data: catalog })
  render(<AgentCapabilities kind="skills" />)
  await screen.findByRole('switch')
  fireEvent.click(screen.getByRole('button', { name: 'agent.capabilities.import.skills' }))
  expect(await screen.findByText('agent.capabilities.importReserved')).toBeTruthy()
  expect(vi.mocked(api).mock.calls.every(call => call[0] === 'GET')).toBe(true)
})

it('shows unknown MCP connection state and opens connection details', async () => {
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, mcp: [{ name: 'local-fixture', transport: 'stdio', state: 'unknown', tools: 0 }] } })
  render(<AgentCapabilities kind="mcp" />)
  expect(await screen.findByText('local-fixture')).toBeTruthy()
  expect(screen.getByText('agent.capabilities.mcp.unknown')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'agent.capabilities.connectionDetails' }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
})

it('shows seven tools and manages business operations in a separate CLI tab', async () => {
  const names = ['read', 'bash', 'edit', 'write', 'tool_list', 'delegate', 'ask_user']
  const tools = names.map(name => ({ name, description: 'runtime description', schema: { type: 'object' }, effect: 'read', main: true, enabled: true, mutable: false, source: 'builtin' }))
  const data = { ...catalog, tools, cli: [{ name: 'sessions', commands: [{ name: 'session_send', description: 'Send to a session', enabled: true, mutable: false }, { name: 'http_external', description: 'External service', enabled: true, mutable: true }] }] }
  vi.mocked(api).mockResolvedValue({ data })
  const { container } = render(<AgentCapabilities kind="tools" />)
  await screen.findByText('tool_list')
  expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['skills', 'cli', 'mcp', 'tools'].map(tab => 'agent.capabilities.tab.' + tab))
  expect(screen.queryAllByRole('switch')).toHaveLength(0)
  expect(screen.getAllByText('agent.capabilities.builtinFixed')).toHaveLength(7)
  expect(Array.from(container.querySelector('.agent-capability-grid')!.querySelectorAll('.agent-capability-heading strong')).map(node => node.textContent)).toEqual(names)
  expect(container.querySelector('.agent-capability-cli')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: 'agent.capabilities.tab.cli' }))
  await screen.findByText('session_send')
  expect(container.querySelector('.agent-capability-card .agent-capability-heading')).toBeNull()
  fireEvent.click(screen.getByText('agent.capabilities.cliCommands'))
  fireEvent.click(screen.getByRole('switch'))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/capability-settings', { kind: 'tools', name: 'http_external', enabled: false }))
})


it('opens built-in skill reference documents without any edit or enable controls', async () => {
  const builtin = { ...skill, source: 'builtin', mutable: false, references: { 'references/chrome.md': { text: '# Chrome operations\nUse roami chrome tabs.', version: 'r1' } } }
  vi.mocked(api).mockResolvedValue({ data: { ...catalog, skills: [builtin] } })
  render(<AgentCapabilities kind="skills" />)
  await screen.findByText('roami-dispatch')
  expect(screen.queryByRole('switch')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'agent.capabilities.content' }))
  fireEvent.click(await screen.findByRole('button', { name: 'chrome.md' }))
  expect(await screen.findByRole('heading', { name: 'Chrome operations' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'agent.capabilities.skillOverview' }))
  expect(screen.getByText('Dispatch through the CLI')).toBeTruthy()
  expect(vi.mocked(api).mock.calls.every(call => call[0] === 'GET')).toBe(true)
})
