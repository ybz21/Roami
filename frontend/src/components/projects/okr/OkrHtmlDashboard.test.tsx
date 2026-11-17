// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PageActivityProvider } from '../../../page-activity'
import OkrHtmlDashboard from './OkrHtmlDashboard'
import type { Workspace } from './okr-workspace'

const state = vi.hoisted(() => ({ api: vi.fn(), node: '' }))
vi.mock('../../../api', () => ({ api: state.api }))
vi.mock('../../../layout', () => ({ useLayout: () => ({ size: 'large', coarse: false }) }))
vi.mock('../../../theme', () => ({ useThemeMode: () => ({ mode: 'dark' }) }))
vi.mock('../../../i18n', () => ({ useI18n: () => ({ locale: 'en-US', t: (key: string) => key }) }))
vi.mock('../../cluster/node-url', () => ({ nodeApi: (path: string) => state.node + '/api' + path }))
class Channel {
 static all: Channel[] = []
 port1 = { close: vi.fn(), start: vi.fn(), postMessage: vi.fn((_value: { datasets: Record<string, unknown>; context: { locale: string; revision: number } }) => {}), onmessage: null as null | ((event: { data: object }) => void) }
 port2 = { close: vi.fn() }
 constructor() { Channel.all.push(this) }
}
const digest = 'a'.repeat(64)
const workspace: Workspace = { projectId: 'project', revision: 9, updatedAt: 'now', objective: 'Reach people', startDate: '2026-11-01', endDate: '2026-11-30', swarm: '', autoCollect: false, keyResults: [], observations: [], reviews: [], metrics: [{ id: 'users', name: 'Users', source: 'manual', unit: '' }], dashboard: { schemaVersion: 2, widgets: [], html: { entry: 'dashboard/index.html', assets: ['dashboard/index.html'], metricIds: ['users'] } }, projectFiles: { schemaVersion: 1, root: '.roami/okr', revision: 9, htmlDashboardSupported: true, dashboardDigest: digest } }
const definition = (projectId = 'project', hash = digest) => ({ data: { projectId, revision: 9, digest: hash, metricIds: ['users'], libraries: [] } })
beforeEach(() => {
 state.node = ''; state.api.mockReset(); state.api.mockResolvedValue(definition()); Channel.all = []
 vi.stubGlobal('MessageChannel', Channel)
 vi.stubGlobal('requestAnimationFrame', (callback: () => void) => { callback(); return 1 })
 vi.stubGlobal('cancelAnimationFrame', vi.fn())
 Object.defineProperty(document, 'hidden', { configurable: true, value: false })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
async function open() {
 const frame = await screen.findByTitle('okr.tab.dashboard') as HTMLIFrameElement
 vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(() => {})
 fireEvent.load(frame)
 return frame
}
it('uses an opaque frame and transfers only declared snapshots without adding data polls', async () => {
 const view = render(<OkrHtmlDashboard workspace={workspace} active />)
 const frame = await open(), channel = Channel.all[0]
 expect(frame.getAttribute('sandbox')).toBe('allow-scripts')
 expect(frame.src).toContain('/projects/project/okr/dashboard/document?digest=' + digest)
 expect(channel.port1.postMessage).toHaveBeenCalledOnce()
 const first = channel.port1.postMessage.mock.calls[0][0]
 expect(Object.keys(first.datasets)).toEqual(['users'])
 expect(first.context.locale).toBe('en-US')
 act(() => channel.port1.onmessage!({ data: { type: 'okr:ready', digest } }))
 view.rerender(<OkrHtmlDashboard workspace={{ ...workspace, revision: 10 }} active />)
 await waitFor(() => expect(channel.port1.postMessage.mock.calls.slice(-1)[0]?.[0].context.revision).toBe(10))
 expect(state.api).toHaveBeenCalledOnce()
 view.rerender(<OkrHtmlDashboard workspace={workspace} active={false} />)
 expect(channel.port1.close).toHaveBeenCalled()
 expect(screen.queryByTitle('okr.tab.dashboard')).toBeNull()
})
it('closes the channel when its document navigates again', async () => {
 render(<OkrHtmlDashboard workspace={workspace} active />)
 const frame = await open(), channel = Channel.all[0]
 fireEvent.load(frame)
 expect(channel.port1.close).toHaveBeenCalled()
 expect(screen.getByRole('alert')).toBeTruthy()
 expect(screen.queryByTitle('okr.tab.dashboard')).toBeNull()
})
it('unmounts hidden documents and releases their channel', async () => {
 render(<OkrHtmlDashboard workspace={workspace} active />)
 await open(); const channel = Channel.all[0]
 Object.defineProperty(document, 'hidden', { configurable: true, value: true })
 act(() => document.dispatchEvent(new Event('visibilitychange')))
 expect(channel.port1.close).toHaveBeenCalled()
 expect(screen.queryByTitle('okr.tab.dashboard')).toBeNull()
})
it('ignores late metadata after the node or project changes', async () => {
 let finish!: (value: unknown) => void
 state.api.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
 const view = render(<OkrHtmlDashboard workspace={workspace} active />)
 state.node = '/nodes/other'
 state.api.mockResolvedValue(definition('other'))
 view.rerender(<OkrHtmlDashboard workspace={{ ...workspace, projectId: 'other' }} active />)
 await screen.findByTitle('okr.tab.dashboard')
 await act(async () => finish(definition()))
 expect(screen.getByTitle('okr.tab.dashboard').getAttribute('src')).toContain('/nodes/other/api/projects/other/')
 expect(state.api.mock.calls[0][3].signal.aborted).toBe(true)
})
it('fails closed when metadata belongs to a different configuration and keeps retry available', async () => {
 state.api.mockResolvedValue(definition('different'))
 const refresh = vi.fn()
 render(<OkrHtmlDashboard workspace={workspace} active onRefresh={refresh} />)
 await screen.findByRole('alert')
 expect(screen.queryByTitle('okr.tab.dashboard')).toBeNull()
 state.api.mockResolvedValue(definition())
 fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
 expect(refresh).toHaveBeenCalledOnce()
 await screen.findByTitle('okr.tab.dashboard')
})

it('releases its frame when the owning page hides even if its dashboard tab stays selected', async () => {
 const view = (active: boolean) => <PageActivityProvider active={active}><OkrHtmlDashboard workspace={workspace} active /></PageActivityProvider>
 const rendered = render(view(true)); await open(); const channel = Channel.all[0]
 rendered.rerender(view(false))
 expect(screen.queryByTitle('okr.tab.dashboard')).toBeNull()
 expect(channel.port1.close).toHaveBeenCalled()
 rendered.rerender(view(true)); await open()
 expect(state.api).toHaveBeenCalledTimes(2)
})
