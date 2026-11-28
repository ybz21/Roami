import { usePageEffect } from '../../page-activity'
import { useRegisteredAgents } from '../../agent-registry'
// 手机上一个项目的 worktree 视图（从项目分组标题进入）：
// 每张卡 = 分支 + 收尾状态 + 挂着的会话 + 在这个目录开 Claude / Codex / 终端；顶上「开任务」。
// 桌面项目页那套问候 / 行动卡 / 筛选 chips / 路径在手机上是硬缩，这里不复用。
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { App as AntApp, Spin } from 'antd'
import { getHashParams } from '../../route-hash'
import { projectPath, projectSwarmPath } from '../projects/okr/okr-workspace'
import type { ProjectSwarm } from '../projects/okr/okr-directory'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { AgentLogo, ChevronRight, DiffIcon, FolderIcon, SwarmIcon, TargetIcon, TerminalIcon, TrashIcon } from '../../icons'
import { currentNodeId, useCurrentNodeId } from '../cluster/node-url'
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

type Wt = { path: string; branch: string; isMain: boolean; directoryOnly?: boolean; dirty: number; untracked: number; committedAhead: number; behind: number; mergedInto?: string; locked?: boolean; prunable?: boolean; sessions: { session: string; primary?: boolean; dormant?: boolean }[] | null }

const canRemove = (w: Wt) => !!w.branch && !w.isMain && !w.directoryOnly && !w.locked && !w.prunable && !w.sessions?.length

export default function MobileProjectDetail({ projectId, dir, swarm, onOpenSession, onNewInWorktree }: {
  projectId?: string
  swarm?: ProjectSwarm
  dir: string
  onOpenSession: (name: string) => void
  onNewInWorktree: (kind: string, path: string) => void
}) {
  const agents = useRegisteredAgents()
  const { t } = useI18n()
  const { message, modal } = AntApp.useApp()
  const node = useCurrentNodeId()
  const [loaded, setLoaded] = useState<{ dir: string; node: typeof node; worktrees: Wt[] } | null>(null)
  const wts = loaded?.dir === dir && loaded.node === node ? loaded.worktrees : null
  const [revision, setRevision] = useState(0)
  const confirmation = useRef<ReturnType<typeof modal.confirm>>()
  // worktree 接口只给会话名；名字 / agent / 活状态从 overview 补，和会话页同一份
  const overview = useSessionOverview(), native = useNativeSessionList()
  const owned = useMemo(() => native.value.filter(session => (projectId ? session.projectId === projectId : session.directory === dir)).map(nativeSessionRecord), [native.value, projectId, dir])
  const live = useMemo(() => new Map<string, OverviewItem>([...overview.value, ...owned].map(session => [session.name, session])), [overview.value, owned])
  // 「改动」二级页：桌面右栏那个 Git 面板原样，手机档它自己会变成全屏二级页
  const [gitAt, setGitAt] = useState<string | null>(null)
  const [showQuiet, setShowQuiet] = useState(false)

  useEffect(() => () => confirmation.current?.destroy(), [dir, node])

  usePageEffect(() => {
    const loadWt = async (signal: AbortSignal) => {
      try {
        const { data } = await api('GET', `/git/worktrees?dir=${encodeURIComponent(dir)}`, undefined, { signal })
        if (!signal.aborted) setLoaded({ dir, node, worktrees: data ?? [] })
      } catch (error) {
        if (!signal.aborted) setLoaded(current => current?.dir === dir && current.node === node ? current : { dir, node, worktrees: [] })
        throw error
      }
    }
    const poll = pollWhileVisible(loadWt, 5000)
    return () => poll.stop()
  }, [dir, node, revision])

  const removeWorktree = (w: Wt) => {
    const forceWorktree = w.dirty + w.untracked > 0
    confirmation.current = modal.confirm({
      wrapClassName: 'tt-mproj-remove',
      title: t('mobile.wt.deleteTitle', { branch: w.branch }),
      content: t(forceWorktree ? 'mobile.wt.deleteDirtyDesc' : 'mobile.wt.deleteDesc'),
      okText: t('project.wt.delete'),
      cancelText: t('common.cancel'),
      okButtonProps: { danger: true },
      autoFocusButton: 'cancel',
      onOk: async () => {
        if (currentNodeId() !== node) return
        try {
          await api('POST', '/git/worktree/remove', { path: w.path, forceWorktree })
          setLoaded(current => current?.dir === dir && current.node === node ? { ...current, worktrees: current.worktrees.filter(item => item.path !== w.path) } : current)
          message.success(t('project.wt.deleted'))
        } catch (error) {
          const detail = (error as { apiError?: { code?: string; sessions?: string[] } })?.apiError
          if (detail?.code === 'SESSIONS_INSIDE') {
            message.error(t('worktree.sessionsInsideDesc', { sessions: detail.sessions?.join(', ') || '' }))
          } else {
            message.error(t(detail?.code === 'WORKTREE_DIRTY' ? 'mobile.wt.deleteChanged' : 'mobile.wt.deleteFailed'))
          }
        } finally {
          setRevision(value => value + 1)
        }
      },
    })
  }

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
    if (s.review?.role === 'reviewer') return t(`session.review.phase.${s.review.phase}`)
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
  const query = getHashParams().toString()
  return (
    <div className="tt-mproj">
      {projectId && <a className="tt-msess-row" href={'#/' + projectPath(projectId, true) + (query ? '?' + query : '')}><span className="ic"><TargetIcon /></span><span className="t"><b>{t('okr.title')}</b></span><ChevronRight /></a>}
      {swarm && <a className="tt-msess-row" href={'#/' + projectSwarmPath(swarm.projectId) + (query ? '?' + query : '')}><span className="ic"><SwarmIcon /></span><span className="t"><b>{t('nav.swarm')}</b></span><ChevronRight /></a>}
      {wts === null && <div style={{ display: 'grid', placeItems: 'center', padding: 40 }}><Spin /></div>}
      {shown.map((w) => (
        <div key={w.path} className="tt-mproj-wt">
          <div className="wn">{w.directoryOnly ? <FolderIcon size={12} /> : <BranchIcon size={12} />}<b>{w.isMain ? t('session.wt.mainRepo') : w.branch || w.path.split('/').pop() || t('tree.loose')}</b>{w.isMain && w.branch && <span>{w.branch}</span>}{!w.directoryOnly && <span>{wtStatus(w)}</span>}</div>
          {w.path && <SessionLocation cwd={w.path} />}
          <SessionHierarchy sessions={(w.sessions || []).filter(s => !swarm?.sessionIds.includes(s.session)).map(s => ({ ...s, name: s.session, label: live.get(s.session)?.label, parent: live.get(s.session)?.parent }))} allSessions={[...live.values()]} renderRow={s => {
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
            {canRemove(w) && <button type="button" className="tt-act danger" onClick={() => removeWorktree(w)}><TrashIcon size={13} />{t('project.wt.delete')}</button>}
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
