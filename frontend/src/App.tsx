import { Spin } from 'antd'
import Login from './components/auth/Login'
import SoloTerminal from './components/terminal/SoloTerminal'
import AppShell from './app/AppShell'
import { useAppBootstrap } from './app/useAppBootstrap'
import { useAppRoute } from './app/useAppRoute'

export default function App() {
  const { authed, onLogin, logout } = useAppBootstrap()
  const routing = useAppRoute()

  if (authed === null) return <div style={{ height: '100dvh', display: 'grid', placeItems: 'center' }}><Spin size="large" /></div>
  if (!authed) return <Login onOk={async () => { await onLogin(); routing.go('projects') }} />
  if (routing.soloName) return <SoloTerminal name={routing.soloName} />
  return <AppShell routing={routing} logout={logout} />
}
