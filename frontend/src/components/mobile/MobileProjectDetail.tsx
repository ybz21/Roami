import { useRegisteredAgents } from '../../agent-registry'
// 手机上一个项目的 worktree 视图（从项目分组标题进入）：
// 每张卡 = 分支 + 收尾状态 + 挂着的会话 + 在这个目录开 Claude / Codex / 终端；顶上「开任务」。
// 桌面项目页那套问候 / 行动卡 / 筛选 chips / 路径在手机上是硬缩，这里不复用。
import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Spin } from 'antd'
import { getHashParams } from '../../route-hash'
import { projectPath } from '../projects/okr/okr-workspace'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { AgentLogo, ChevronRight, DiffIcon, FolderIcon, TargetIcon, TerminalIcon } from '../../icons'
import AdaptivePanel from '../shell/AdaptivePanel'
import { useNativeSessionList } from '../sessions/native-session-list'
import { nativeSessionRecord } from '../sessions/session-record'
import { useSessionOverview } from '../../session-overview'
import { pollWhileVisible } from '../../visible-poll'
import SessionHierarchy from '../sessions/SessionHierarchy'
import SessionLocation from '../sessions/SessionLocation'
import { absTime, relTime } from '../../time-format'

const GitPanel = lazy(() => import('../git/GitPanel'))
import { BranchIcon } from '../git/parts'
import type { OverviewItem } from './MobileSessions'

type Wt = { path: string; branch: string; isMain: boolean; directoryOnly?: boolean; dirty: number; untracked: number; committedAhead: number; behind: number; mergedInto?: string; pushed?: boolean; sessions: { session: string; primary?: boolean; dormant?: boolean }[] | null }

export default function MobileProjectDetail({ projectId, dir, onOpenSession, onNewInWorktree }: {
  projectId?: string
  dir: string
  onOpenSession: (name: string) => void
  onNewInWorktree: (kind: string, path: string) => void
}) {
  const agents = useRegisteredAgents()
  const { t } = useI18n()
  const [wts, setWts] = useState<Wt[] | null>(null)
  // worktree 接口只给会话名；名字 / agent / 活状态从 overview 补，和会话页同一份
  const overview = useSessionOverview(), native = useNativeSessionList()
  const owned = useMemo(() => native.value.filter(session => (projectId ? session.projectId === projectId : session.directory === dir)).map(nativeSessionRecord), [native.value, projectId, dir])
  const live = useMemo(() => new Map<string, OverviewItem>([...overview.value, ...owned].map(session => [session.name, session])), [overview.value, owned])
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
    const poll = pollWhileVisible(loadWt, 5000)
    return () => { stop = true; poll.stop() }
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
  const all = useMemo(() => {
    const groups = (wts || []).map(worktree => ({ ...worktree, sessions: [...worktree.sessions || []] }))
    const sessions: OverviewItem[] = [...overview.value.filter(session => projectId ? session.projectKey === projectId : session.projectDir === dir), ...owned]
    for (const session of sessions) {
      if (groups.some(group => group.sessions.some(item => item.session === session.name))) continue
      const directory = session.worktree || session.cwd || ''
      let group = groups.find(worktree => worktree.path === directory)
      if (!group) { group = { path: directory, branch: session.branch || '', isMain: directory === dir, directoryOnly: true, dirty: 0, untracked: 0, committedAhead: 0, behind: 0, sessions: [] }; groups.push(group) }
      if (!group.sessions.some(item => item.session === session.name)) group.sessions.push({ session: session.name })
    }
    return groups
  }, [wts, overview.value, owned, dir, projectId])
  const quiet = all.filter((w) => !busy(w) && !w.isMain)
  const rank = (w: Wt) => ((w.sessions || []).length ? 0 : busy(w) ? 1 : 2)
  const shown = [...all.filter((w) => busy(w) || w.isMain).sort((a, b) => rank(a) - rank(b)), ...(showQuiet ? quiet : [])]
  return (
    <div className="tt-mproj">
      {projectId && <a className="tt-msess-row" href={'#/' + projectPath(projectId, true) + (getHashParams().toString() ? '?' + getHashParams().toString() : '')}><span className="ic"><TargetIcon /></span><span className="t"><b>{t('okr.title')}</b></span><ChevronRight /></a>}
      {wts === null && <div style={{ display: 'grid', placeItems: 'center', padding: 40 }}><Spin /></div>}
      {shown.map((w) => (
        <div key={w.path} className="tt-mproj-wt">
          <div className="wn">{w.directoryOnly ? <FolderIcon size={12} /> : <BranchIcon size={12} />}<b>{w.isMain ? t('session.wt.mainRepo') : w.branch || w.path.split('/').pop() || t('tree.loose')}</b>{w.isMain && w.branch && <span>{w.branch}</span>}{!w.directoryOnly && <span>{wtStatus(w)}</span>}</div>
          {w.path && <SessionLocation cwd={w.path} />}
          <SessionHierarchy sessions={(w.sessions || []).map(s => ({ ...s, name: s.session, label: live.get(s.session)?.label, parent: live.get(s.session)?.parent }))} allSessions={[...live.values()]} renderRow={s => {
            const o = live.get(s.name)
            return (
              <button key={s.session} type="button" className={`tt-msess-row sub${o?.waiting ? ' wait' : ''}${s.dormant || o?.dormant ? ' dormant' : ''}`} onClick={() => onOpenSession(s.session)}>
                <span className="ic">{o?.agent ? <AgentLogo kind={o.agent} size={16} /> : <TerminalIcon size={16} />}</span>
                <span className="t"><b>{o?.label || s.session}</b><span className="st"><i>{status(o, s.dormant)}</i>{o && (o.waiting || o.running) && o.tail ? <span className="tail"> · {o.tail}</span> : null}</span></span>
                <em title={absTime(o?.lastActivity)}>{relTime(o?.lastActivity, t)}</em><ChevronRight size={14} />
              </button>
            )
          }} />
          {w.path && <div className="acts">
            {agents.map(agent => <button key={agent.kind} type="button" className="tt-act" disabled={!agent.interactive} onClick={() => onNewInWorktree(agent.kind, w.path)}><AgentLogo kind={agent.kind} size={13} />{agent.interactive ? agent.displayName : t('capabilities.agents.taskOnly', { name: agent.displayName })}</button>)}
            <button type="button" className="tt-act" onClick={() => onNewInWorktree('shell', w.path)}><TerminalIcon size={13} />{t('tabs.newTerminal')}</button>
            {(w.dirty + w.untracked > 0 || w.committedAhead > 0) && <button type="button" className="tt-act" onClick={() => setGitAt(w.path)}><DiffIcon size={13} />{t('git.changes')}</button>}
          </div>}
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
