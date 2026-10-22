// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { AgentCatalog } from './AgentCatalog'
import { AgentBalance } from './AgentBalance'
import { checkAgent, discoverAgents, installAgent, upgradeAgent } from '../../agent-registry'
import { useBackDismiss } from '../shell/useBackDismiss'

const state = vi.hoisted(() => ({
  prefs: { agentBalanceRefreshSeconds: 60, codexCommand: 'codex --model configured', claudeCommand: 'claude', piCommand: 'pi', opencodeCommand: 'opencode' },
  loaded: true, phone: false, save: vi.fn(), polls: [] as Array<(signal: AbortSignal) => Promise<unknown>>, stop: vi.fn(),
}))
vi.mock('../../agent-registry', () => ({ discoverAgents: vi.fn(), installAgent: vi.fn(), checkAgent: vi.fn(), upgradeAgent: vi.fn() }))
vi.mock('../../preferences', () => ({ usePreferences: () => [state.prefs, state.save], preferencesLoaded: () => state.loaded }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: state.phone }) }))
vi.mock('../../visible-poll', () => ({ pollWhileVisible: (load: (signal: AbortSignal) => Promise<unknown>) => {
  state.polls.push(load); void load(new AbortController().signal).catch(() => {}); return { stop: state.stop }
} }))
vi.mock('../shell/useBackDismiss', () => ({ useBackDismiss: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string, vars?: unknown) => key + (vars ? JSON.stringify(vars) : '') }) }))
const snapshot = { kind: 'codex', installed: true, binary: '/usr/bin/codex', authentication: 'unknown' as const, quota: { state: 'available' as const, windows: [
  { remainingPercent: 0, windowMinutes: 300, resetsAt: Math.floor(Date.now() / 1000) + 3600 },
  { remainingPercent: 75, windowMinutes: 10080, resetsAt: Math.floor(Date.now() / 1000) + 7200 },
] } }
beforeAll(() => {
  const style = window.getComputedStyle; window.getComputedStyle = element => style(element)
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
beforeEach(() => { vi.mocked(discoverAgents).mockResolvedValue([snapshot]); state.save.mockResolvedValue(true) })
afterEach(() => { cleanup(); vi.clearAllMocks(); state.polls = []; state.loaded = true; state.phone = false; state.prefs = { agentBalanceRefreshSeconds: 60, codexCommand: 'codex --model configured', claudeCommand: 'claude', piCommand: 'pi', opencodeCommand: 'opencode' } })

it('shows exhausted and weekly balances and hides expired snapshots', () => {
  const view = render(<AgentBalance agent={snapshot} />)
  expect(screen.getByText('agent.professional.remaining{"percent":0}')).toBeTruthy()
  expect(screen.getByText('agent.professional.periodDays{"n":7}')).toBeTruthy()
  expect(screen.getAllByText(/agent.professional.resetsAt/)).toHaveLength(2)
  view.rerender(<AgentBalance agent={{ ...snapshot, quota: { state: 'available', windows: [{ remainingPercent: 80, windowMinutes: 300, resetsAt: 1 }] } }} />)
  expect(screen.getByText('agent.professional.reason.no_snapshot')).toBeTruthy()
})

it('shows agent cards without opening details and keeps installation separate from sign-in', async () => {
  const select = vi.fn()
  render(<AgentCatalog onSelect={select} />)
  await screen.findByText('agent.professional.remaining{"percent":75}')
  expect(screen.getAllByRole('article')).toHaveLength(4)
  const card = screen.getByRole('article', { name: 'Codex' })
  expect(within(card).getByText('agent.professional.installed')).toBeTruthy()
  expect(within(card).getByText('capabilities.agents.auth.unknown')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(within(card).getByRole('button', { name: 'capabilities.agents.manage' }))
  expect(select).toHaveBeenCalledWith('codex')
})

it('waits for stored preferences before hydrating a command and preserves edits after a failed save', async () => {
  state.loaded = false
  const view = render(<AgentCatalog initialKind="codex" onSelect={vi.fn()} />)
  const field = screen.getByRole('textbox', { name: 'capabilities.agents.command' }) as HTMLInputElement
  expect(field.disabled).toBe(true); expect(field.value).toBe('')
  state.loaded = true; state.prefs = { ...state.prefs, codexCommand: '/custom/codex --model stored' }
  view.rerender(<AgentCatalog initialKind="codex" onSelect={vi.fn()} />)
  await waitFor(() => expect(field.value).toBe('/custom/codex --model stored'))
  fireEvent.change(field, { target: { value: '/custom/codex --model chosen' } })
  state.save.mockResolvedValueOnce(false)
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.saveChanges' }))
  await screen.findByText('settings.preference.failed')
  expect(field.value).toBe('/custom/codex --model chosen')
  expect(state.save).toHaveBeenCalledWith({ codexCommand: '/custom/codex --model chosen' })
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.saveChanges' }))
  await screen.findByText('capabilities.agents.saved')
})

it('accepts newer versions from automatic snapshots and preserves data after discovery failure', async () => {
  vi.mocked(checkAgent).mockResolvedValue({ ...snapshot, version: 'codex-cli 1.2.3', versionState: 'available' })
  render(<AgentCatalog initialKind="codex" onSelect={vi.fn()} />)
  const card = screen.getByRole('article', { name: 'Codex' })
  await within(card).findByText('agent.professional.remaining{"percent":75}')
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'capabilities.agents.check' }))
  await within(card).findByText('codex-cli 1.2.3')
  expect(checkAgent).toHaveBeenCalledWith('codex')
  vi.mocked(discoverAgents).mockResolvedValue([{ ...snapshot, version: 'codex-cli 2.0.0', versionState: 'available' }])
  await act(() => state.polls[0](new AbortController().signal))
  expect(within(card).getByText('codex-cli 2.0.0')).toBeTruthy()
  expect(screen.queryByText('codex-cli 1.2.3')).toBeNull()
  vi.mocked(discoverAgents).mockRejectedValueOnce(new Error('offline'))
  await act(async () => { try { await state.polls[0](new AbortController().signal) } catch {} })
  expect(screen.getByText('agent.professional.loadFailed')).toBeTruthy()
  expect(within(card).getByText('codex-cli 2.0.0')).toBeTruthy()
})

