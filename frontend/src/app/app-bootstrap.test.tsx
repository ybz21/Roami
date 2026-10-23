// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const mock = vi.hoisted(() => ({
  api: vi.fn(), bootstrap: vi.fn(), preferences: vi.fn(), unmount: vi.fn(),
  unauthorized: () => { },
}))
vi.mock('../api', () => ({
  api: mock.api,
  setUnauthorizedHandler: (handler: () => void) => { mock.unauthorized = handler },
}))
vi.mock('../components/cluster/node-url', () => ({ bootstrapCluster: mock.bootstrap }))
vi.mock('../preferences', () => ({ loadPreferences: mock.preferences }))
vi.mock('../components/auth/Login', () => ({ default: ({ onOk }: { onOk: () => void }) => <button onClick={onOk}>Login</button> }))
vi.mock('../components/terminal/SoloTerminal', () => ({ default: ({ name }: { name: string }) => <div>Solo {name}</div> }))
vi.mock('./AppShell', () => ({
  default: () => {
    useEffect(() => mock.unmount, [])
    return <div>Workspace</div>
  }
}))

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>(done => { resolve = done })
  return { promise, resolve }
}

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '#/projects')
  mock.api.mockResolvedValue({})
  mock.bootstrap.mockResolvedValue(undefined)
})
afterEach(cleanup)

describe('application mount boundary', () => {
  it('waits for authentication and node addressing before mounting business components', async () => {
    const me = deferred(), cluster = deferred()
    mock.api.mockReturnValueOnce(me.promise)
    mock.bootstrap.mockReturnValueOnce(cluster.promise)
    render(<App />)
    expect(screen.queryByText('Workspace')).toBeNull()
    expect(mock.bootstrap).not.toHaveBeenCalled()
    await act(async () => me.resolve())
    expect(mock.bootstrap).toHaveBeenCalledOnce()
    expect(screen.queryByText('Workspace')).toBeNull()
    expect(mock.preferences).not.toHaveBeenCalled()
    await act(async () => cluster.resolve())
    expect(screen.getByText('Workspace')).toBeTruthy()
    expect(mock.preferences).toHaveBeenCalledOnce()
  })

  it('uses the same bootstrap boundary after login and unmounts on an expired session', async () => {
    mock.api.mockRejectedValueOnce(new Error('UNAUTHORIZED'))
    render(<App />)
    await screen.findByText('Login')
    expect(mock.bootstrap).not.toHaveBeenCalled()
    const cluster = deferred()
    mock.bootstrap.mockReturnValueOnce(cluster.promise)
    fireEvent.click(screen.getByText('Login'))
    expect(screen.queryByText('Workspace')).toBeNull()
    await act(async () => cluster.resolve())
    await screen.findByText('Workspace')
    act(() => mock.unauthorized())
    expect(screen.getByText('Login')).toBeTruthy()
    expect(mock.unmount).toHaveBeenCalledOnce()
  })

  it('opens a standalone terminal without mounting the workspace', async () => {
    history.replaceState(null, '', '#/term/test%20session')
    render(<App />)
    await screen.findByText('Solo test session')
    expect(screen.queryByText('Workspace')).toBeNull()
  })

  it('preserves the task notification destination after login', async () => {
    history.replaceState(null, '', '#/inbox/task-session')
    mock.api.mockRejectedValueOnce(new Error('UNAUTHORIZED'))
    render(<App />)
    fireEvent.click(await screen.findByText('Login'))
    await screen.findByText('Workspace')
    expect(location.hash).toBe('#/inbox/task-session')
  })

  it('ignores bootstrap completion after the application unmounts', async () => {
    const cluster = deferred()
    mock.bootstrap.mockReturnValueOnce(cluster.promise)
    const view = render(<App />)
    await waitFor(() => expect(mock.bootstrap).toHaveBeenCalledOnce())
    view.unmount()
    await act(async () => cluster.resolve())
    expect(mock.preferences).not.toHaveBeenCalled()
  })
})
