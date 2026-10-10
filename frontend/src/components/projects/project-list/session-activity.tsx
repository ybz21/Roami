import { useEffect, useState } from 'react'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { relTime } from '../../../time-format'
import { CheckIcon, CloseIcon } from '../../../icons'

type Activity = { id: number; type: string; session: string; label: string; body: string; at: number; read: boolean }

export function SessionActivity({ onOpenSession, showEmpty = false }: { onOpenSession: (name: string) => void; showEmpty?: boolean }) {
  const { t } = useI18n()
  const [items, setItems] = useState<Activity[]>([])
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let stopped = false
    const load = () => api('GET', '/inbox?limit=40').then((r) => {
      if (!stopped) {
        setItems((r.data.items || []).filter((it: Activity) => it.type === 'session.done' || it.type === 'session.error').slice(0, 6))
        setLoaded(true)
      }
    }).catch(() => { if (!stopped) setLoaded(true) })
    void load()
    const timer = setInterval(load, 20000)
    return () => { stopped = true; clearInterval(timer) }
  }, [])
  if (!items.length) return showEmpty ? <div className="prj-session-empty">{t(loaded ? 'project.noActivity' : 'common.loading')}</div> : null
  const open = (item: Activity) => {
    if (!item.read) {
      setItems((prev) => prev.map((it) => it.id === item.id ? { ...it, read: true } : it))
      void api('POST', '/inbox/read', { ids: [item.id] }).catch(() => {})
    }
    onOpenSession(item.session)
  }
  return <section className="prj-session-activity" aria-label={t('project.sessionActivity')}>
    <h3>{t('project.sessionActivity')}</h3>
    <div className="prj-session-events">{items.map((item) => <button key={item.id} type="button" className={`prj-session-event ${item.type === 'session.error' ? 'error' : 'done'}`} onClick={() => open(item)}>
      <span className="icon">{item.type === 'session.error' ? <CloseIcon size={16} /> : <CheckIcon size={16} />}</span>
      <span className="content"><b>{item.label || item.session}</b><span>{item.body || t('inbox.noSummary')}</span></span>
      <time>{relTime(item.at, t)}</time>
    </button>)}</div>
  </section>
}

export const SESSION_ACTIVITY_CSS = `
.prj-session-activity{min-width:0;padding:var(--sp-3);border-radius:var(--r-card);background:var(--bg-container)}
.prj-session-activity h3{margin:0 0 var(--sp-2);font-size:var(--fs-sm);font-weight:600;color:var(--text-bright)}
.prj-session-events{display:flex;flex-direction:column}
.prj-session-event{display:flex;align-items:flex-start;gap:var(--sp-2);width:100%;min-width:0;padding:var(--sp-2) 0;border:0;border-top:1px solid var(--border-subtle);background:transparent;color:var(--text-dim);font:inherit;text-align:left;cursor:pointer}
:where(html[data-pointer="fine"]) .prj-session-event:hover{color:var(--text-bright);background:var(--list-hover)}
.prj-session-event .icon{flex:0 0 auto;color:var(--ok)}
.prj-session-event.error .icon{color:var(--danger)}
.prj-session-event .content{display:flex;flex:1;min-width:0;flex-direction:column;gap:var(--sp-1)}
.prj-session-event b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-bright);font-size:var(--fs-sm)}
.prj-session-event .content span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs-meta)}
.prj-session-event time{flex:0 0 auto;color:var(--text-dimmer);font-size:var(--fs-micro)}
html[data-pointer="coarse"] .prj-session-event{min-height:var(--tap);padding:var(--sp-3) 0}
html[data-size="compact"] .prj-session-activity{margin:var(--sp-3) var(--pad-page) var(--sp-4);padding:0;background:transparent}
.prj-session-empty{padding:var(--sp-5) var(--pad-page);color:var(--text-dim);font-size:var(--fs-sm);text-align:center}
`