it('upgrades an installed agent after confirmation and displays the verified version', async () => {
  vi.mocked(upgradeAgent).mockResolvedValue({ ...snapshot, version: 'codex-cli 2.0.0', versionState: 'available' })
  render(<AgentCatalog onSelect={vi.fn()} />)
  const card = screen.getByRole('article', { name: 'Codex' })
  fireEvent.click(await within(card).findByRole('button', { name: 'capabilities.agents.update' }))
  expect(upgradeAgent).not.toHaveBeenCalled()
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'capabilities.agents.update' }))
  await within(card).findByText('codex-cli 2.0.0')
  expect(upgradeAgent).toHaveBeenCalledWith('codex')
  expect(installAgent).not.toHaveBeenCalled()
})

it('opens the agent model route directly from its card', async () => {
  const select = vi.fn()
  render(<AgentCatalog onSelect={select} />)
  const card = screen.getByRole('article', { name: 'Codex' })
  fireEvent.click(within(card).getByRole('button', { name: 'capabilities.models.manage' }))
  expect(select).toHaveBeenCalledWith('codex/models')
})

it('shows all installed versions on entry without explicit checks and marks unreadable versions', async () => {
  vi.mocked(discoverAgents).mockResolvedValue([
    ...['claude', 'codex', 'opencode'].map(kind => ({ ...snapshot, kind, version: kind + ' 1.0', versionState: 'available' as const })),
    { ...snapshot, kind: 'pi', versionState: 'unavailable' },
  ])
  render(<AgentCatalog onSelect={vi.fn()} />)
  for (const kind of ['claude', 'codex', 'opencode']) expect(await screen.findByText(kind + ' 1.0')).toBeTruthy()
  expect(within(screen.getByRole('article', { name: 'Pi' })).getByText('capabilities.agents.versionUnknown')).toBeTruthy()
  expect(checkAgent).not.toHaveBeenCalled()
})

it('uses the installation endpoint only after confirming a missing agent installation', async () => {
  vi.mocked(discoverAgents).mockResolvedValue([snapshot, { kind: 'pi', installed: false, quota: { state: 'unknown' } }])
  vi.mocked(installAgent).mockResolvedValue()
  render(<AgentCatalog onSelect={vi.fn()} />)
  const card = screen.getByRole('article', { name: 'Pi' })
  fireEvent.click(await within(card).findByRole('button', { name: 'agentDiscovery.install' }))
  expect(installAgent).not.toHaveBeenCalled()
  fireEvent.click(within(await screen.findByRole('tooltip')).getByRole('button', { name: 'agentDiscovery.install' }))
  await waitFor(() => expect(installAgent).toHaveBeenCalledWith('pi'))
})

it('opens the existing terminal workflow for login and model configuration', async () => {
  const launch = vi.fn().mockResolvedValue(undefined)
  render(<AgentCatalog initialKind="codex" onSelect={vi.fn()} onLaunch={launch} />)
  const open = await screen.findByRole('button', { name: 'capabilities.agents.openTerminal' }) as HTMLButtonElement
  await waitFor(() => expect(open.disabled).toBe(false))
  fireEvent.click(open)
  await waitFor(() => expect(launch).toHaveBeenCalledWith('codex'))
})

it('keeps mobile details in URL history and returns to the agent catalog', async () => {
  state.phone = true
  const select = vi.fn()
  render(<AgentCatalog initialKind="codex" onSelect={select} />)
  await screen.findByRole('textbox', { name: 'capabilities.agents.command' })
  expect(useBackDismiss).toHaveBeenCalledWith(false, expect.any(Function))
  fireEvent.click(screen.getByRole('button', { name: 'common.back' }))
  expect(select).toHaveBeenCalledWith('')
})
