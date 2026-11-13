import { usePageEffect } from '../../page-activity'
// Worktree 管理抽屉（W4，设计见 docs/design/web/07-worktree.md §3 + w4 图纸）
// 列出仓库全部 worktree（5s 轮询）：四态徽章、有货着色、筛选、对比 base、
// 进入会话（孤儿复活）、合并回 base（squash/merge/rebase）、
// 删除（先列损失再确认 + 占用检查兜底）与显式清理残留。
import { useCallback, useEffect, useState } from 'react'
import { App as AntApp, AutoComplete, Button, Drawer, Dropdown, Empty, Input, Modal, Popover, Select, Skeleton, Tag, Tooltip } from 'antd'
import { sessionLabel } from '../sessions/session-label'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { recentDirs } from '../sessions/DirPicker'
import DiffView from '../files/DiffView'
import { useLayout } from '../../layout'
import AdaptivePanel from '../shell/AdaptivePanel'
import { useBackDismiss } from '../shell/useBackDismiss'
import { ArrowDown, ArrowUp, CloseIcon, PlusIcon } from '../../icons'
import { BranchIcon } from './parts'
import { branchNames } from './local-branches'
import { WindowsIcon } from '../../icons'

// 会话视图的 Git 面板挂在右侧浮动面板(--z-panel)里，本抽屉从那里打开时必须压过它，
// 否则整个抽屉被 Git 面板盖住（antd Drawer 默认 z=1000）。抽屉内嵌套弹层 antd 会自动抬升，
// 但 modal.confirm 走 App 级 holder 不在抽屉上下文里，须显式再高一级。
// 手机档不走 Drawer——AdaptivePanel 会换成全屏二级页，这两个常量只对桌面生效。
const DRAWER_Z = 1300
const MODAL_Z = 1400

type WtSession = { session: string; primary: boolean }
type Worktree = {
  path: string; branch: string; head: string; isMain: boolean
  base: string; startOid: string; createdBy: string; createdAt: number
  external: boolean; adopted?: boolean; dirty: number; untracked: number
  committedAhead: number; behind: number; lastCommitAt: number
  locked: boolean; prunable: boolean; sessions: WtSession[]
}

// 相对时间（Unix 秒），与 App.tsx relTime 同款（避免循环依赖只引用函数式 recentDirs）
function relTime(sec: number | undefined, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (!sec || !Number.isFinite(sec)) return '—'
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - sec))
  if (diff < 60) return t('time.justNow')
  if (diff < 3600) return t('time.minutesAgo', { count: Math.floor(diff / 60) })
  if (diff < 86400) return t('time.hoursAgo', { count: Math.floor(diff / 3600) })
  return t('time.daysAgo', { count: Math.floor(diff / 86400) })
}

// 状态归类：主工作区 / 活会话 / 孤儿 / 外部（导轨色与筛选共用）
function catOf(wt: Worktree): 'main' | 'live' | 'orphan' | 'external' {
  if (wt.isMain) return 'main'
  if (wt.sessions?.length) return 'live'
  if (wt.external) return 'external'
  return 'orphan'
}
const RAIL: Record<string, string> = {
  main: 'rgba(139,148,158,.45)', live: 'var(--ok)', orphan: '#d29922', external: 'rgba(139,148,158,.7)',
}

