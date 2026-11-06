// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProjectOkr from './ProjectOkr'
import type { Workspace } from './okr-workspace'

const state = vi.hoisted(() => ({ api: vi.fn(), size: 'large', phone: false }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ phone: state.phone, size: state.size, coarse: state.phone }) }))
vi.mock('../../../theme', () => ({ useThemeMode: () => ({ mode: 'dark' }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string) => key }) }))
vi.mock('./OkrMainChat', () => ({ default: ({ onClose }: { onClose: () => void }) => <aside><button type="button" onClick={onClose}>Close Main view</button></aside> }))
const digest = 'a'.repeat(64)
const workspace: Workspace = {
 projectId: 'project', revision: 3, objective: 'Reach developers', startDate: '2026-11-01', endDate: '2026-11-30', metrics: [{ id: 'users', name: 'Users', unit: '', source: 'manual' }], keyResults: [], observations: [], reviews: [], swarm: '', autoCollect: false, updatedAt: 'now',
 dashboard: { schemaVersion: 2, widgets: [], html: { entry: 'dashboard/index.html', assets: ['dashboard/index.html'], metricIds: ['users'] } },
 projectFiles: { root: '.roami/okr', schemaVersion: 1, revision: 3, htmlDashboardSupported: true, dashboardDigest: digest },
}
beforeEach(() => {
 localStorage.clear(); state.api.mockReset(); state.size = 'large'; state.phone = false
 Object.defineProperty(document, 'hidden', { configurable: true, value: false })
 vi.stubGlobal('requestAnimationFrame', (callback: () => void) => { callback(); return 1 })
 vi.stubGlobal('cancelAnimationFrame', vi.fn())
 vi.stubGlobal('MessageChannel', class { port1 = { start() {}, close() {}, postMessage() {}, onmessage: null }; port2 = { close() {} } })
 window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
 state.api.mockImplementation(async (_method, path) => ({ data: path === '/agent/swarms' ? [] : path.endsWith('/dashboard') ? { projectId: 'project', revision: 3, digest, metricIds: ['users'], libraries: [] } : workspace }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it.each(['compact', 'medium', 'large'])('releases the HTML frame only when Main covers the workspace (%s)', async size => {
 state.size = size; state.phone = size === 'compact'
 render(<ProjectOkr projectId="project" />)
 await screen.findByRole('button', { name: 'okr.edit' })
 fireEvent.click(screen.getByRole('tab', { name: 'okr.tab.dashboard' }))
 await screen.findByTitle('okr.tab.dashboard')
 fireEvent.click(screen.getByRole('button', { name: 'okr.chatOpen' }))
 await screen.findByRole('button', { name: 'Close Main view' })
 await waitFor(() => expect(!!screen.queryByTitle('okr.tab.dashboard')).toBe(size === 'large'))
 fireEvent.click(screen.getByRole('button', { name: 'Close Main view' }))
 await screen.findByTitle('okr.tab.dashboard')
 expect(screen.getByRole('tab', { name: 'okr.tab.dashboard' }).getAttribute('aria-selected')).toBe('true')
 expect(state.api.mock.calls.some(([method]) => method !== 'GET')).toBe(false)
})
