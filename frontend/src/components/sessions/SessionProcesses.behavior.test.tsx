// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProcesses } from './SessionProcesses'
const mocks = vi.hoisted(() => ({ api: vi.fn(), confirm: vi.fn(), destroy: vi.fn(), error: vi.fn(), refresh: vi.fn(), stop: vi.fn(), load: undefined as any }))
vi.mock('../../api', () => ({ api: mocks.api }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('./native-session-list', () => ({ refreshSessionLists: vi.fn() }))
vi.mock('../../visible-poll', () => ({ pollWhileVisible: (load: any) => { mocks.load = load; void load(new AbortController().signal).catch(() => {}); return { refresh: mocks.refresh, stop: mocks.stop } } }))
vi.mock('antd', () => ({ App: { useApp: () => ({ modal: { confirm: mocks.confirm }, message: { error: mocks.error, success: vi.fn() } }) }, Drawer: ({ children }: any) => <div>{children}</div>, Spin: () => null }))
const root = { pid: 10, ppid: 1, name: 'bash', rss: 1024, swap: 0, start: '111', protected: true, command: 'bash', state: 'S' }
const child = { ...root, pid: 20, ppid: 10, name: 'java', start: '222', protected: false }
afterEach(cleanup)
beforeEach(() => { vi.clearAllMocks(); mocks.api.mockResolvedValue({ processes: [root, child] }); mocks.confirm.mockReturnValue({ destroy: mocks.destroy }); mocks.refresh.mockResolvedValue(undefined) })
describe('session process controls', () => {
  it('confirms and submits the selected identity while protecting roots', async () => {
    const view = render(<SessionProcesses name="one/two" onClose={() => {}} />)
    await screen.findByText('java')
    expect(screen.getAllByRole('button', { name: 'session.process.stop' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'session.process.force' }))
    expect(mocks.api).toHaveBeenCalledTimes(1)
    await mocks.confirm.mock.calls[0][0].onOk()
    expect(mocks.api).toHaveBeenCalledWith('POST', '/sessions/one%2Ftwo/processes/20/stop', { start: '222', force: true })
    view.unmount(); expect(mocks.stop).toHaveBeenCalled(); expect(mocks.destroy).toHaveBeenCalled()
  })
  it('disables stale rows after a snapshot read fails', async () => {
    render(<SessionProcesses name="one" onClose={() => {}} />)
    await screen.findByText('java')
    mocks.api.mockRejectedValueOnce(new Error('offline'))
    await mocks.load(new AbortController().signal).catch(() => {})
    await waitFor(() => expect((screen.getByRole('button', { name: 'session.process.stop' }) as HTMLButtonElement).disabled).toBe(true))
    expect(screen.getByRole('alert').textContent).toContain('session.process.loadFailed')
  })
})
