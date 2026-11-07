// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionMemoryAlerts, SessionPauseButton } from './SessionMemoryControl'

const mocks = vi.hoisted(() => ({
  api: vi.fn(), error: vi.fn(), warning: vi.fn(), destroy: vi.fn(),
  overview: { loaded: true, failed: false, value: [] as any[] },
}))
vi.mock('../../api', () => ({ api: mocks.api }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../session-overview', () => ({ useSessionOverview: () => mocks.overview }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { error: mocks.error }, notification: { warning: mocks.warning, destroy: mocks.destroy } }) },
  Button: ({ children, onClick }: any) => <button type="button" onClick={onClick}>{children}</button>,
}))

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  mocks.api.mockResolvedValue({})
  mocks.overview = { loaded: true, failed: false, value: [] }
})

describe('session memory recovery', () => {
  it('resumes a paused session and refreshes shared lists', async () => {
    const refresh = vi.fn()
    window.addEventListener('roami:sessions-changed', refresh)
    const onRow = vi.fn()
    render(<div onClick={onRow}><SessionPauseButton name="session/one" mem={{ cur: 10, paused: true }} /></div>)
    fireEvent.click(screen.getByRole('button', { name: 'session.mem.resume' }))
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    expect(mocks.api).toHaveBeenCalledWith('POST', '/sessions/session%2Fone/resume')
    expect(onRow).not.toHaveBeenCalled()
    window.removeEventListener('roami:sessions-changed', refresh)
  })

  it('explains unavailable freezing and retains the recovery action', async () => {
    mocks.api.mockRejectedValue({ apiError: { code: 'SESSION_PAUSE_UNAVAILABLE' } })
    render(<SessionPauseButton name="one" />)
    fireEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith('session.mem.unavailable'))
    expect(screen.getByRole('button').hasAttribute('disabled')).toBe(false)
  })

  it('notifies on state transitions and opens the affected session', () => {
    const onOpen = vi.fn()
    mocks.overview.value = [{ name: 'one', label: 'Work', mem: { warning: true } }]
    const view = render(<SessionMemoryAlerts onOpen={onOpen} />)
    view.rerender(<SessionMemoryAlerts onOpen={onOpen} />)
    expect(mocks.warning).toHaveBeenCalledTimes(1)
    mocks.overview.value = [{ name: 'one', label: 'Work', mem: { paused: true } }]
    view.rerender(<SessionMemoryAlerts onOpen={onOpen} />)
    expect(mocks.warning).toHaveBeenCalledTimes(2)
    const latest = mocks.warning.mock.lastCall![0]
    render(latest.btn)
    fireEvent.click(screen.getByRole('button'))
    expect(onOpen).toHaveBeenCalledWith('one')
    mocks.overview.value = []
    view.rerender(<SessionMemoryAlerts onOpen={onOpen} />)
    expect(mocks.destroy).toHaveBeenCalledWith('session-memory:local:one')
  })

  it('keeps the visible session alert in its banner without a duplicate popup', () => {
    mocks.overview.value = [{ name: 'one', label: 'Work', mem: { warning: true } }]
    const view = render(<SessionMemoryAlerts onOpen={vi.fn()} />)
    expect(mocks.warning).toHaveBeenCalledTimes(1)
    view.rerender(<SessionMemoryAlerts onOpen={vi.fn()} visibleSession="one" />)
    expect(mocks.destroy).toHaveBeenCalledWith('session-memory:local:one')
    mocks.overview.value = [{ name: 'one', label: 'Work', mem: { paused: true } }]
    view.rerender(<SessionMemoryAlerts onOpen={vi.fn()} visibleSession="one" />)
    expect(mocks.warning).toHaveBeenCalledTimes(1)
  })
})
