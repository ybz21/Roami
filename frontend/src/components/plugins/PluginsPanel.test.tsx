// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import PluginsPanel from './PluginsPanel'
import { api } from '../../api'
import { useBackDismiss } from '../shell/useBackDismiss'

const layout = vi.hoisted(() => ({ phone: false }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => layout }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../visible-poll', () => ({ pollWhileVisible: () => ({ stop: vi.fn() }) }))
vi.mock('../shell/useBackDismiss', () => ({ useBackDismiss: vi.fn() }))
vi.mock('./HostMonitorPanel', () => ({ default: () => <div>Monitor content</div> }))
vi.mock('./CronPanel', () => ({ default: () => null }))
vi.mock('./KeepalivePanel', () => ({ default: () => null }))

const monitor = {
  manifest: { id: 'roam.host-monitor', name: 'monitor', version: '1.2.0', displayName: { 'en-US': 'Host monitor' }, description: { 'en-US': 'Monitor this machine' }, runtime: { kind: 'builtin' },
    contributes: { configFields: [{ key: 'destination', title: { 'en-US': 'Destination' } }, { key: 'token', title: { 'en-US': 'Token' }, secret: true }] } },
  enabled: true, installed: '2026-10-21',
}
const archive = { manifest: { id: 'external.archive', name: 'archive', version: '2.0.0', displayName: { 'en-US': 'Delivery archive' }, description: { 'en-US': 'Organize deliverables' }, runtime: { kind: 'exec' } }, enabled: false, installed: '2026-10-21' }

beforeAll(() => {
  const style = window.getComputedStyle
  window.getComputedStyle = element => style(element)
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
beforeEach(() => {
  layout.phone = false
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (path === '/plugins') return [monitor, archive]
    if (path.endsWith('/config')) return { destination: 'Roami', token: '********' }
    return []
  })
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.mocked(api).mockReset() })

it('keeps plugin details closed until requested and searches names, descriptions and IDs', async () => {
  render(<PluginsPanel />)
  await screen.findByRole('article', { name: 'Host monitor' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByText('1.2.0')).toBeTruthy()
  expect(screen.getByText('capabilities.source.builtin')).toBeTruthy()
  const search = screen.getByRole('textbox', { name: 'plugins.search' })
  fireEvent.change(search, { target: { value: 'external.archive' } })
  expect(screen.queryByRole('article', { name: 'Host monitor' })).toBeNull()
  expect(screen.getByRole('article', { name: 'Delivery archive' })).toBeTruthy()
  fireEvent.change(search, { target: { value: 'unknown' } })
  expect(screen.getByText('plugins.noResults')).toBeTruthy()
})

it('persists a card switch and keeps its last saved value when a later request fails', async () => {
  render(<PluginsPanel />)
  const card = await screen.findByRole('article', { name: 'Host monitor' })
  const toggle = within(card).getByRole('switch')
  fireEvent.click(toggle)
  await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
  expect(api).toHaveBeenCalledWith('POST', '/plugins/roam.host-monitor/disable')
  vi.mocked(api).mockRejectedValueOnce(new Error('offline'))
  fireEvent.click(toggle)
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/plugins/roam.host-monitor/enable'))
  await screen.findByText('offline')
  expect(toggle.getAttribute('aria-checked')).toBe('false')
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('opens configuration directly and submits only changes, preserving masked secrets', async () => {
  const onSelect = vi.fn()
  const view = render(<PluginsPanel onSelect={onSelect} />)
  const card = await screen.findByRole('article', { name: 'Host monitor' })
  fireEvent.click(within(card).getByRole('button', { name: 'plugins.tabConfig' }))
  expect(onSelect).toHaveBeenCalledWith('roam.host-monitor')
  view.rerender(<PluginsPanel initialId="roam.host-monitor" onSelect={onSelect} />)
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('tab', { name: 'plugins.tabConfig' }).getAttribute('aria-selected')).toBe('true')
  const destination = within(dialog).getByRole('textbox', { name: 'Destination' })
  await waitFor(() => expect((destination as HTMLInputElement).value).toBe('Roami'))
  fireEvent.change(destination, { target: { value: 'Inbox' } })
  vi.mocked(api).mockRejectedValueOnce(new Error('could not save'))
  fireEvent.click(within(dialog).getByRole('button', { name: 'plugins.save' }))
  await screen.findByText('could not save')
  expect((destination as HTMLInputElement).value).toBe('Inbox')
  expect(api).toHaveBeenCalledWith('PUT', '/plugins/roam.host-monitor/config', { set: { destination: 'Inbox' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'plugins.save' }))
  await screen.findByText('plugins.saved')
})

it('opens mobile deep links without adding an overlay history entry and returns to the catalog', async () => {
  layout.phone = true
  const onSelect = vi.fn()
  render(<PluginsPanel initialId="roam.host-monitor" onSelect={onSelect} />)
  await screen.findByText('Monitor content')
  expect(useBackDismiss).toHaveBeenCalledWith(false, expect.any(Function))
  fireEvent.click(screen.getByRole('button', { name: 'common.back' }))
  expect(onSelect).toHaveBeenCalledWith('')
  await waitFor(() => expect(screen.queryByText('Monitor content')).toBeNull())
})

it('retries an initial catalog failure without offering a permanent refresh action', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline'))
  render(<PluginsPanel />)
  fireEvent.click(await screen.findByRole('button', { name: 'agent.retry' }))
  await screen.findByRole('article', { name: 'Host monitor' })
  expect(screen.queryByRole('button', { name: 'agent.retry' })).toBeNull()
})

it('uninstalls the selected plugin with the explicit purge option and closes its details', async () => {
  render(<PluginsPanel initialId="roam.host-monitor" />)
  const dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'plugins.uninstall' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'plugins.uninstallPurge' }))
  fireEvent.click(screen.getByRole('button', { name: 'OK' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('DELETE', '/plugins/roam.host-monitor?purge=1'))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('blocks editing after a configuration load failure and recovers without submitting empty fields', async () => {
  let fail = true
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (path === '/plugins') return [monitor]
    if (method === 'GET' && path.endsWith('/config')) {
      if (fail) throw new Error('offline')
      return { destination: 'Roami', token: '********' }
    }
    return []
  })
  render(<PluginsPanel initialId="roam.host-monitor" />)
  fireEvent.click(await screen.findByRole('tab', { name: 'plugins.tabConfig' }))
  await screen.findByText('plugins.configLoadFailed')
  expect(screen.queryByRole('textbox', { name: 'Destination' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'plugins.save' })).toBeNull()
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'PUT')).toBe(false)
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  const field = await screen.findByRole('textbox', { name: 'Destination' }) as HTMLInputElement
  expect(field.value).toBe('Roami')
  expect((screen.getByLabelText('Token') as HTMLInputElement).value).toBe('********')
})
