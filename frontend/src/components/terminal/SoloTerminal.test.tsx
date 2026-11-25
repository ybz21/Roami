// @vitest-environment jsdom
import { App as AntApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { WorkspaceStateProvider } from '../../view-state'
import { setSessionLabels } from '../sessions/session-label'
import { setSessionProjects } from '../sessions/session-project'
import { resetInspector } from '../shell/inspector'
import SoloTerminal from './SoloTerminal'

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  layout: { size: 'large' as 'large' | 'expanded' | 'compact', phone: false, desktop: true, coarse: false, orient: 'landscape' as const, keyboard: 0 },
  inspectorCollapsed: false,
  setInspectorCollapsed: vi.fn(),
  openPalette: vi.fn(),
}))

vi.mock('../../api', () => ({
  api: mocks.api,
  makeClipboardImageFile: vi.fn(),
  upload: vi.fn(),
  uploadedPathOf: vi.fn(),
}))
vi.mock('../../layout', () => ({ useLayout: () => mocks.layout }))
vi.mock('../../agent-kind', () => ({
  useAgentKindInventory: () => ({ value: { kinds: { '2026-1123-1751-2r6z': 'antigravity' }, alternatives: {} }, loaded: true, failed: false }),
  agentName: (kind: string) => kind,
}))
vi.mock('../../agent-registry', () => ({ useRegisteredAgents: () => [] }))
vi.mock('../../app/useTerminalRuntime', () => ({
  useTerminalRuntime: () => ({
    fontSize: 13,
    setFontSize: vi.fn(),
    statusMap: { '2026-1123-1751-2r6z': 'connected' },
    setStatus: vi.fn(),
    activityMap: {},
    termRefs: { current: {} },
    claudeMap: {},
    claudeView: {},
    setClaudeView: vi.fn(),
    codexMap: {},
    codexView: {},
    setCodexView: vi.fn(),
    openCodeMap: {},
    openCodeView: {},
    setOpenCodeView: vi.fn(),
    rename: vi.fn(),
  }),
}))
vi.mock('../../app/useBrowserEnvironment', () => ({
  useBrowserEnvironment: () => ({ online: true, offline: false, roamVersion: '1.0.0', isFs: false, fsSupported: true, toggleFs: vi.fn() }),
}))
vi.mock('../sessions/native-session-list', () => ({
  useNativeSessionList: () => ({ value: [], loaded: true }),
  refreshSessionLists: vi.fn(),
}))
vi.mock('../sessions/session-lifecycle', () => ({
  useSessionLifecycle: () => ({ value: [] }),
  blockingLifecycle: () => null,
}))
vi.mock('../sessions/SessionMemoryControl', () => ({
  SessionMemoryAlerts: () => null,
  SessionMemoryBanner: () => null,
}))
vi.mock('../sessions/SessionReviewStatus', () => ({ default: () => null }))
vi.mock('../shell/palette', () => ({
  GlobalSearch: () => null,
  openPalette: mocks.openPalette,
}))
vi.mock('../shell/useWorkspaceLayout', () => ({
  useWorkspaceLayout: () => ({
    mode: 'focus',
    dockVisible: true,
    focus: 'none',
    navCollapsed: false,
    large: mocks.layout.size === 'large',
    overlayCapable: false,
    toggleDock: vi.fn(),
    setDockOpen: vi.fn(),
    setFocus: vi.fn(),
    toggleFocus: vi.fn(),
    setNavCollapsed: vi.fn(),
    inspectorWidth: 350,
    inspectorBounds: { min: 280, max: 1200 },
    setInspectorWidth: vi.fn(),
    resetInspectorWidth: vi.fn(),
    canvasFitsInspector: true,
    inspectorCollapsed: mocks.inspectorCollapsed,
    setInspectorCollapsed: mocks.setInspectorCollapsed,
    toggleInspectorCollapsed: vi.fn(),
  }),
}))
vi.mock('../shell/InspectorPanels', () => ({
  InspectorPanels: ({ open, dir, scope, onOpenFile }: any) => open ? (
    <div data-testid="solo-inspector" data-dir={dir} data-scope={scope}>
      <button type="button" onClick={() => onOpenFile?.('/repo/.worktrees/task-a/acceptance.md')}>open-file</button>
    </div>
  ) : null,
}))
vi.mock('./Terminal', async () => {
  const { forwardRef } = await import('react')
  return {
    default: forwardRef(function MockTerm() { return <div data-testid="xterm-canvas" /> }),
  }
})
vi.mock('../files/fileview', () => ({
  FileView: ({ path }: { path: string }) => <div data-testid="solo-file-view">{path}</div>,
}))
vi.mock('../chat/VoiceInput', () => ({ VoiceInput: () => null }))
vi.mock('../prompt', () => ({ PromptDialog: () => null }))
vi.mock('../cluster/node-url', () => ({
  currentNodeId: () => '',
  useCurrentNodeId: () => '',
  nodeApi: (path: string) => `/api${path}`,
}))
vi.mock('../../preferences', () => ({
  usePreferences: () => [{ workspace: { dpadOn: false, dpadSide: 'right', dpadHintSeen: true }, keybindings: {} }],
  savePreferences: vi.fn(),
  saveWorkspace: vi.fn(),
}))