export default function WorktreePanel({ open, onClose, openTerm, initialDir, embedded = false }: {
  open: boolean
  onClose: () => void
  /** 嵌在右栏三面板里（22 设计 §3.4）：不自己 claim Inspector 槽位、不画自己的标题行，壳由外层给 */
  embedded?: boolean
  openTerm?: (name: string) => void
  initialDir?: string
}) {
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const { desktop: wide } = useLayout()
  // dir 为空 = 跨仓库总览（当前全部会话触达的仓库）；填目录 = 聚焦单仓库
  const [dir, setDir] = useState('')
  const [list, setList] = useState<Worktree[] | null>(null)
  const [allGroups, setAllGroups] = useState<{ repo: string; worktrees: Worktree[] }[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  // 筛选：文本（分支/会话名）+ 状态档
  const [q, setQ] = useState('')
  const [cat, setCat] = useState<'all' | 'live' | 'orphan' | 'external'>('all')
  // + 新建 worktree（不带会话）：分支（此处可手动指定）+ 基于
  const [createOpen, setCreateOpen] = useState(false)
  const [newBranch, setNewBranch] = useState('')
  const [newBase, setNewBase] = useState('')
  const [branches, setBranches] = useState<string[]>([])
  const [creatingWt, setCreatingWt] = useState(false)
  // 对比 base：committed 与 workingTree 分开呈现 + 逐文件补丁
  const [cmp, setCmp] = useState<Worktree | null>(null)
  // 窄档：返回键先关对比视图，再关面板本身（一次返回退一层）
  useBackDismiss(!wide && !!cmp, () => setCmp(null))
  const [cmpData, setCmpData] = useState<any>(null)
  const [cmpFile, setCmpFile] = useState('')
  const [cmpText, setCmpText] = useState('')

  // 打开时优先用调用方指定目录（会话 Tag 直达聚焦单仓库），否则默认跨仓库总览
  useEffect(() => {
    if (!open) return
    setQ(''); setCat('all')
    if (initialDir) setDir(initialDir)
  }, [open, initialDir]) // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async (d: string, silent = false) => {
    if (!silent) setLoading(true)
    try {
      if (d.trim()) {
        const r = await api('GET', `/git/worktrees?dir=${encodeURIComponent(d.trim())}`)
        setList(Array.isArray(r?.data) ? r.data : []); setAllGroups(null)
      } else {
        const r = await api('GET', '/git/worktrees/all')
        setAllGroups(Array.isArray(r?.data) ? r.data : []); setList(null)
      }
    } catch (e: any) {
      if (!silent) { message.error(e.message); setList([]); setAllGroups([]) }
    } finally { if (!silent) setLoading(false) }
  }, [message])

  // 目录变化去抖加载；抽屉开着时 5s 轮询（service 侧有缓存兜底）
  usePageEffect(() => {
    if (!open) { setList(null); setAllGroups(null); return }
    const t0 = setTimeout(() => load(dir), 300)
    const iv = setInterval(() => load(dir, true), 5000)
    return () => { clearTimeout(t0); clearInterval(iv) }
  }, [open, dir, load])

  const withBusy = async (path: string, fn: () => Promise<void>) => {
    setBusy((m) => ({ ...m, [path]: true }))
    try { await fn() } finally { setBusy((m) => ({ ...m, [path]: false })) }
  }

  // 删除执行：默认 -d 删分支；409 分流兜底（占用/分支未合并——脏保护通常已被预检确认拦掉）。
  // 收养来的分支（开工时选的「已有分支」）例外：工作区是我们建的，分支不是，默认留着。
  const doRemove = (wt: Worktree, extra: Record<string, any> = {}) => withBusy(wt.path, async () => {
    try {
      await api('POST', '/git/worktree/remove', { path: wt.path, deleteBranch: !wt.adopted, ...extra })
      message.success(t('worktree.deleted'))
      load(dir, true)
    } catch (e: any) {
      const ae = e.apiError || {}
      if (ae.code === 'WORKTREE_DIRTY') {
        modal.confirm({
          zIndex: MODAL_Z,
          title: t('worktree.dirtyDeleteTitle'),
          content: t('worktree.dirtyDeleteDesc', { dirty: ae.dirty ?? wt.dirty, untracked: ae.untracked ?? wt.untracked }),
          okText: t('worktree.delete'), okButtonProps: { danger: true },
          onOk: () => { doRemove(wt, { ...extra, forceWorktree: true }) },
        })
      } else if (ae.code === 'SESSIONS_INSIDE') {
        modal.warning({
          zIndex: MODAL_Z,
          title: t('worktree.sessionsInsideTitle'),
          content: t('worktree.sessionsInsideDesc', { sessions: (ae.sessions || []).join(', ') }),
        })
      } else if (ae.code === 'BRANCH_NOT_MERGED') {
        load(dir, true) // worktree 本体已删，先刷新
        modal.confirm({
          zIndex: MODAL_Z,
          title: t('worktree.branchNotMergedTitle'),
          content: t('worktree.branchNotMergedDesc', { branch: ae.branch || wt.branch }),
          okText: t('worktree.forceDeleteBranch'), okButtonProps: { danger: true },
          onOk: () => { doRemove(wt, { ...extra, forceDeleteBranch: true }) },
        })
      } else {
        message.error(e.message)
      }
    }
  })

  // 删除入口：有货（改动/未合并提交）先列明损失再确认（w4 图纸），干净的直接删
  const beginRemove = (wt: Worktree) => {
    const dirtyAll = (wt.dirty || 0) + (wt.untracked || 0)
    const ahead = wt.committedAhead || 0
    if (dirtyAll === 0 && ahead === 0) { doRemove(wt); return }
    const delBranch = { current: !wt.adopted }
    modal.confirm({
      title: t('worktree.deleteLossTitle', { branch: wt.branch || wt.path.split('/').pop() || '' }),
      okText: t('worktree.stillDelete'), okButtonProps: { danger: true },
      content: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
          <div style={{ color: 'var(--text-dim)', lineHeight: 1.7 }}>
            {t('worktree.deleteLossDesc')}
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {dirtyAll > 0 && <li style={{ color: '#d29922' }}>{t('worktree.lossDirty', { count: dirtyAll })}</li>}
              {ahead > 0 && <li style={{ color: 'var(--accent)' }}>{t('worktree.lossAhead', { count: ahead, base: wt.base || 'base' })}</li>}
            </ul>
          </div>
          {!!wt.branch && (
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" defaultChecked={!wt.adopted} style={{ accentColor: 'var(--accent-solid)' }}
                onChange={(e) => { delBranch.current = e.target.checked }} />
              <span>{t('worktree.deleteBranchToo')} <span style={{ fontFamily: 'ui-monospace, monospace', color: '#39c5cf' }}>{wt.branch}</span>
                {wt.adopted && <span style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)' }}> {t('worktree.adoptedKeepBranch')}</span>}</span>
            </label>
          )}
        </div>
      ),
      onOk: () => doRemove(wt, {
        forceWorktree: dirtyAll > 0,
        deleteBranch: delBranch.current,
        ...(delBranch.current && ahead > 0 ? { forceDeleteBranch: true } : {}),
      }),
    })
  }

  const doMerge = (wt: Worktree, strategy: 'squash' | 'merge' | 'rebase') => withBusy(wt.path, async () => {
    try {
      const r = await api('POST', '/git/worktree/merge', { path: wt.path, strategy, expectedHead: wt.head })
      message.success(t('worktree.mergeSuccess', { base: r?.data?.base || wt.base }))
      load(dir, true)
      modal.confirm({
        zIndex: MODAL_Z,
        title: t('worktree.deleteAfterMergeTitle', { branch: wt.branch }),
        content: t('worktree.deleteAfterMergeDesc'),
        okText: t('worktree.delete'),
        onOk: () => { doRemove(wt, { ...(strategy === 'squash' && !wt.adopted ? { forceDeleteBranch: true } : {}) }) },
      })
    } catch (e: any) {
      const ae = e.apiError || {}
      if (ae.code === 'MERGE_CONFLICT') {
        modal.warning({
          zIndex: MODAL_Z,
          title: t('worktree.mergeConflictTitle'),
          content: (
            <div>
              <div>{t('worktree.mergeConflictDesc', { stage: ae.stage || '?' })}</div>
              <ul style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 8, paddingLeft: 18, maxHeight: 200, overflow: 'auto' }}>
                {(ae.conflictFiles || []).map((f: string) => <li key={f}>{f}</li>)}
              </ul>
            </div>
          ),
        })
      } else {
        message.error(e.message)
      }
    }
  })

  // 进入：有会话直接切过去；孤儿/外部 = 新建会话进入（复活）
  const doEnter = (wt: Worktree) => withBusy(wt.path, async () => {
    if (wt.sessions?.length) {
      openTerm?.(wt.sessions[0].session); onClose()
      return
    }
    const name = (wt.branch || wt.path.split('/').pop() || 'wt').replace(/\//g, '-')
    try {
      const res = await api('POST', '/sessions', { name, dir: wt.path })
      openTerm?.(res.name || name); onClose()
    } catch (e: any) { message.error(e.message) }
  })

  // 打开创建气泡时拉分支列表
  useEffect(() => {
    if (!createOpen || !dir.trim()) return
    api('GET', `/git/branches?dir=${encodeURIComponent(dir.trim())}`).then((r) => {
      setBranches(branchNames(r?.data?.branches))
      setNewBase((prev) => prev || r?.data?.default || '')
    }).catch(() => {})
  }, [createOpen, dir])

  const doCreate = async () => {
    setCreatingWt(true)
    try {
      const r = await api('POST', '/git/worktree', { dir: dir.trim(), branch: newBranch.trim(), base: newBase })
      message.success(t('worktree.created', { branch: r?.data?.branch || newBranch }))
      setCreateOpen(false); setNewBranch('')
      load(dir, true)
    } catch (e: any) { message.error(e.message) } finally { setCreatingWt(false) }
  }

  const doPrune = async () => {
    try {
      await api('POST', '/git/worktree/prune', { dir: dir.trim() })
      message.success(t('worktree.pruned'))
      load(dir, true)
    } catch (e: any) { message.error(e.message) }
  }

  // 对比 base：打开时拉统计，选文件拉补丁
  useEffect(() => {
    if (!cmp) { setCmpData(null); setCmpFile(''); setCmpText(''); return }
    let cancelled = false
    api('GET', `/git/worktree/diff?path=${encodeURIComponent(cmp.path)}`).then((r) => {
      if (cancelled) return
      setCmpData(r?.data || null)
      const first = r?.data?.committed?.files?.[0]?.path || r?.data?.workingTree?.files?.[0]?.path || ''
      setCmpFile(first)
    }).catch((e: any) => { if (!cancelled) { message.error(e.message); setCmp(null) } })
    return () => { cancelled = true }
  }, [cmp]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!cmp || !cmpFile) { setCmpText(''); return }
    let cancelled = false
    api('GET', `/git/worktree/diff?path=${encodeURIComponent(cmp.path)}&file=${encodeURIComponent(cmpFile)}`)
      .then((r) => { if (!cancelled) setCmpText(r?.data?.diff || '') })
      .catch(() => { if (!cancelled) setCmpText('') })
    return () => { cancelled = true }
  }, [cmp, cmpFile])

  // 四态徽章：活会话（点击进终端）/ 孤儿 / 外部创建 / 旧格式；主工作区单独标注
  const badges = (wt: Worktree) => {
    if (wt.isMain) return [<Tag key="m" style={{ margin: 0 }}>{t('worktree.main')}</Tag>]
    const out = [] as any[]
    if (wt.sessions?.length) {
      out.push(
        <Tag key="s" color="green" style={{ margin: 0, cursor: openTerm ? 'pointer' : 'default' }} title={wt.sessions.map((x) => x.session).join(', ')}
          onClick={openTerm ? () => { openTerm(wt.sessions[0].session); onClose() } : undefined}>
          {sessionLabel(wt.sessions[0].session)}{wt.sessions.length > 1 ? ` +${wt.sessions.length - 1}` : ''}
        </Tag>,
      )
    } else if (!wt.external) {
      out.push(<Tag key="o" color="warning" style={{ margin: 0 }}>{t('worktree.orphan')}</Tag>)
    }
    if (wt.external) out.push(<Tag key="e" style={{ margin: 0 }} icon={<WindowsIcon size={11} />}>{t('worktree.external')}</Tag>)
    if (wt.branch.startsWith('_')) out.push(<Tag key="l" color="warning" style={{ margin: 0 }}>{t('worktree.legacy')}</Tag>)
    return out
  }

  // 元信息行：有货着色（↑ 蓝 / 改动 黄），其余弱化
  const metaLine = (wt: Worktree) => {
    const dirtyAll = (wt.dirty || 0) + (wt.untracked || 0)
    return (
      <div style={{ color: 'var(--text-dimmer)', fontSize: 12, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <span>{t('worktree.baseOf', { base: '' })}<b style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--text-dim)' }}>{wt.base || '?'}</b></span>
        <span>·</span>
        <span>
          <b style={{ color: wt.committedAhead > 0 ? 'var(--accent)' : undefined, fontWeight: wt.committedAhead > 0 ? 700 : 400, display: 'inline-flex', alignItems: 'center', gap: 1 }}><ArrowUp size={11} />{wt.committedAhead}</b>
          {' '}
          <span style={{ color: wt.behind > 0 ? 'var(--text-dim)' : undefined, display: 'inline-flex', alignItems: 'center', gap: 1 }}><ArrowDown size={11} />{wt.behind}</span>
        </span>
        <span>·</span>
        <span style={{ color: dirtyAll > 0 ? '#d29922' : undefined, fontWeight: dirtyAll > 0 ? 700 : 400 }}>
          {dirtyAll > 0 ? t('worktree.changesHot', { count: dirtyAll }) : t('worktree.noChanges')}
        </span>
        <span>·</span>
        <span>{relTime(wt.lastCommitAt, t)}</span>
      </div>
    )
  }

  // 操作行：进入 / 对比 / 合并回 base ▾ / 删除；手机端收进「⋯」
  const actions = (wt: Worktree) => {
    if (wt.isMain) return null
    const canMerge = !wt.external && !!wt.base
    const canCompare = !!wt.base && !wt.branch.startsWith('_')
    const enterLabel = wt.sessions?.length ? t('worktree.enter') : t('worktree.enterNew')
    if (!wide) {
      const items: any[] = []
      if (canCompare) items.push({ key: 'cmp', label: t('worktree.compare') })
      if (canMerge) {
        items.push({ key: 'squash', label: t('worktree.mergeInto', { base: wt.base }) + ' · squash' })
        items.push({ key: 'merge', label: t('worktree.strategyMerge') })
        items.push({ key: 'rebase', label: t('worktree.strategyRebase') })
      }
      items.push({ key: 'del', label: t('worktree.delete'), danger: true })
      return (
        <div style={{ display: 'flex', gap: 8, marginTop: 2 }}>
          <Button size="small" loading={!!busy[wt.path]} onClick={() => doEnter(wt)}>{enterLabel}</Button>
          <Dropdown trigger={['click']} menu={{
            items,
            onClick: ({ key }) => {
              if (key === 'cmp') setCmp(wt)
              else if (key === 'del') beginRemove(wt)
              else doMerge(wt, key as any)
            },
          }}>
            <Button size="small">⋯</Button>
          </Dropdown>
        </div>
      )
    }
    return (
      <div style={{ display: 'flex', gap: 8, marginTop: 2, flexWrap: 'wrap' }}>
        <Button size="small" loading={!!busy[wt.path]} onClick={() => doEnter(wt)}>{enterLabel}</Button>
        {canCompare && <Button size="small" onClick={() => setCmp(wt)}>{t('worktree.compare')}</Button>}
        {canMerge && (
          <Dropdown.Button size="small" loading={!!busy[wt.path]}
            onClick={() => doMerge(wt, 'squash')}
            menu={{
              items: [
                { key: 'merge', label: t('worktree.strategyMerge') },
                { key: 'rebase', label: t('worktree.strategyRebase') },
              ],
              onClick: ({ key }) => doMerge(wt, key as 'merge' | 'rebase'),
            }}>
            {t('worktree.mergeInto', { base: wt.base })}
          </Dropdown.Button>
        )}
        <Button size="small" danger loading={!!busy[wt.path]} onClick={() => beginRemove(wt)}>
          {t('worktree.delete')}
        </Button>
      </div>
    )
  }

  // 两种视图统一成分组结构：单仓库 = 一个匿名组（含主工作区行）；总览 = 按仓库分组（不列主工作区行，组头即仓库）
  const focused = !!dir.trim()
  const dataReady = focused ? list !== null : allGroups !== null
  const allWts: Worktree[] = focused ? (list || []) : (allGroups || []).flatMap((g) => g.worktrees)
  const counts = { all: 0, live: 0, orphan: 0, external: 0 }
  for (const wt of allWts) {
    if (wt.isMain) continue
    counts.all++
    const c = catOf(wt)
    if (c !== 'main') counts[c]++
  }
  const ql = q.trim().toLowerCase()
  const match = (wt: Worktree) => {
    if (ql && !(wt.branch.toLowerCase().includes(ql) || wt.path.toLowerCase().includes(ql)
      || (wt.sessions || []).some((s) => `${sessionLabel(s.session)} ${s.session}`.toLowerCase().includes(ql)))) return false
    if (cat === 'all') return true
    if (wt.isMain) return false
    return catOf(wt) === cat
  }
  const sortRows = (ws: Worktree[]) => [...ws].sort((a, b) => Number(b.isMain) - Number(a.isMain) || (b.lastCommitAt || 0) - (a.lastCommitAt || 0))
  const groups: { repo: string; rows: Worktree[] }[] = focused
    ? [{ repo: '', rows: sortRows((list || []).filter(match)) }]
    : (allGroups || [])
      .map((g) => ({ repo: g.repo, rows: sortRows(g.worktrees.filter((w) => !w.isMain && match(w))) }))
      .filter((g) => g.rows.length > 0)
  const shownCount = groups.reduce((n, g) => n + g.rows.length, 0)

  const cmpFiles: { path: string; adds: number; dels: number }[] = (() => {
    if (!cmpData) return []
    const m = new Map<string, { path: string; adds: number; dels: number }>()
    for (const part of [cmpData.committed, cmpData.workingTree]) {
      for (const f of part?.files || []) {
        const cur = m.get(f.path) || { path: f.path, adds: 0, dels: 0 }
        cur.adds += f.adds; cur.dels += f.dels
        m.set(f.path, cur)
      }
    }
    return Array.from(m.values())
  })()

  return (
    // 手机走全屏二级页（13 §6）：全宽的 antd Drawer「既不是页也不是 sheet」——
    // 从右横切进场、右上角一个 ×、返回键不认它。
    // 桌面走 Inspector 列（14 panels-desktop.html）：抽屉的遮罩 + 横切进场是第三种
    // 「从右边出来一块」，和 Git 面板那两种并列。现在三者同一条 rail、同一套宽度记忆。
    <PanelShell embedded={embedded} open={open} onClose={onClose} title={t('worktree.title')}>
      {/* 桌面档的面板头：抽屉原来提供的标题与关闭，进 Inspector 之后要自己长出来；嵌入右栏时外层已经有活动条 */}
      {wide && !embedded && (
        <div style={{
          flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8,
          padding: '10px 12px', borderBottom: '1px solid var(--border-subtle)',
        }}>
          <b style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-bright)' }}>{t('worktree.title')}</b>
          <span style={{ flex: 1 }} />
          <button type="button" className="tt-file-close" onClick={onClose}
            title={t('common.close')} aria-label={t('common.close')}><CloseIcon /></button>
        </div>
      )}
      <div style={{
        flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column',
        gap: 0, padding: '14px 12px 12px',
      }}>
      {/* 头部：仓库目录（留空 = 跨仓库总览）+ 新建 + 刷新 */}
      <div style={{ display: 'flex', gap: 8 }}>
        <AutoComplete style={{ flex: 1, minWidth: 0 }} value={dir} onChange={setDir} allowClear
          options={recentDirs().map((d) => ({ value: d }))}
          filterOption={(input, opt) => String(opt?.value).toLowerCase().includes(input.toLowerCase())}
          placeholder={t('worktree.dirPlaceholder')} />
        <Popover open={createOpen} onOpenChange={setCreateOpen} trigger="click" placement="bottomRight"
          content={
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: 260 }}>
              <Input size="small" placeholder={t('worktree.createBranchPlaceholder')} value={newBranch}
                onChange={(e) => setNewBranch(e.target.value)} style={{ fontFamily: 'monospace' }} />
              <Select size="small" showSearch value={newBase || undefined} onChange={(v) => setNewBase(v)}
                placeholder={t('session.wt.basePlaceholder')}
                options={branches.map((b) => ({ value: b, label: b }))} />
              <Button size="small" type="primary" loading={creatingWt} disabled={!dir.trim()} onClick={doCreate}>{t('worktree.create')}</Button>
            </div>
          }>
          <Tooltip title={focused ? t('worktree.create') : t('worktree.createNeedsDir')}>
            <Button style={{ flex: '0 0 auto' }} disabled={!focused} icon={<PlusIcon size={13} />} />
          </Tooltip>
        </Popover>
        <Button onClick={() => load(dir)} loading={loading} style={{ flex: '0 0 auto' }}>{t('common.refresh')}</Button>
      </div>
      {/* 筛选行：状态档（带计数）+ 文本筛选 */}
      <div style={{ display: 'flex', gap: 8, margin: '10px 0 0', alignItems: 'center', flexWrap: 'wrap' }}>
        {([['all', t('common.all')], ['live', t('worktree.statLive')], ['orphan', t('worktree.orphan')], ['external', t('worktree.external')]] as const).map(([k, label]) => (
          <Tag.CheckableTag key={k} checked={cat === k} onChange={() => setCat(k as any)}
            style={{ margin: 0, fontSize: 12, lineHeight: '20px', userSelect: 'none' }}>
            {label} {counts[k as keyof typeof counts]}
          </Tag.CheckableTag>
        ))}
        <Input allowClear size="small" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder={t('worktree.filterPlaceholder')} style={{ flex: 1, minWidth: 120 }} />
      </div>
      {/* 关系说明：session↔worktree 是按 cwd 现算的弱关联 */}
      <div style={{ fontSize: 12, color: 'var(--text-dimmer)', lineHeight: 1.6, margin: '8px 0 12px' }}>
        {t('worktree.relationHint')}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {loading && !dataReady ? (
          <>{[0, 1, 2].map((i) => <Skeleton key={i} active title={false} paragraph={{ rows: 2 }} />)}</>
        ) : dataReady && counts.all === 0 ? (
          // 空态（Result 风格）：聚焦仓库时给直接新建 CTA；总览时说明数据来源
          <div style={{ textAlign: 'center', padding: '48px 16px' }}>
            <div style={{ opacity: 0.4, display: 'flex', justifyContent: 'center', color: 'var(--text-dim)' }}><BranchIcon size={30} /></div>
            <div style={{ fontSize: 14, margin: '10px 0 4px', color: 'var(--text-bright)' }}>{t('worktree.emptyTitle')}</div>
            <div style={{ fontSize: 12.5, color: 'var(--text-dimmer)', marginBottom: 14 }}>{focused ? t('worktree.emptyHint') : t('worktree.allEmptyHint')}</div>
            {focused && <Button size="small" type="primary" onClick={() => setCreateOpen(true)} icon={<PlusIcon size={12} />}>{t('worktree.create')}</Button>}
          </div>
        ) : dataReady ? (
          <>
            {shownCount === 0 && <Empty description={t('session.noMatches')} style={{ marginTop: 24 }} />}
            {groups.map((g) => (
              <div key={g.repo || '_'} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {!focused && (
                  // 总览的仓库组头：点击聚焦单仓库（可新建/清理）
                  <div onClick={() => setDir(g.repo)} style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, cursor: 'pointer', padding: '2px 2px 0' }}>
                    <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-bright)', flex: '0 0 auto' }}>{g.repo.split('/').filter(Boolean).pop()}</span>
                    <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11.5, color: 'var(--text-dimmer)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{g.repo}</span>
                    <Tag style={{ margin: 0, flex: '0 0 auto', fontSize: 11, lineHeight: '18px' }}>{g.rows.length}</Tag>
                    <a style={{ marginLeft: 'auto', fontSize: 12, flex: '0 0 auto' }}>{t('worktree.focusRepo')}</a>
                  </div>
                )}
                {g.rows.map((wt) => {
                  const c = catOf(wt)
                  return (
                    <div key={wt.path} style={{
                      position: 'relative', overflow: 'hidden',
                      background: c === 'orphan' ? 'rgba(210,153,34,.05)' : 'var(--bg-elevated)',
                      border: '1px solid var(--border)', borderRadius: 10,
                      padding: '10px 12px 10px 15px', display: 'flex', flexDirection: 'column', gap: 6,
                    }}>
                      <span aria-hidden style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: RAIL[c] }} />
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                        <span title={wt.path} style={{
                          fontFamily: 'monospace', fontWeight: 600, color: wt.branch.startsWith('_') ? 'var(--text-dimmer)' : 'var(--text-bright)',
                          minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                        }}><BranchIcon size={11} /><span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{wt.branch || wt.head?.slice(0, 8) || '?'}</span></span>
                        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, flex: '0 0 auto' }}>{badges(wt)}</span>
                      </div>
                      {metaLine(wt)}
                      {actions(wt)}
                    </div>
                  )
                })}
              </div>
            ))}
          </>
        ) : null}
      </div>

      {/* 底栏：全貌一句话；清理残留是仓库级操作，仅聚焦单仓库时提供 */}
      {dataReady && counts.all > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', paddingTop: 10, marginTop: 10, borderTop: '1px solid var(--border-subtle, #30363d)' }}>
          <span style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>
            {focused ? t('worktree.autoNote', { count: counts.all }) : t('worktree.autoNoteAll', { repos: (allGroups || []).length, count: counts.all })}
          </span>
          {focused && <Button size="small" style={{ marginLeft: 'auto' }} onClick={doPrune}>{t('worktree.prune')}</Button>}
        </div>
      )}

      {/* 对比 base：committed 与 workingTree 分开的统计行 + 文件横条 + 补丁 */}
      <Modal open={!!cmp} onCancel={() => setCmp(null)} footer={null} width="min(860px, 94vw)" destroyOnClose
        title={cmp && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <span style={{ fontFamily: 'ui-monospace, monospace', display: 'inline-flex', alignItems: 'center', gap: 4 }}><BranchIcon size={11} />{cmp.branch}</span>
            <span style={{ color: 'var(--text-dimmer)', fontWeight: 400, fontSize: 12.5 }}>{t('worktree.compareVs', { base: cmp.base || '?' })}</span>
          </span>
        )}>
        {!cmpData ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', gap: 14, fontSize: 12.5, color: 'var(--text-dim)', flexWrap: 'wrap' }}>
              <span>
                {t('worktree.cmpCommitted')}: {(cmpData.committed?.files || []).length} {t('race.stat.files')}
                {' '}<b style={{ color: 'var(--ok)' }}>+{cmpData.committed?.adds || 0}</b> <b style={{ color: '#f85149' }}>−{cmpData.committed?.dels || 0}</b>
              </span>
              <span>
                {t('worktree.cmpWorking')}: {(cmpData.workingTree?.files || []).length} {t('race.stat.files')}
                {' '}<b style={{ color: 'var(--ok)' }}>+{cmpData.workingTree?.adds || 0}</b> <b style={{ color: '#f85149' }}>−{cmpData.workingTree?.dels || 0}</b>
                {(cmpData.untracked || 0) > 0 && <span style={{ color: 'var(--text-dimmer)' }}>（+{cmpData.untracked} untracked）</span>}
              </span>
            </div>
            {cmpFiles.length > 0 && (
              <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 2 }}>
                {cmpFiles.map((f) => (
                  <span key={f.path} onClick={() => setCmpFile(f.path)} title={`${f.path}  +${f.adds} −${f.dels}`} style={{
                    cursor: 'pointer', padding: '2px 8px', borderRadius: 6, flex: '0 0 auto',
                    fontFamily: 'ui-monospace, monospace', fontSize: 12,
                    background: cmpFile === f.path ? 'var(--bg-elevated)' : 'transparent',
                    border: '1px solid ' + (cmpFile === f.path ? 'var(--border)' : 'transparent'),
                    opacity: cmpFile === f.path ? 1 : 0.65,
                  }}>{f.path.split('/').pop()}</span>
                ))}
              </div>
            )}
            <div style={{ height: '52vh', border: '1px solid var(--border-subtle, #30363d)', borderRadius: 8, overflow: 'hidden' }}>
              {cmpText.trim()
                ? <DiffView text={cmpText} />
                : <Empty style={{ marginTop: 60 }} description={t('worktree.noChanges')} />}
            </div>
          </div>
        )}
      </Modal>
      </div>
    </PanelShell>
  )
}

/** 面板的壳：独立打开时是 AdaptivePanel（claim 槽位 / 手机二级页）；嵌在右栏三面板里时只是一个列容器 */
function PanelShell({ embedded, open, onClose, title, children }: { embedded: boolean; open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  if (embedded) return <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, minWidth: 0 }}>{children}</div>
  return <AdaptivePanel open={open} onClose={onClose} title={title}>{children}</AdaptivePanel>
}
