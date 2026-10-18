// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentCapabilities } from './agent-capabilities'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../i18n', () => { const t = (key: string) => key; return { useI18n: () => ({ t }) } })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const skill = { name: 'roami-dispatch', text: 'Dispatch through the CLI', version: 'abc123456789', source: 'builtin', enabled: true }
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
  expect(screen.getByText('Dispatch through the CLI')).toBeTruthy()
})
it('shows a retry when the capability catalog cannot be loaded', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: catalog })
  render(<AgentCapabilities kind="skills" />)
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  expect(await screen.findByRole('switch')).toBeTruthy()
})