function renderSolo(name = '2026-1123-1751-2r6z') {
  return render(
    <I18nProvider>
      <AntApp>
        <WorkspaceStateProvider>
          <SoloTerminal name={name} />
        </WorkspaceStateProvider>
      </AntApp>
    </I18nProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('ttmux-locale', 'zh-CN')
  history.replaceState(null, '', '#/term/2026-1123-1751-2r6z')
  setSessionLabels({})
  setSessionProjects({})
  resetInspector()
  mocks.inspectorCollapsed = false
  mocks.layout.size = 'large'
  mocks.layout.phone = false
  mocks.layout.desktop = true
  mocks.layout.coarse = false
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addListener: vi.fn(), removeListener: vi.fn() }))
  mocks.api.mockImplementation((_method: string, path: string) => {
    if (path === '/sessions') {
      return Promise.resolve([{ name: '2026-1123-1751-2r6z', label: '原生终端选型-antigravity' }])
    }
    if (path === '/projects') {
      return Promise.resolve({ data: { projects: [{ key: 'roami', name: 'Roami', dir: '/repo', git: true }] } })
    }
    if (path === '/sessions/annotations') {
      return Promise.resolve({
        data: { '2026-1123-1751-2r6z': { primary: { repo: '/repo', worktree: '/repo/.worktrees/task-a', branch: 'feat/demo' } } },
      })
    }
    if (path.endsWith('/cwd')) {
      return Promise.resolve({ data: { dir: '/repo/.worktrees/task-a' } })
    }
    return Promise.resolve({ data: {} })
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('SoloTerminal', () => {
  it('uses the main workspace tab bar, session label/project hydration, file path bar, and right inspector on desktop', async () => {
    const { container } = renderSolo()

    await waitFor(() => {
      expect(container.querySelector('.tt-global-tabs .tt-tabs-wrap')).not.toBeNull()
      expect(screen.getByTestId('solo-inspector').getAttribute('data-scope')).toBe('Roami · 原生终端选型-antigravity')
      expect(screen.getByTestId('solo-inspector').getAttribute('data-dir')).toBe('/repo/.worktrees/task-a')
    })

    const brand = container.querySelector<HTMLAnchorElement>('.tt-solo-brand')
    expect(brand?.getAttribute('href')).toBe('#/home')
    expect(container.querySelector('.tt-session-toolbar')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    expect(mocks.openPalette).toHaveBeenCalledOnce()

    fireEvent.click(screen.getByRole('button', { name: '右栏' }))
    expect(mocks.setInspectorCollapsed).toHaveBeenCalledWith(true)

    fireEvent.click(screen.getByRole('button', { name: 'open-file' }))
    await waitFor(() => {
      expect(screen.getByTestId('solo-file-view').textContent).toBe('/repo/.worktrees/task-a/acceptance.md')
      expect(container.querySelector('.tt-pathbar')).not.toBeNull()
    })

    fireEvent.click(screen.getByRole('button', { name: '返回来源会话' }))
    await waitFor(() => {
      expect(container.querySelector('.tt-pathbar')).toBeNull()
      expect(container.querySelector('.tt-session-toolbar')).not.toBeNull()
    })
  })

  it('uses the mobile session header without desktop inspector on phones', async () => {
    mocks.layout.size = 'compact'
    mocks.layout.phone = true
    mocks.layout.desktop = false
    mocks.layout.coarse = true

    const { container } = renderSolo()

    await waitFor(() => {
      expect(container.querySelector('.tt-sesshead')).not.toBeNull()
    })
    expect(screen.queryByTestId('solo-inspector')).toBeNull()
    expect(container.querySelector('.tt-solo-brand')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(location.hash).toBe('#/home')
  })
})
