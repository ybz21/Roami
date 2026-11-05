import type { ReactNode } from 'react'
import { useI18n } from '../../i18n'
import { sessionLineage } from '../shell/session-lineage'

type LinkedSession = { name: string; label?: string; parent?: string }

export default function SessionHierarchy<S extends LinkedSession>({ sessions, allSessions = sessions, limit, renderRow }: {
  sessions: S[]; allSessions?: LinkedSession[]; limit?: number; renderRow: (session: S, index: number) => ReactNode
}) {
  const { t } = useI18n()
  const visible = new Set(sessions.map(session => session.name))
  const labels = new Map(allSessions.map(session => [session.name, session.label || session.name]))
  return <>{sessionLineage(sessions).slice(0, limit).map(({ session, depth }, index) => {
    const row = renderRow(session, index)
    if (row == null) return null
    const parent = session.parent && !visible.has(session.parent) && labels.get(session.parent)
    return <div key={session.name} className={`tt-session-lineage${depth ? ' child' : ''}`} data-depth={depth}
      style={{ marginInlineStart: `calc(var(--sp-3) * ${Math.min(depth, 3)})` }}>
      {parent && <span className="tt-session-parent">{t('session.fork.childOf', { parent })}</span>}
      {row}
    </div>
  })}</>
}
