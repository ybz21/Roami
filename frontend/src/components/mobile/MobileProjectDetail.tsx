// 手机上一个项目的 worktree 视图（从项目分组标题进入）：
// 每张卡 = 分支 + 收尾状态 + 挂着的会话 + 在这个目录开 Claude / Codex / 终端；顶上「开任务」。
// 桌面项目页那套问候 / 行动卡 / 筛选 chips / 路径在手机上是硬缩，这里不复用。
import { lazy, Suspense, useEffect, useState } from 'react'
import { Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { AgentLogo, ChevronRight, DiffIcon, TerminalIcon } from '../../icons'
import AdaptivePanel from '../shell/AdaptivePanel'

const GitPanel = lazy(() => import('../git/GitPanel'))
import { BranchIcon } from '../git/parts'
import type { OverviewItem } from './MobileSessions'

type Wt = { path: string; branch: string; isMain: boolean; dirty: number; untracked: number; committedAhead: number; behind: number; mergedInto?: string; pushed?: boolean; sessions: { session: string; primary?: boolean; dormant?: boolean }[] | null }

export default function MobileProjectDetail({ dir, onOpenSession, onNewInWorktree }: {
  dir: string
  onOpenSession: (name: string) => void
  onNewInWorktree: (kind: 'claude' | 'codex' | 'shell', path: string) => void
}) {
  const { t } = useI18n()
  const [wts, setWts] = useState<Wt[] | null>(null)
  // worktree 接口只给会话名；名字 / agent / 活状态从 overview 补，和会话页同一份
  const [live, setLive] = useState<Map<string, OverviewItem>>(new Map())
  // 「改动」二级页：桌面右栏那个 Git 面板原样，手机档它自己会变成全屏二级页
  const [gitAt, setGitAt] = useState<string | null>(null)
  const [showQuiet, setShowQuiet] = useState(false)

  useEffect(() => {
    let stop = false
    setWts(null)
    // 后端 nil slice 序列化成 null，这里统一成空数组
    const loadWt = () => api('GET', `/git/worktrees?dir=${encodeURIComponent(dir)}`)
      .then((r) => { if (!stop) setWts((r.data || []).map((w: Wt) => ({ ...w, sessions: w.sessions || [] }))) })
      .catch(() => { if (!stop) setWts([]) })
    const loadLive = () => api('GET', '/sessions/overview')
      .then((r) => { if (!stop) setLive(new Map(((r.data.items || []) as OverviewItem[]).map((s) => [s.name, s]))) })
      .catch(() => {})
    loadWt(); loadLive()
    const i = setInterval(() => { loadWt(); loadLive() }, 5000)
    return () => { stop = true; clearInterval(i) }
  }, [dir])

  const wtStatus = (w: Wt) => {
    const parts: string[] = []
    if (w.mergedInto) parts.push(t('mobile.wt.merged'))
    else if (w.committedAhead > 0) parts.push(t('mobile.wt.ahead', { n: w.committedAhead }))
    if (w.dirty + w.untracked > 0) parts.push(t('mobile.wt.dirty', { n: w.dirty + w.untracked }))
    if (w.behind > 0) parts.push(t('mobile.wt.behind', { n: w.behind }))
    return parts.join(' · ') || t('mobile.wt.clean')
  }
  const status = (s: OverviewItem | undefined, dormant?: boolean) => {
    if (!s) return dormant ? t('mobile.st.dormant') : ''
    return s.dormant ? t('mobile.st.dormant') : s.waiting ? t('mobile.st.waiting') : s.running ? t('mobile.st.running') : t('mobile.st.idle')
  }
  const busy = (w: Wt) => (w.sessions || []).length > 0 || w.dirty + w.untracked > 0 || (w.committedAhead > 0 && !w.mergedInto)
  const all = wts || []
  const quiet = all.filter((w) => !busy(w) && !w.isMain)
  const rank = (w: Wt) => ((w.sessions || []).length ? 0 : busy(w) ? 1 : 2)
  const shown = [...all.filter((w) => busy(w) || w.isMain).sort((a, b) => rank(a) - rank(b)), ...(showQuiet ? quiet : [])]
  return (
    <div className="tt-mproj">
      {wts === null && <div style={{ display: 'grid', placeItems: 'center', padding: 40 }}><Spin /></div>}
      {shown.map((w) => (
        <div key={w.path} className="tt-mproj-wt">
          <div className="wn"><BranchIcon size={12} /><b>{w.isMain ? t('session.wt.mainRepo') : w.branch || w.path.split('/').pop()}</b><span>{wtStatus(w)}</span></div>
          {(w.sessions || []).map((s) => {
            const o = live.get(s.session)
            return (
              <button key={s.session} type="button" className={`tt-msess-row sub${o?.waiting ? ' wait' : ''}${s.dormant || o?.dormant ? ' dormant' : ''}`} onClick={() => onOpenSession(s.session)}>
                <span className="ic">{o?.agent ? <AgentLogo kind={o.agent} size={16} /> : <TerminalIcon size={16} />}</span>
                <span className="t"><b>{o?.label || s.session}</b><span className="st"><i>{status(o, s.dormant)}</i>{o && (o.waiting || o.running) && o.tail ? <span className="tail"> · {o.tail}</span> : null}</span></span>
                <ChevronRight size={14} />
              </button>
            )
          })}
          <div className="acts">
            <button type="button" className="tt-act" onClick={() => onNewInWorktree('claude', w.path)}><AgentLogo kind="claude" size={13} />Claude</button>
            <button type="button" className="tt-act" onClick={() => onNewInWorktree('codex', w.path)}><AgentLogo kind="codex" size={13} />Codex</button>
            <button type="button" className="tt-act" onClick={() => onNewInWorktree('shell', w.path)}><TerminalIcon size={13} />{t('tabs.newTerminal')}</button>
            {(w.dirty + w.untracked > 0 || w.committedAhead > 0) && <button type="button" className="tt-act" onClick={() => setGitAt(w.path)}><DiffIcon size={13} />{t('git.changes')}</button>}
          </div>
        </div>
      ))}
      {quiet.length > 0 && (
        <button type="button" className="tt-mproj-more" onClick={() => setShowQuiet((v) => !v)}>
          {showQuiet ? t('mobile.proj.hideQuiet') : t('mobile.proj.showQuiet', { n: quiet.length })}
        </button>
      )}
      {wts && !all.length && <div className="tt-msess-empty">{t('tree.noTasks')}</div>}
      <AdaptivePanel open={!!gitAt} title={t('git.changes')} onClose={() => setGitAt(null)}>
        <Suspense fallback={<div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>}>
          {gitAt && <GitPanel dir={gitAt} onClose={() => setGitAt(null)} />}
        </Suspense>
      </AdaptivePanel>
    </div>
  )
}
