import { Spin } from 'antd'
import { Suspense } from 'react'
import Login from './components/auth/Login'
import SoloTerminal from './components/terminal/SoloTerminal'
import AppShell from './app/AppShell'
import { useAppBootstrap } from './app/useAppBootstrap'
import { useAppRoute } from './app/useAppRoute'
import { WorkspaceStateProvider } from './view-state'
import { lazyRetry } from './components/lazy-retry'
import { readArtifactPreviewRoute } from './components/agent/artifact-preview-route'

const ArtifactPreviewPage = lazyRetry(() => import('./components/agent/ArtifactPreviewPage'))

export default function App() {
  const { authed, onLogin, logout } = useAppBootstrap()
  const routing = useAppRoute()

  if (authed === null) return <div style={{ height: '100dvh', display: 'grid', placeItems: 'center' }}><Spin size="large" /></div>
  if (!authed) return <Login onOk={async () => { await onLogin() }} />
  const artifactRoute = readArtifactPreviewRoute(location.hash)
  if (artifactRoute) return <Suspense fallback={<Spin />}><ArtifactPreviewPage key={artifactRoute.node + ':' + artifactRoute.id} route={artifactRoute} /></Suspense>
  if (routing.soloName) return <WorkspaceStateProvider><SoloTerminal name={routing.soloName} /></WorkspaceStateProvider>
  return <AppShell routing={routing} logout={logout} />
}
