import { primaryShortcutLabel } from '../../keyboard-platform'
// Git 面板 —— 会话/项目右侧的 Git 工作台。设计见 docs/design/web/11-git-panel.md（图版 G1–G6）。
//
// 四个 tab：改动（VSCode 式暂存/提交）、提交树（真 DAG 泳道图）、分支（本地/远端/worktree/标签/储藏）、
// 对比 base（仅 worktree 会话）。详情列二选一：文件差异 或 提交详情，宽屏贴面板左侧、窄屏整屏推入。
//
// 本文件只做编排：取数、状态、菜单、危险操作确认；渲染都在 ./git/* 里。
import {Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Dropdown, Input, Popover, Segmented, Spin, Tag, Tooltip, App as AntApp } from 'antd'
import type { MenuProps } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import DiffView from '../files/DiffView'
import GraphView, { type GraphData } from './GraphView'
import RefsView, { type BranchInfo, type RefsData, type StashEntry, type TagInfo, type WtInfo } from './RefsView'
import CommitDetail from './CommitDetail'
import AskModal, { type AskSpec } from './AskModal'
import {
  AheadBehind, BackIcon, BranchIcon, CloseIcon, DiscardIcon, MinusIcon, MONO, MoreIcon,
  PlusIcon, RefreshIcon, RowAct, Section, SyncIcon,
} from './parts'
import type { RawCommit } from './graph'
import { useLayout } from '../../layout'
import { InspectorLayers, type LayerSize } from '../shell/InspectorLayers'
import { useBackDismiss } from '../shell/useBackDismiss'
import { CheckIcon, ChevronDown, ChevronRight, WarnIcon } from '../../icons'
import { WindowsIcon } from '../../icons'
import { lazyRetry } from '../lazy-retry'

const WorktreePanel = lazyRetry(() => import('./WorktreePanel'))

interface GitFile { path: string; orig?: string; index: string; work: string; staged: boolean; untracked: boolean }
interface GitCommit { hash: string; short: string; subject: string; author: string; when: string }
interface GitStatus {
  repo: boolean; root?: string; branch?: string; ahead?: number; behind?: number
  upstream?: string; state?: string; conflicts?: string[]
  files?: GitFile[]; commits?: GitCommit[]
}
type Detail =
  | { kind: 'file'; file: string; staged: boolean; untracked: boolean; base?: boolean }
  | { kind: 'commit'; hash: string }

const GRAPH_PAGE = 150

function statusColor(code: string): string {
  switch (code) {
    case 'M': return 'hsl(38,90%,55%)'
    case 'A': return 'var(--ok)'
    case 'D': return 'hsl(0,70%,58%)'
    case 'R': case 'C': return 'hsl(210,75%,60%)'
    case 'U': return 'hsl(0,75%,60%)'
    case '?': return 'var(--text-dimmer)'
    default: return 'var(--text-dim)'
  }
}
const fileNameOf = (p: string) => p.split('/').pop() || p

// 「改动列表 ｜ 详情」两层折叠，与文件抽屉的「文件树 ｜ 预览」共用 <InspectorLayers>：
// 列表钉在抽屉右缘不动，diff / 提交详情从它左边长出来，面板外缘跟着两层之和让位。
// 下限比文件抽屉那对（树 180 / 预览 280）各放宽一档：改动行前面多一列状态字母，
// diff 又比正文多「-/+ 一列 + 原始缩进」，400 是它还读得下去的底线。
// 两层下限之和 625 就是分栏阈值：抽屉外缘的上界由 Shell 按终端让出的余量给（1600 屏上
// 终端并排时只有 552），到不了就整层盖住列表——**宁可少一栏，也不要开出一栏读不了的 diff**。
// 把 diff 下限压到 300 换取「这一档也能并排」试过，实测就是一栏 300 的 diff，每行都在横滚。
const LIST: LayerSize = { key: 'ttmux.gitListW', min: 220, max: 520, def: 320 }
const DETAIL: LayerSize = { key: 'ttmux.gitDetailW', min: 400, max: 1400, def: 620 }

function GitRow({ f, accent, active, kind, root, onOpen, onStage, onUnstage, onDiscard }: {
  f: GitFile; accent: string; active: boolean; kind: 'staged' | 'changes' | 'untracked' | 'conflict'; root?: string
  onOpen: () => void; onStage: () => void; onUnstage: () => void; onDiscard: () => void
}) {
  const { t } = useI18n()
  const code = (f.index !== ' ' && f.index !== '?') ? f.index : f.work
  const badge = f.untracked ? 'U' : (code || '?')
  const subdir = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : ''
  // f.path 相对仓库根；拼成绝对路径供拖到终端时识别（与文件面板一致的拖拽载荷）。
  const fullPath = root ? root.replace(/\/$/, '') + '/' + f.path : f.path
  return (
    <div className="cc-filerow" onClick={onOpen}
      draggable
      onDragStart={(ev) => {
        ev.dataTransfer.setData('application/x-ttmux-path', fullPath)
        ev.dataTransfer.setData('text/plain', fullPath)
        ev.dataTransfer.effectAllowed = 'copy'
      }}
      style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px 4px 10px', cursor: 'pointer', fontSize: 13, userSelect: 'none', background: active ? 'var(--accent-soft)' : undefined }}>
      <span style={{ width: 16, flex: '0 0 auto', textAlign: 'center', fontFamily: MONO, fontWeight: 700, color: statusColor(kind === 'conflict' ? 'U' : badge) }}>
        {kind === 'conflict' ? 'U' : badge}
      </span>
      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-bright)' }} title={f.path}>
        {f.orig && <span style={{ color: 'var(--text-dimmer)' }}>{fileNameOf(f.orig)} → </span>}
        {fileNameOf(f.path)}
        {subdir && <span style={{ color: 'var(--text-dimmer)', fontSize: 11, marginLeft: 6 }}>{subdir}</span>}
      </span>
      {kind === 'staged'
        ? <RowAct title={t('git.unstage')} onClick={onUnstage}><MinusIcon /></RowAct>
        : <>
            {kind !== 'conflict' && <RowAct title={t('git.discard')} danger onClick={onDiscard}><DiscardIcon /></RowAct>}
            <RowAct title={kind === 'conflict' ? t('git.markResolved') : t('git.stage')} onClick={onStage}><PlusIcon /></RowAct>
          </>}
      <span style={{ width: 5, height: 5, borderRadius: '50%', flex: '0 0 auto', background: accent, opacity: active ? 1 : 0 }} />
    </div>
  )
}

