import { usePageEffect } from '../../page-activity'
import { useRef, useState } from 'react'
import { App as AntApp, Drawer, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { pollWhileVisible } from '../../visible-poll'
import { useCurrentNodeId } from '../cluster/node-url'
import MobileSubPage from '../MobileSubPage'
import { humanBytes } from './session-memory'
import { refreshSessionLists } from './native-session-list'
import './session-processes.css'

export type SessionProcess = {
  pid: number; ppid: number; name: string; command: string; state: string
  rss: number; swap: number; start: string; protected: boolean
}

export function processTree(processes: SessionProcess[]) {
  const byParent = new Map<number, SessionProcess[]>(), ids = new Set(processes.map(p => p.pid))
  for (const p of processes) {
    const parent = ids.has(p.ppid) ? p.ppid : 0
    byParent.set(parent, [...(byParent.get(parent) || []), p])
  }
  const rows: { process: SessionProcess; depth: number }[] = [], seen = new Set<number>()
  const visit = (p: SessionProcess, depth: number) => {
    if (seen.has(p.pid)) return
    seen.add(p.pid); rows.push({ process: p, depth })
    for (const child of (byParent.get(p.pid) || []).sort((a, b) => b.rss - a.rss)) visit(child, depth + 1)
  }
  for (const root of (byParent.get(0) || []).sort((a, b) => b.rss - a.rss)) visit(root, 0)
  for (const p of processes) visit(p, 0)
  return rows
}

export function SessionProcesses({ name, onClose }: { name: string; onClose: () => void }) {
  const { t, locale } = useI18n(), { phone } = useLayout(), { modal, message } = AntApp.useApp()
  const node = useCurrentNodeId()
  const [processes, setProcesses] = useState<SessionProcess[]>([])
  const [loaded, setLoaded] = useState(false), [error, setError] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const confirmation = useRef<ReturnType<typeof modal.confirm> | null>(null)
  const refresh = useRef<() => Promise<unknown>>(async () => {})
  usePageEffect(() => {
    setProcesses([]); setLoaded(false); setError(false)
    const poll = pollWhileVisible(async signal => {
      try {
        const result = await api('GET', `/sessions/${encodeURIComponent(name)}/processes`, undefined, { signal })
        if (!signal.aborted) { setProcesses(result.processes); setLoaded(true); setError(false) }
      } catch (err) {
        if (!signal.aborted) { setError(true); setLoaded(true) }
        throw err
      }
    }, 5000)
    refresh.current = poll.refresh
    return () => { confirmation.current?.destroy(); poll.stop(); refresh.current = async () => {} }
  }, [name, node])
  const stop = (p: SessionProcess, force: boolean) => { confirmation.current = modal.confirm({
    title: t(force ? 'session.process.forceTitle' : 'session.process.stopTitle', { name: p.name, pid: String(p.pid) }),
    content: t(force ? 'session.process.forceHint' : 'session.process.stopHint'),
    okText: t(force ? 'session.process.force' : 'session.process.stop'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
    onOk: async () => {
      setBusy(p.pid)
      try {
        await api('POST', `/sessions/${encodeURIComponent(name)}/processes/${p.pid}/stop`, { start: p.start, force })
        message.success(t('session.process.signalled'))
        await refresh.current(); refreshSessionLists()
      } catch (err: any) {
        message.error(t(err?.apiError?.code === 'SESSION_PROCESS_STALE' ? 'session.process.stale' : 'session.process.stopFailed'))
        await refresh.current()
      } finally { setBusy(null) }
    },
  }) }
  const content = <div className="tt-session-processes">
    <p className="tt-process-note">{t('session.process.memoryHint')}</p>
    {error && <div role="alert" className="tt-process-error">{t('session.process.loadFailed')} <button type="button" className="tt-act" onClick={() => void refresh.current()}>{t('session.process.retry')}</button></div>}
    {!loaded ? <Spin /> : !error && processes.length === 0 ? <p>{t('session.process.empty')}</p> : null}
    <div role="list" aria-label={t('session.process.title')}>
      {processTree(processes).map(({ process: p, depth }) => <div className="tt-process-row" role="listitem" key={`${p.pid}:${p.start}`} style={{ paddingInlineStart: `calc(var(--sp-4) + var(--sp-3) * ${Math.min(depth, 6)})` }}>
        <div className="tt-process-identity"><strong>{p.name}</strong><span>{t('session.process.pid', { pid: new Intl.NumberFormat(locale, { useGrouping: false }).format(p.pid), parent: String(p.ppid) })}</span></div>
        <div className="tt-process-memory"><span>{t('session.process.rss', { bytes: humanBytes(p.rss) })}</span>{p.swap > 0 && <span>{t('session.process.swap', { bytes: humanBytes(p.swap) })}</span>}</div>
        <div className="tt-process-actions">{p.protected ? <span>{t('session.process.protected')}</span> : <>
          <button type="button" className="tt-act danger" disabled={busy !== null || error} onClick={() => stop(p, false)}>{t('session.process.stop')}</button>
          <button type="button" className="tt-act danger" disabled={busy !== null || error} onClick={() => stop(p, true)}>{t('session.process.force')}</button>
        </>}</div>
        <details><summary>{t('session.process.details')}</summary><pre>{p.command || p.name}</pre><span>{t('session.process.state', { state: p.state })}</span></details>
      </div>)}
    </div>
  </div>
  return phone
    ? <MobileSubPage title={t('session.process.title')} layer="session" search={false} onBack={onClose}>{content}</MobileSubPage>
    : <Drawer open title={t('session.process.title')} onClose={onClose} width="min(100%, calc(var(--sp-5) * 40))" styles={{ body: { padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' } }}>{content}</Drawer>
}
