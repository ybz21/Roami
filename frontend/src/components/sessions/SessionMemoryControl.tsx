import { useEffect, useRef, useState } from 'react'
import { App as AntApp, Button } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useSessionOverview } from '../../session-overview'
import { useCurrentNodeId } from '../cluster/node-url'
import { nativeSessionId } from './session-record'
import { refreshSessionLists } from './native-session-list'
import { humanBytes, memNoteworthy, memPercent, type SessionMem } from './session-memory'
import './session-memory-control.css'

export function SessionPauseButton({ name, mem, onChanged }: { name: string; mem?: SessionMem; onChanged?: () => void }) {
  const { t } = useI18n(), { message } = AntApp.useApp()
  const [busy, setBusy] = useState(false)
  if (nativeSessionId(name)) return null
  const act = async () => {
    setBusy(true)
    try {
      await api('POST', `/sessions/${encodeURIComponent(name)}/${mem?.paused ? 'resume' : 'pause'}`)
      refreshSessionLists()
      onChanged?.()
    } catch (error: any) {
      const code = error?.apiError?.code
      message.error(t(code === 'SESSION_PAUSE_SHARED_PANE' ? 'session.mem.sharedPane' : code === 'SESSION_PAUSE_UNAVAILABLE' ? 'session.mem.unavailable' : 'session.mem.actionFailed'))
    } finally { setBusy(false) }
  }
  return <button type="button" className="tt-act tt-session-pause" disabled={busy} onClick={e => { e.stopPropagation(); void act() }}>{t(mem?.paused ? 'session.mem.resume' : 'session.mem.pause')}</button>
}

export function SessionMemoryBanner({ name }: { name: string }) {
  const { t } = useI18n()
  const overview = useSessionOverview(!nativeSessionId(name))
  const mem = overview.value.find(s => s.name === name)?.mem
  if (!memNoteworthy(mem)) return null
  const usage = mem?.limit
    ? t('session.mem.tip', { cur: humanBytes(mem.cur), limit: humanBytes(mem.limit), pct: String(memPercent(mem)) })
    : t('session.mem.tipNoLimit', { cur: humanBytes(mem?.cur || 0) })
  return <div className="tt-session-memory" role="status">
    <span>{t(mem?.pauseError ? 'session.mem.notice.failed' : mem?.paused ? 'session.mem.notice.paused' : 'session.mem.notice.warning')} <b>{usage}</b></span>
    <SessionPauseButton name={name} mem={mem} />
  </div>
}

// Uses the existing shared overview subscription; no per-session requests.
export function SessionMemoryAlerts({ onOpen, visibleSession }: { onOpen: (name: string) => void; visibleSession?: string }) {
  const { t } = useI18n(), { notification } = AntApp.useApp()
  const overview = useSessionOverview(), node = useCurrentNodeId()
  const seen = useRef(new Map<string, string>())
  useEffect(() => {
    if (!overview.loaded || overview.failed) return
    const alive = new Set<string>()
    for (const s of overview.value) {
      const key = `session-memory:${node || 'local'}:${s.name}`
      alive.add(key)
      const level = s.mem?.pauseError ? 'failed' : s.mem?.paused ? 'paused' : s.mem?.warning ? 'warning' : ''
      if (s.name === visibleSession) { notification.destroy(key); seen.current.set(key, level); continue }
      if (seen.current.get(key) === level) continue
      seen.current.set(key, level)
      if (!level) { notification.destroy(key); continue }
      notification.warning({ key, duration: 0, message: s.label,
        description: t('session.mem.notice.' + level),
        btn: <Button onClick={() => { notification.destroy(key); onOpen(s.name) }}>{t('session.mem.open')}</Button>,
      })
    }
    for (const key of seen.current.keys()) if (!alive.has(key)) { notification.destroy(key); seen.current.delete(key) }
  }, [overview.value, overview.loaded, overview.failed, node, notification, t, onOpen, visibleSession])
  return null
}