export default function GitPanel({ dir, accent = 'var(--accent)', onClose, openTerm, initialTab }: {
  dir?: string; accent?: string; onClose?: () => void
  openTerm?: (name: string) => void
  /** 从项目页分叉图点「对比 base」进来时直接落在该 tab */
  initialTab?: 'changes' | 'graph' | 'refs' | 'base'
}) {
  const { t } = useI18n()
  const { message, modal } = AntApp.useApp()

  const [status, setStatus] = useState<GitStatus | null>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [tick, setTick] = useState(0)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [diff, setDiff] = useState('')
  const [diffLoading, setDiffLoading] = useState(false)
  const [msg, setMsg] = useState('')
  const [amend, setAmend] = useState(false)
  const [ask, setAsk] = useState<AskSpec | null>(null)
  const [tab, setTab] = useState<'changes' | 'graph' | 'refs' | 'base'>(initialTab || 'changes')

  // 提交树
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)
  const [scope, setScope] = useState<'all' | 'current'>('all')
  const [query, setQuery] = useState('')
  const [pages, setPages] = useState(1)
  const [focus, setFocus] = useState<{ ref: string; nonce: number } | undefined>()
  const [selHash, setSelHash] = useState<string>('')

  // 分支页
  const [refs, setRefs] = useState<RefsData | null>(null)
  const [refsLoading, setRefsLoading] = useState(false)

  // worktree 态（W3 保留）：当前 dir 所在的 linked worktree + 对比 base
  const [wt, setWt] = useState<any | null>(null)
  const [wtAll, setWtAll] = useState<any[]>([])
  const [repoRoot, setRepoRoot] = useState('')
  const [cmp, setCmp] = useState<any | null>(null)
  const [wtOpen, setWtOpen] = useState(false)
  const [merging, setMerging] = useState(false)

  const { desktop: wide } = useLayout()
  // 窄档：返回键先关 diff 详情（面板本身由外面的二级页接管，一次返回退一层）
  useBackDismiss(!wide && !!detail, () => setDetail(null))
  const root = status?.root
  const refresh = useCallback(() => setTick((n) => n + 1), [])

  // ── 取数 ───────────────────────────────────────────────
  useEffect(() => {
    if (!dir) { setStatus(null); return }
    let stop = false
    setLoading(true); setErr('')
    api('GET', `/git/status?dir=${encodeURIComponent(dir)}`)
      .then((r) => { if (!stop) setStatus(r.data) })
      .catch((e) => { if (!stop) setErr(e.message) })
      .finally(() => { if (!stop) setLoading(false) })
    return () => { stop = true }
  }, [dir, tick])

  useEffect(() => {
    if (tab !== 'graph' || !dir) return
    let stop = false
    setGraphLoading(true)
    const q = query.trim() ? `&q=${encodeURIComponent(query.trim())}` : ''
    api('GET', `/git/graph?dir=${encodeURIComponent(dir)}&limit=${GRAPH_PAGE * pages}&scope=${scope}${q}`)
      .then((r) => { if (!stop) setGraph(r.data) })
      .catch((e) => { if (!stop) { setGraph(null); message.error(e.message) } })
      .finally(() => { if (!stop) setGraphLoading(false) })
    return () => { stop = true }
  }, [dir, tab, scope, query, pages, tick])

  useEffect(() => {
    if (tab !== 'refs' || !dir) return
    let stop = false
    setRefsLoading(true)
    api('GET', `/git/refs?dir=${encodeURIComponent(dir)}`)
      .then((r) => { if (!stop) setRefs(r.data) })
      .catch(() => { if (!stop) setRefs(null) })
      .finally(() => { if (!stop) setRefsLoading(false) })
    return () => { stop = true }
  }, [dir, tab, tick])

  // 探测当前 dir 落在哪个 linked worktree（最长前缀），并记主仓库根与全量清单
  useEffect(() => {
    if (!dir) { setWt(null); setWtAll([]); setRepoRoot(''); setTab('changes'); return }
    let stop = false
    api('GET', `/git/worktrees?dir=${encodeURIComponent(dir)}`).then((r) => {
      if (stop) return
      const list: any[] = Array.isArray(r?.data) ? r.data : []
      setWtAll(list)
      setRepoRoot(list.find((w) => w.isMain)?.path || '')
      let best: any = null
      for (const w of list) {
        if (w.isMain || w.prunable) continue
        if ((dir === w.path || dir.startsWith(w.path + '/')) && (!best || w.path.length > best.path.length)) best = w
      }
      setWt(best)
      if (!best || !best.base) setTab((cur) => (cur === 'base' ? 'changes' : cur))
      else if (initialTab) setTab(initialTab)
    }).catch(() => { if (!stop) { setWt(null); setWtAll([]); setRepoRoot('') } })
    return () => { stop = true }
  }, [dir, tick])

  useEffect(() => {
    if (tab !== 'base' || !wt?.base) { setCmp(null); return }
    let stop = false
    api('GET', `/git/worktree/diff?path=${encodeURIComponent(wt.path)}`)
      .then((r) => { if (!stop) setCmp(r?.data || null) })
      .catch(() => { if (!stop) setCmp(null) })
    return () => { stop = true }
  }, [tab, wt, tick])

  // 选中的文件被暂存/放弃后从清单消失 → 关掉详情
  useEffect(() => {
    if (detail?.kind !== 'file' || detail.base || !status?.files) return
    if (!status.files.some((f) => f.path === detail.file)) setDetail(null)
  }, [status])

  useEffect(() => {
    if (detail?.kind !== 'file' || !root) { if (detail?.kind !== 'file') setDiff(''); return }
    let stop = false
    setDiffLoading(true)
    const req = detail.base && wt
      ? api('GET', `/git/worktree/diff?path=${encodeURIComponent(wt.path)}&file=${encodeURIComponent(detail.file)}`)
      : api('GET', `/git/diff?root=${encodeURIComponent(root)}&file=${encodeURIComponent(detail.file)}&staged=${detail.staged ? 1 : 0}&untracked=${detail.untracked ? 1 : 0}`)
    req
      .then((r) => { if (!stop) setDiff(r.data?.diff || '') })
      .catch((e) => { if (!stop) setDiff(`# ${e.message}`) })
      .finally(() => { if (!stop) setDiffLoading(false) })
    return () => { stop = true }
  }, [detail, root])

  // ── 写操作 ─────────────────────────────────────────────
  const run = async (fn: () => Promise<any>, okMsg?: string) => {
    if (busy) return
    setBusy(true)
    try {
      const r = await fn()
      refresh()
      const out = r?.data?.output?.trim?.()
      if (out) message.success(out)
      else if (okMsg) message.success(okMsg)
    } catch (e: any) {
      const ae = e.apiError
      // 冲突类失败：把冲突文件列出来并引导去「改动」页解
      if (ae?.conflictFiles?.length) {
        modal.error({
          title: t('git.action.conflictTitle'),
          content: (
            <div style={{ fontSize: 13 }}>
              <div style={{ marginBottom: 6 }}>{t('git.action.conflictDesc', { state: ae.state || '?' })}</div>
              <ul style={{ paddingLeft: 18, margin: 0, fontFamily: MONO, fontSize: 12 }}>
                {ae.conflictFiles.map((cf: string) => <li key={cf}>{cf}</li>)}
              </ul>
            </div>
          ),
          onOk: () => setTab('changes'),
        })
        refresh()
      } else message.error(e.message)
    } finally { setBusy(false) }
  }
  const act = (body: Record<string, any>, okMsg?: string) =>
    run(() => api('POST', '/git/action', { root, ...body }), okMsg)
  const confirmAct = (title: string, okText: string, body: Record<string, any>, okMsg?: string) =>
    modal.confirm({ title, okText, cancelText: t('common.cancel'), okButtonProps: { danger: true }, onOk: () => act(body, okMsg) })

  const stage = (files: string[]) => run(() => api('POST', '/git/stage', { root, files }))
  const stageAll = () => run(() => api('POST', '/git/stage', { root, all: true }))
  const unstage = (files: string[]) => run(() => api('POST', '/git/unstage', { root, files }))
  const unstageAll = () => run(() => api('POST', '/git/unstage', { root, all: true }))
  const discardFile = (f: GitFile) => {
    modal.confirm({
      title: t('git.discardConfirm', { file: f.path }),
      okText: t('git.discard'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
      onOk: () => run(() => api('POST', '/git/discard', f.untracked ? { root, untracked: [f.path] } : { root, files: [f.path] })),
    })
  }
  const discardAll = () => {
    modal.confirm({
      title: t('git.discardAllConfirm'), okText: t('git.discardAll'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
      onOk: () => run(() => api('POST', '/git/discard', { root, files: ['.'] })),
    })
  }
  const op = (o: string) => run(() => api('POST', '/git/op', { root, op: o }), t('git.opDone', { op: o }))
  const doCommit = async (mode: 'plain' | 'push' | 'sync') => {
    if (!msg.trim()) { message.warning(t('git.commitEmpty')); return }
    await run(async () => {
      const r = await api('POST', '/git/commit', { root, message: msg, push: mode === 'push', amend })
      setMsg(''); setAmend(false)
      if (mode === 'sync') await api('POST', '/git/op', { root, op: 'sync' })
      return r
    }, t('git.committed'))
  }
  // 勾上「修订」就把上次的提交信息填回输入框，省得重打一遍
  const toggleAmend = async () => {
    if (amend) { setAmend(false); setMsg(''); return }
    setAmend(true)
    if (!msg.trim() && graph?.commits?.[0]) setMsg(graph.commits[0].subject)
    else if (!msg.trim() && status?.commits?.[0]) setMsg(status.commits[0].subject)
  }

  const doWtMerge = async (strategy: 'merge' | 'squash' | 'rebase') => {
    if (!wt) return
    setMerging(true)
    try {
      await api('POST', '/git/worktree/merge', { path: wt.path, strategy, expectedHead: wt.head })
      message.success(t('git.wt.mergeDone', { base: wt.base }))
      refresh()
    } catch (e: any) {
      const ae = e.apiError
      if (ae?.code === 'MERGE_CONFLICT') {
        modal.error({
          title: t('worktree.mergeConflictTitle'),
          content: (
            <div style={{ fontSize: 13 }}>
              <div style={{ marginBottom: 6 }}>{t('worktree.mergeConflictDesc', { stage: ae.stage || '?' })}</div>
              <ul style={{ paddingLeft: 18, margin: 0, fontFamily: MONO, fontSize: 12 }}>
                {(ae.conflictFiles || []).map((cf: string) => <li key={cf}>{cf}</li>)}
              </ul>
            </div>
          ),
        })
      } else message.error(e.message)
    } finally { setMerging(false) }
  }

  // ── 分组 ───────────────────────────────────────────────
  const conflicts = useMemo(() => {
    const set = new Set(status?.conflicts || [])
    return (status?.files || []).filter((f) => set.has(f.path) || f.index === 'U' || f.work === 'U')
  }, [status])
  const conflictSet = useMemo(() => new Set(conflicts.map((f) => f.path)), [conflicts])
  const staged = useMemo(() => (status?.files || []).filter((f) => f.staged && !f.untracked && !conflictSet.has(f.path)), [status, conflictSet])
  const changed = useMemo(() => (status?.files || []).filter((f) => !f.untracked && f.work !== ' ' && f.work !== '?' && !conflictSet.has(f.path)), [status, conflictSet])
  const untracked = useMemo(() => (status?.files || []).filter((f) => f.untracked), [status])
  const clean = status?.repo && !loading && (status.files?.length ?? 0) === 0

  // 分支 → worktree 路径，供提交树的 ⧉ 角标用
  const wtByBranch = useMemo(() => {
    const m: Record<string, string> = {}
    for (const w of wtAll) if (!w.isMain && w.branch) m[w.branch] = w.path
    return m
  }, [wtAll])

  const gotoWorktree = (path: string) => {
    const w = wtAll.find((x) => x.path === path)
    const s = w?.sessions?.[0]?.session
    if (s && openTerm) { openTerm(s); return }
    setWtOpen(true)
  }

  const locate = (ref: string) => { setTab('graph'); setFocus({ ref, nonce: Date.now() }) }

  // ── 菜单 ───────────────────────────────────────────────
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); message.success(t('common.copied')) }
    catch { message.warning(t('git.action.copyFailed')) }
  }

  const commitMenu = (c: RawCommit): MenuProps => commitActionsMenu(c.hash, c.short)
  const commitActionsMenu = (hash: string, short: string): MenuProps => ({
    items: [
      { key: 'open', label: t('git.action.viewCommit') },
      { key: 'copy', label: t('git.detail.copySha') },
      { type: 'divider' },
      { key: 'branch', label: t('git.action.branchHere') },
      { key: 'tag', label: t('git.action.tagHere') },
      { key: 'checkout', label: t('git.action.checkoutCommit') },
      { type: 'divider' },
      { key: 'cherry', label: t('git.action.cherryPick') },
      { key: 'revert', label: t('git.action.revert') },
      {
        key: 'reset', label: t('git.action.reset'), danger: true, children: [
          { key: 'reset:soft', label: t('git.action.resetSoft') },
          { key: 'reset:mixed', label: t('git.action.resetMixed') },
          { key: 'reset:hard', label: t('git.action.resetHard'), danger: true },
        ],
      },
    ],
    onClick: ({ key }) => {
      if (key === 'open') { setSelHash(hash); setDetail({ kind: 'commit', hash }) }
      else if (key === 'copy') copy(hash)
      else if (key === 'branch') setAsk({
        title: t('git.action.branchHere'), label: t('git.action.branchFrom', { rev: short }),
        placeholder: 'feat/…', okText: t('git.refs.create'),
        onOk: (name) => act({ action: 'branch-create', name, from: hash, checkout: true }, t('git.action.branchCreated', { name })),
      })
      else if (key === 'tag') setAsk({
        title: t('git.action.tagHere'), label: t('git.action.tagAt', { rev: short }),
        placeholder: 'v1.0.0', okText: t('git.refs.create'),
        onOk: (name) => act({ action: 'tag-create', name, hash }, t('git.action.tagCreated', { name })),
      })
      else if (key === 'checkout') confirmAct(t('git.action.checkoutCommitConfirm', { rev: short }), t('git.refs.checkout'), { action: 'checkout', ref: hash })
      else if (key === 'cherry') act({ action: 'cherry-pick', hash }, t('git.action.cherryPicked', { rev: short }))
      else if (key === 'revert') act({ action: 'revert', hash }, t('git.action.reverted', { rev: short }))
      else if (key.startsWith('reset:')) {
        const mode = key.slice(6)
        confirmAct(
          mode === 'hard' ? t('git.action.resetHardConfirm', { rev: short }) : t('git.action.resetConfirm', { rev: short, mode }),
          t('git.action.reset'), { action: 'reset', hash, mode },
        )
      }
    },
  })

  const branchMenu = (b: BranchInfo): MenuProps => ({
    items: [
      { key: 'locate', label: t('git.refs.locate') },
      { key: 'checkout', label: t('git.refs.checkout'), disabled: b.current },
      { type: 'divider' },
      { key: 'merge', label: t('git.refs.mergeInto', { branch: status?.branch || 'HEAD' }), disabled: b.current },
      { key: 'rebase', label: t('git.refs.rebaseOnto', { branch: b.name }), disabled: b.current },
      { type: 'divider' },
      { key: 'push', label: b.upstream ? t('git.push') : t('git.refs.pushSetUpstream') },
      { key: 'rename', label: t('git.refs.rename') },
      { key: 'copy', label: t('common.copy') },
      { key: 'delete', label: t('git.refs.delete'), danger: true, disabled: b.current },
    ],
    onClick: ({ key }) => {
      if (key === 'locate') locate(b.name)
      else if (key === 'checkout') act({ action: 'checkout', ref: b.name }, t('git.refs.checkedOut', { branch: b.name }))
      else if (key === 'merge') act({ action: 'merge', ref: b.name }, t('git.refs.merged', { branch: b.name }))
      else if (key === 'rebase') confirmAct(t('git.refs.rebaseConfirm', { branch: b.name }), t('git.refs.rebase'), { action: 'rebase', ref: b.name })
      else if (key === 'push') act({ action: 'push-branch', ref: b.name, upstream: !b.upstream }, t('git.refs.pushed', { branch: b.name }))
      else if (key === 'rename') setAsk({
        title: t('git.refs.rename'), initial: b.name, okText: t('git.refs.rename'),
        onOk: (name) => act({ action: 'branch-rename', ref: b.name, name }, t('git.refs.renamed', { name })),
      })
      else if (key === 'copy') copy(b.name)
      else if (key === 'delete') {
        // 未合并的分支 git 会用 -d 拒绝；这里先试安全删，失败再问要不要 -D
        modal.confirm({
          title: t('git.refs.deleteConfirm', { branch: b.name }),
          okText: t('git.refs.delete'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
          onOk: async () => {
            try {
              await api('POST', '/git/action', { root, action: 'branch-delete', ref: b.name })
              message.success(t('git.refs.deleted', { branch: b.name })); refresh()
            } catch (e: any) {
              modal.confirm({
                title: t('git.refs.forceDeleteTitle', { branch: b.name }),
                content: <div style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>{e.message}</div>,
                okText: t('git.refs.forceDelete'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
                onOk: () => act({ action: 'branch-delete', ref: b.name, force: true }, t('git.refs.deleted', { branch: b.name })),
              })
            }
          },
        })
      }
    },
  })

  const remoteMenu = (b: BranchInfo): MenuProps => ({
    items: [
      { key: 'locate', label: t('git.refs.locate') },
      { key: 'checkout', label: t('git.refs.checkoutTracking') },
      { key: 'merge', label: t('git.refs.mergeInto', { branch: status?.branch || 'HEAD' }) },
      { key: 'copy', label: t('common.copy') },
    ],
    onClick: ({ key }) => {
      const local = b.name.includes('/') ? b.name.slice(b.name.indexOf('/') + 1) : b.name
      if (key === 'locate') locate(b.name)
      else if (key === 'checkout') act({ action: 'checkout', ref: local }, t('git.refs.checkedOut', { branch: local }))
      else if (key === 'merge') act({ action: 'merge', ref: b.name }, t('git.refs.merged', { branch: b.name }))
      else if (key === 'copy') copy(b.name)
    },
  })

  const tagMenu = (tg: TagInfo): MenuProps => ({
    items: [
      { key: 'locate', label: t('git.refs.locate') },
      { key: 'copy', label: t('common.copy') },
      { key: 'delete', label: t('git.refs.deleteTag'), danger: true },
    ],
    onClick: ({ key }) => {
      if (key === 'locate') locate(tg.name)
      else if (key === 'copy') copy(tg.name)
      else if (key === 'delete') confirmAct(t('git.refs.deleteTagConfirm', { tag: tg.name }), t('git.refs.delete'), { action: 'tag-delete', ref: tg.name })
    },
  })

  const stashMenu = (s: StashEntry, i: number): MenuProps => ({
    items: [
      { key: 'pop', label: t('git.refs.stashPop') },
      { key: 'apply', label: t('git.refs.stashApply') },
      { key: 'drop', label: t('git.refs.stashDrop'), danger: true },
    ],
    onClick: ({ key }) => {
      if (key === 'drop') confirmAct(t('git.refs.stashDropConfirm', { ref: s.ref }), t('git.refs.stashDrop'), { action: 'stash-drop', index: i })
      else act({ action: `stash-${key}`, index: i }, t(key === 'pop' ? 'git.refs.stashPopped' : 'git.refs.stashApplied'))
    },
  })

  const wtMenu = (w: WtInfo): MenuProps => {
    const live = w.sessions?.length || 0
    return {
      items: [
        { key: 'enter', label: live ? t('git.refs.wtEnter') : t('git.refs.wtNoSession'), disabled: !live || !openTerm },
        { key: 'locate', label: t('git.refs.locate'), disabled: !w.branch },
        { key: 'compare', label: t('git.wt.compare', { base: w.base || '?' }), disabled: !w.base },
        { type: 'divider' },
        { key: 'manage', label: t('git.wt.manage') },
      ],
      onClick: ({ key }) => {
        if (key === 'enter') gotoWorktree(w.path)
        else if (key === 'locate' && w.branch) locate(w.branch)
        else if (key === 'compare') { setWt(wtAll.find((x) => x.path === w.path) || null); setTab('base') }
        else if (key === 'manage') setWtOpen(true)
      },
    }
  }

  const moreItems: MenuProps['items'] = [
    { key: 'pull', label: t('git.pull') },
    { key: 'push', label: t('git.push') },
    { key: 'fetch', label: t('git.fetch') },
    { key: 'sync', label: t('git.sync') },
    { type: 'divider' },
    { key: 'stageAll', label: t('git.stageAll'), disabled: !changed.length && !untracked.length },
    { key: 'unstageAll', label: t('git.unstageAll'), disabled: !staged.length },
    { key: 'stash', label: t('git.refs.stashAll'), disabled: !status?.files?.length },
    { key: 'discardAll', label: t('git.discardAll'), danger: true, disabled: !changed.length },
  ]
  const onMore: MenuProps['onClick'] = ({ key }) => {
    if (key === 'stageAll') stageAll()
    else if (key === 'unstageAll') unstageAll()
    else if (key === 'discardAll') discardAll()
    else if (key === 'stash') stashAll()
    else op(key)
  }

  const stashAll = () => setAsk({
    title: t('git.refs.stashAll'), label: t('git.refs.stashMessage'), placeholder: t('git.refs.stashPlaceholder'),
    initial: t('git.refs.stashDefault'), okText: t('git.refs.stash'),
    onOk: (m) => act({ action: 'stash-push', message: m, untracked: true }, t('git.refs.stashed')),
  })
  const newBranch = (from?: string) => setAsk({
    title: t('git.refs.newBranch'), label: t('git.action.branchFrom', { rev: from || status?.branch || 'HEAD' }),
    placeholder: 'feat/…', okText: t('git.refs.create'),
    onOk: (name) => act({ action: 'branch-create', name, from, checkout: true }, t('git.action.branchCreated', { name })),
  })

  // ── 头部 ───────────────────────────────────────────────
  const switcher = (
    <div style={{ width: 280, maxWidth: '80vw' }}>
      <BranchSwitcher
        dir={dir} tick={tick} current={status?.branch}
        onPick={(name) => act({ action: 'checkout', ref: name }, t('git.refs.checkedOut', { branch: name }))}
        onNew={() => newBranch()}
      />
    </div>
  )

  // ⋯ 与 ↻：桌面在标题行右端；窄档标题行整行不渲染（页头已经是「← Git」），
  // 这两枚挪到分支行右端——否则会留下一条只有两个图标的空带。
  const headerActs = (<>
    {status?.repo && (
      <Dropdown trigger={['click']} menu={{ items: moreItems, onClick: onMore }} placement="bottomRight" disabled={busy}>
        <Button type="text" size="small" style={{ width: 24, height: 24, minWidth: 24, padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: '0 0 auto' }}><MoreIcon /></Button>
      </Dropdown>
    )}
    <Tooltip title={t('git.refresh')}>
      <Button type="text" size="small" onClick={refresh} style={{ width: 24, height: 24, minWidth: 24, padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: '0 0 auto' }}><RefreshIcon /></Button>
    </Tooltip>
  </>)

  const header = (
    <div style={{ padding: '6px 8px 8px', borderBottom: '1px solid var(--border-subtle)', flex: '0 0 auto' }}>
      {wide && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: accent, display: 'inline-flex' }}><BranchIcon /></span>
          <span style={{ color: 'var(--text-bright)', fontWeight: 600, fontSize: 13 }}>{t('git.panelTitle')}</span>
          <span style={{ flex: 1 }} />
          {headerActs}
          {onClose && <button type="button" title={t('git.closePanel')} aria-label={t('git.closePanel')} className="tt-file-close" onClick={onClose}><CloseIcon /></button>}
        </div>
      )}

      {status?.repo && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: wide ? 7 : 0, minWidth: 0 }}>
          <Popover trigger="click" placement="bottomLeft" content={switcher} arrow={false}>
            <button type="button" title={t('git.refs.switchBranch')}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, height: 26, padding: '0 9px', maxWidth: 210,
                borderRadius: 7, background: 'var(--bg-base)', border: '1px solid var(--border)',
                fontFamily: MONO, fontSize: 12.5, color: 'var(--text-bright)', cursor: 'pointer', flex: '0 1 auto', minWidth: 0,
              }}>
              <span style={{ color: accent, display: 'inline-flex', flex: '0 0 auto' }}><BranchIcon size={12} /></span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{status.branch || 'HEAD'}</span>
              <span style={{ color: 'var(--text-dimmer)', display: 'inline-flex', flex: '0 0 auto' }}><ChevronDown size={11} /></span>
            </button>
          </Popover>
          <Tooltip title={t('git.sync')}>
            <Button type="text" size="small" onClick={() => op('sync')} disabled={busy}
              style={{ height: 24, padding: '0 6px', display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--text-dim)', flex: '0 0 auto' }}>
              <SyncIcon /><AheadBehind ahead={status.ahead} behind={status.behind} />
            </Button>
          </Tooltip>
          {wt && (
            <Tooltip title={t('git.wt.badgeTip')}>
              <Tag color="cyan" style={{ margin: 0, cursor: 'pointer', flex: '0 0 auto' }} onClick={() => setWtOpen(true)}>worktree{wt.external ? <> · <WindowsIcon size={10} /></> : ''}</Tag>
            </Tooltip>
          )}
          {status.upstream && (
            <span style={{ fontSize: 11, color: 'var(--text-dimmer)', fontFamily: MONO, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}
              title={status.upstream}>{status.upstream}</span>
          )}
          {!wide && <span style={{ flex: 1 }} />}
          {!wide && headerActs}
        </div>
      )}

      {wt && (
        <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dimmer)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={repoRoot}>
          {t('git.wt.baseLine', { base: wt.base || '?', repo: repoRoot })}
        </div>
      )}

      {status?.repo && (
        <div style={{ marginTop: 8 }}>
          <Segmented size="small" block value={tab} onChange={(v) => setTab(v as any)}
            options={[
              { label: `${t('git.changes')}${status.files?.length ? ` (${status.files.length})` : ''}`, value: 'changes' },
              { label: t('git.graph.tab'), value: 'graph' },
              { label: t('git.refs.tab'), value: 'refs' },
              ...(wt?.base ? [{ label: t('git.wt.tabBase', { base: wt.base }), value: 'base' }] : []),
            ]} />
        </div>
      )}
    </div>
  )

  // merge/rebase 卡住时的状态横幅
  const banner = status?.state ? (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', flex: '0 0 auto',
      background: 'rgba(210,153,34,.10)', borderBottom: '1px solid rgba(210,153,34,.3)', fontSize: 12, color: '#e3b341',
    }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><WarnIcon size={13} /> {t(`git.state.${status.state}` as any)}</span>
      {!!conflicts.length && <span>· {t('git.state.conflicts', { count: conflicts.length })}</span>}
      <span style={{ flex: 1 }} />
      <Button size="small" style={{ height: 22, fontSize: 11.5 }} disabled={busy || !!conflicts.length}
        onClick={() => act({ action: 'continue' }, t('git.state.continued'))}>{t('git.state.continue')}</Button>
      <Button size="small" danger style={{ height: 22, fontSize: 11.5 }} disabled={busy}
        onClick={() => confirmAct(t('git.state.abortConfirm'), t('git.state.abort'), { action: 'abort' }, t('git.state.aborted'))}>
        {t('git.state.abort')}
      </Button>
    </div>
  ) : null

  // ── 各 tab 主体 ────────────────────────────────────────
  const changesPane = (
    <>
      <div style={{ padding: 8, borderBottom: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: 6, flex: '0 0 auto' }}>
        <Input.TextArea
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); doCommit('plain') } }}
          placeholder={amend ? t('git.amendPlaceholder') : t('git.commitPlaceholder', { branch: status?.branch || 'HEAD', shortcut: primaryShortcutLabel() + 'Enter' })}
          autoSize={{ minRows: 1, maxRows: 5 }}
          style={{ fontSize: 12.5 }}
        />
        <div style={{ display: 'flex', gap: 6 }}>
          <Dropdown.Button
            size="small" type="primary" style={{ flex: 1 }}
            icon={<ChevronDown size={11} />}
            disabled={busy || !msg.trim()}
            onClick={() => doCommit('plain')}
            menu={{ items: [{ key: 'push', label: t('git.commitPush') }, { key: 'sync', label: t('git.commitSync') }], onClick: ({ key }) => doCommit(key as any) }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><CheckIcon size={13} />{amend ? t('git.amend') : t('git.commit')}{staged.length ? ` (${staged.length})` : ''}</span>
          </Dropdown.Button>
          <Tooltip title={t('git.amendTip')}>
            <Button size="small" type={amend ? 'primary' : 'default'} ghost={amend} onClick={toggleAmend}>{t('git.amend')}</Button>
          </Tooltip>
          <Tooltip title={t('git.refs.stashAll')}>
            <Button size="small" onClick={stashAll} disabled={!status?.files?.length}>{t('git.refs.stash')}</Button>
          </Tooltip>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '4px 0' }}>
        {(loading || busy) && <div style={{ display: 'flex', justifyContent: 'center', padding: 10 }}><Spin size="small" /></div>}
        {err && <div style={{ color: '#f85149', fontSize: 12, padding: '6px 10px' }}>{t('git.loadFailed', { message: err })}</div>}
        {clean && <div style={{ color: 'var(--text-dimmer)', fontSize: 12, padding: 10, display: 'flex', alignItems: 'center', gap: 5 }}><CheckIcon size={12} />{t('git.noChanges')}</div>}

        {!!conflicts.length && (
          <Section title={t('git.conflicts')} count={conflicts.length}
            extra={<RowAct title={t('git.markAllResolved')} onClick={() => stage(conflicts.map((f) => f.path))}><PlusIcon /></RowAct>}>
            {conflicts.map((f) => <GitRow key={'x' + f.path} f={f} accent={accent} root={root} kind="conflict"
              active={detail?.kind === 'file' && detail.file === f.path}
              onOpen={() => setDetail({ kind: 'file', file: f.path, staged: false, untracked: false })}
              onStage={() => stage([f.path])} onUnstage={() => {}} onDiscard={() => {}} />)}
          </Section>
        )}
        {!!staged.length && (
          <Section title={t('git.staged')} count={staged.length}
            extra={<RowAct title={t('git.unstageAll')} onClick={unstageAll}><MinusIcon /></RowAct>}>
            {staged.map((f) => <GitRow key={'s' + f.path} f={f} accent={accent} root={root} kind="staged"
              active={detail?.kind === 'file' && detail.file === f.path && detail.staged}
              onOpen={() => setDetail({ kind: 'file', file: f.path, staged: true, untracked: false })}
              onStage={() => {}} onUnstage={() => unstage([f.path])} onDiscard={() => {}} />)}
          </Section>
        )}
        {!!changed.length && (
          <Section title={t('git.changes')} count={changed.length}
            extra={<><RowAct title={t('git.discardAll')} danger onClick={discardAll}><DiscardIcon /></RowAct><RowAct title={t('git.stageAll')} onClick={() => stage(changed.map((f) => f.path))}><PlusIcon /></RowAct></>}>
            {changed.map((f) => <GitRow key={'c' + f.path} f={f} accent={accent} root={root} kind="changes"
              active={detail?.kind === 'file' && detail.file === f.path && !detail.staged && !detail.untracked}
              onOpen={() => setDetail({ kind: 'file', file: f.path, staged: false, untracked: false })}
              onStage={() => stage([f.path])} onUnstage={() => {}} onDiscard={() => discardFile(f)} />)}
          </Section>
        )}
        {!!untracked.length && (
          <Section title={t('git.untracked')} count={untracked.length}
            extra={<RowAct title={t('git.stageAll')} onClick={() => stage(untracked.map((f) => f.path))}><PlusIcon /></RowAct>}>
            {untracked.map((f) => <GitRow key={'u' + f.path} f={f} accent={accent} root={root} kind="untracked"
              active={detail?.kind === 'file' && detail.file === f.path && detail.untracked}
              onOpen={() => setDetail({ kind: 'file', file: f.path, staged: false, untracked: true })}
              onStage={() => stage([f.path])} onUnstage={() => {}} onDiscard={() => discardFile(f)} />)}
          </Section>
        )}
      </div>
    </>
  )

  const basePane = wt && (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '4px 0' }}>
      {!cmp ? <div style={{ display: 'flex', justifyContent: 'center', padding: 12 }}><Spin size="small" /></div> : (
        <>
          <div style={{ padding: '6px 10px', fontSize: 12, color: 'var(--text-dim)' }}>
            {t('git.wt.summary', { files: cmp.committed?.files?.length ?? 0, adds: cmp.committed?.adds ?? 0, dels: cmp.committed?.dels ?? 0 })}
            {((cmp.workingTree?.files?.length ?? 0) + (cmp.untracked ?? 0)) > 0 && (
              <div style={{ color: 'var(--text-dimmer)', marginTop: 2 }}>{t('git.wt.workingNote', { count: (cmp.workingTree?.files?.length ?? 0) + (cmp.untracked ?? 0) })}</div>
            )}
          </div>
          {!(cmp.committed?.files?.length) && <div style={{ color: 'var(--text-dimmer)', fontSize: 12, padding: '8px 10px', display: 'flex', alignItems: 'center', gap: 5 }}><CheckIcon size={12} />{t('git.wt.noDiff', { base: wt.base })}</div>}
          {(cmp.committed?.files || []).map((fs: any) => (
            <div key={fs.path} className="cc-filerow" onClick={() => setDetail({ kind: 'file', file: fs.path, staged: false, untracked: false, base: true })}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', cursor: 'pointer', fontSize: 13, background: detail?.kind === 'file' && detail.file === fs.path && detail.base ? 'var(--accent-soft)' : undefined }}>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-bright)' }} title={fs.path}>{fileNameOf(fs.path)}
                <span style={{ color: 'var(--text-dimmer)', fontSize: 11, marginLeft: 6 }}>{fs.path.includes('/') ? fs.path.slice(0, fs.path.lastIndexOf('/')) : ''}</span>
              </span>
              <span style={{ flex: '0 0 auto', fontFamily: MONO, fontSize: 11.5 }}>
                {fs.binary ? <span style={{ color: 'var(--text-dimmer)' }}>bin</span> : <><span style={{ color: 'var(--ok)' }}>+{fs.adds}</span> <span style={{ color: 'hsl(0,72%,60%)' }}>−{fs.dels}</span></>}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  )

  // 详情层内容：提交详情 或 文件差异。并排时它是左边那一栏，窄到放不下时盖住列表。
  // 返回与关闭只留一个（与文件预览同一条规矩）：盖着的时候给「←」——底下那层还在，
  // 你要的是退回去；并排的时候给「✕」——列表就在旁边，没有「退回」可言。
  // 两个按钮都调 setDetail(null)，并排时同时画出来等于同一个动作放了两遍。
  const detailBody = (twoPane: boolean) => detail?.kind === 'commit' ? (
    <CommitDetail
      root={root || ''} hash={detail.hash} accent={accent}
      menu={commitActionsMenu(detail.hash, detail.hash.slice(0, 7))}
      onClose={() => setDetail(null)}
      onPickParent={(h) => { setSelHash(h); setDetail({ kind: 'commit', hash: h }) }}
    />
  ) : detail?.kind === 'file' ? (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', borderBottom: '1px solid var(--border-subtle)', flex: '0 0 auto' }}>
        {!twoPane && (
          <button type="button" className="tt-file-close" onClick={() => setDetail(null)} title={t('common.back')} aria-label={t('common.back')}><BackIcon /></button>
        )}
        <span style={{ fontFamily: MONO, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
          <span style={{ color: accent, display: 'inline-flex', verticalAlign: -2 }}><ChevronRight size={12} /></span> {detail.file}
        </span>
        <span style={{ flex: 1 }} />
        {!detail.untracked && !detail.base && (
          <Button size="small" type={detail.staged ? 'primary' : 'default'} onClick={() => setDetail({ ...detail, staged: !detail.staged })}>
            {detail.staged ? t('git.stagedDiff') : t('git.working')}
          </Button>
        )}
        {twoPane && (
          <button type="button" title={t('git.closeDiff')} aria-label={t('git.closeDiff')} className="tt-file-close" onClick={() => setDetail(null)}><CloseIcon /></button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {diffLoading ? <div style={{ height: '100%', display: 'grid', placeItems: 'center' }}><Spin /></div>
          : diff.trim() ? <DiffView text={diff} />
            : <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-dimmer)', fontSize: 13 }}>{t('git.binaryDiff')}</div>}
      </div>
    </>
  ) : null

  const changesList = (
    <div className="tt-git-main">
      {header}
      {banner}

      {!dir && !loading && <div style={{ color: 'var(--text-dimmer)', fontSize: 12, padding: 10 }}>{t('git.noDir')}</div>}
      {status && !status.repo && !loading && <div style={{ color: 'var(--text-dimmer)', fontSize: 12, padding: 10, lineHeight: 1.6 }}>{t('git.notRepo')}</div>}

      {status?.repo && tab === 'changes' && changesPane}
      {status?.repo && tab === 'graph' && (
        <GraphView
          data={graph} loading={graphLoading} selected={selHash}
          onPick={(c) => { setSelHash(c.hash); setDetail({ kind: 'commit', hash: c.hash }) }}
          commitMenu={commitMenu}
          scope={scope} onScope={(v) => { setScope(v); setPages(1) }}
          query={query} onQuery={(v) => { setQuery(v); setPages(1) }}
          onLoadMore={() => setPages((n) => n + 1)}
          wtByBranch={wtByBranch} onWt={gotoWorktree}
          focus={focus}
          onFocusDone={(hash) => {
            setFocus(undefined)
            if (hash) setSelHash(hash)
            else message.info(t('git.graph.notLoaded'))
          }}
        />
      )}
      {status?.repo && tab === 'refs' && (
        <RefsView
          data={refs} loading={refsLoading} accent={accent}
          onLocate={locate}
          onCheckout={(b) => act({ action: 'checkout', ref: b.name }, t('git.refs.checkedOut', { branch: b.name }))}
          branchMenu={branchMenu} remoteMenu={remoteMenu} tagMenu={tagMenu} stashMenu={stashMenu}
          onNewBranch={() => newBranch()} onStashAll={stashAll}
          worktrees={wtAll} currentWt={wt?.path} wtMenu={wtMenu}
          onNewWorktree={() => setWtOpen(true)}
        />
      )}
      {status?.repo && tab === 'base' && basePane}

      {/* W3 底部操作条：合并回 base + Worktree 管理（worktree 态才有） */}
      {wt && tab !== 'graph' && (
        <div style={{ borderTop: '1px solid var(--border-subtle)', padding: 8, display: 'flex', gap: 8, flex: '0 0 auto' }}>
          {!!wt.base && !wt.external && (
            <Dropdown.Button size="small" type="primary" style={{ flex: 1 }} disabled={merging}
              icon={<ChevronDown size={11} />}
              onClick={() => doWtMerge('squash')}
              menu={{ items: [{ key: 'merge', label: 'merge' }, { key: 'rebase', label: 'rebase' }], onClick: ({ key }) => doWtMerge(key as any) }}>
              {merging ? <Spin size="small" /> : t('git.wt.merge', { base: wt.base })}
            </Dropdown.Button>
          )}
          <Button size="small" onClick={() => setWtOpen(true)}>{t('git.wt.manage')}</Button>
        </div>
      )}
    </div>
  )

  // 抽屉里的两层：改动列表钉右缘，详情从它左边长出来（和文件抽屉同一份 <InspectorLayers>）。
  const panel = (
    <div className="tt-git-root">
      <InspectorLayers
        pinned={changesList} pinnedSize={LIST} grownSize={DETAIL}
        handle="gitdetail"
        grown={detail ? (twoPane) => <div className="tt-git-detail">{detailBody(twoPane)}</div> : null}
      />
    </div>
  )

  return (
    <>
      {panel}
      <Suspense fallback={null}>
        <WorktreePanel open={wtOpen} onClose={() => { setWtOpen(false); refresh() }} openTerm={openTerm} initialDir={repoRoot || dir} />
      </Suspense>
      <AskModal spec={ask} onClose={() => setAsk(null)} />
    </>
  )
}

// 分支切换器：头部分支芯片点开的浮层。自己拉 /git/refs，避免没进「分支」tab 时也预取一份。
function BranchSwitcher({ dir, tick, current, onPick, onNew }: {
  dir?: string; tick: number; current?: string; onPick: (name: string) => void; onNew: () => void
}) {
  const { t } = useI18n()
  const [list, setList] = useState<BranchInfo[] | null>(null)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!dir) return
    let stop = false
    api('GET', `/git/refs?dir=${encodeURIComponent(dir)}`)
      .then((r) => { if (!stop) setList(r?.data?.branches || []) })
      .catch(() => { if (!stop) setList([]) })
    return () => { stop = true }
  }, [dir, tick])

  const hits = (list || []).filter((b) => !q.trim() || b.name.toLowerCase().includes(q.trim().toLowerCase()))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <Input size="small" autoFocus allowClear value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={t('git.refs.switchPlaceholder')} />
      <div style={{ maxHeight: 260, overflowY: 'auto', margin: '0 -4px' }}>
        {!list && <div style={{ display: 'grid', placeItems: 'center', padding: 12 }}><Spin size="small" /></div>}
        {list && !hits.length && <div style={{ fontSize: 12, color: 'var(--text-dimmer)', padding: '6px 8px' }}>{t('git.refs.none')}</div>}
        {hits.map((b) => (
          <div key={b.name} className="cc-filerow" onClick={() => b.name !== current && onPick(b.name)}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', borderRadius: 6, cursor: b.name === current ? 'default' : 'pointer' }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%', flex: '0 0 auto',
              background: b.name === current ? 'var(--accent)' : 'transparent', border: b.name === current ? undefined : '1px solid var(--border)',
            }} />
            <span style={{
              flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              fontFamily: MONO, fontSize: 12.5, color: b.name === current ? 'var(--accent)' : 'var(--text-bright)',
              fontWeight: b.name === current ? 600 : 400,
            }} title={b.name}>{b.name}</span>
            <AheadBehind ahead={b.ahead} behind={b.behind} />
          </div>
        ))}
      </div>
      <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
        <button type="button" onClick={onNew}
          style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', border: 0, background: 'transparent', color: 'var(--accent)', fontSize: 12.5, cursor: 'pointer', padding: '2px 4px' }}>
          <PlusIcon />{t('git.refs.newBranch')}
        </button>
      </div>
    </div>
  )
}
