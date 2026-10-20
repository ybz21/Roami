import { useCallback, useEffect, useState } from 'react'
import { api, setUnauthorizedHandler } from '../api'
import { bootstrapCluster } from '../components/cluster/node-url'
import { loadPreferences } from '../preferences'

export function useAppBootstrap() {
  const [authed, setAuthed] = useState<boolean | null>(null)
  const onLogin = useCallback(async () => {
    await bootstrapCluster()
    setAuthed(true)
    void loadPreferences()
  }, [])

  useEffect(() => {
    let alive = true
    setUnauthorizedHandler(() => { if (alive) setAuthed(false) })
    void (async () => {
      try { await api('GET', '/me') }
      catch { if (alive) setAuthed(false); return }
      // Business requests need the node prefix established by bootstrap.
      await bootstrapCluster()
      if (!alive) return
      setAuthed(true)
      void loadPreferences()
      navigator.clipboard?.readText?.().catch(() => { })
    })()
    return () => { alive = false; setUnauthorizedHandler(() => { }) }
  }, [])

  const logout = () => { void api('POST', '/logout').catch(() => { }).finally(() => setAuthed(false)) }
  return { authed, onLogin, logout }
}
