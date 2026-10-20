// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentBalance, ProfessionalAgents } from './professional-agents'
import { discoverAgents } from '../../agent-registry'
import type { SettingItem } from './registry'

const state = vi.hoisted(() => ({ prefs: { agentBalanceRefreshSeconds: 60 } }))
vi.mock('../../agent-registry', () => ({ discoverAgents: vi.fn(), installAgent: vi.fn() }))
vi.mock('../../preferences', () => ({ usePreferences: () => [state.prefs, vi.fn()] }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string, vars?: unknown) => key + (vars ? JSON.stringify(vars) : '') }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); state.prefs.agentBalanceRefreshSeconds = 60 })
const items: SettingItem[] = [{ id: 'codexCommand', label: 'Codex', control: { kind: 'text', get: () => 'codex', set: () => {} } }]
const snapshot = { kind: 'codex', installed: true, quota: { state: 'available' as const, windows: [
  { remainingPercent: 0, windowMinutes: 300, resetsAt: Math.floor(Date.now() / 1000) + 3600 },
  { remainingPercent: 75, windowMinutes: 10080, resetsAt: Math.floor(Date.now() / 1000) + 7200 },
] } }

it('shows exhausted and weekly balances with reset periods and hides expired snapshots', () => {
  const view = render(<AgentBalance agent={snapshot} />)
  expect(screen.getByText('agent.professional.remaining{"percent":0}')).toBeTruthy()
  expect(screen.getByText('agent.professional.periodDays{"n":7}')).toBeTruthy()
  expect(screen.getAllByText(/agent.professional.resetsAt/)).toHaveLength(2)
  view.rerender(<AgentBalance agent={{ ...snapshot, quota: { state: 'available', windows: [{ remainingPercent: 80, windowMinutes: 300, resetsAt: 1 }] } }} />)
  expect(screen.getByText('agent.professional.reason.no_snapshot')).toBeTruthy()
  expect(screen.queryByText(/agent.professional.remaining/)).toBeNull()
})

it('adapts polling when preferences arrive and keeps balances on failure', async () => {
  vi.mocked(discoverAgents).mockResolvedValue([snapshot])
  let poll!: () => void
  const timer = vi.spyOn(window, 'setInterval').mockImplementation((callback, ms) => { if ((ms || 0) >= 30000) poll = callback as () => void; return 42 })
  const clear = vi.spyOn(window, 'clearInterval')
  const view = render(<ProfessionalAgents items={items} />)
  await screen.findByText('agent.professional.remaining{"percent":75}')
  expect(timer).toHaveBeenCalledWith(expect.any(Function), 60000)
  state.prefs.agentBalanceRefreshSeconds = 300
  view.rerender(<ProfessionalAgents items={items} />)
  await waitFor(() => expect(timer).toHaveBeenCalledWith(expect.any(Function), 300000))
  vi.mocked(discoverAgents).mockRejectedValue(new Error('offline'))
  await act(async () => { poll() })
  expect(screen.getByRole('alert').textContent).toContain('agent.professional.loadFailed')
  expect(screen.getByText('agent.professional.remaining{"percent":75}')).toBeTruthy()
  view.unmount()
  expect(clear).toHaveBeenCalledWith(42)
})

it('keeps command management available on failure and retries native discovery', async () => {
  vi.mocked(discoverAgents).mockRejectedValueOnce(new Error('offline')).mockResolvedValue([snapshot])
  render(<ProfessionalAgents items={items} />)
  await screen.findByRole('alert')
  expect(screen.getByRole('button', { name: 'agent.professional.manage{"name":"Codex"}' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await screen.findByText('agent.professional.remaining{"percent":75}')
})
