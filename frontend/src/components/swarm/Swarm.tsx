// 蜂群(swarm) 页面：列表 + 详情仪表盘（实时拓扑 / 广场 / 看板 / 节点详情抽屉）。
// 数据全部来自后端 /api/swarms*（透传 ttmux CLI）。设计见 docs/design/蜂群 Web 接入设计.md。
//   一个蜂群 = 一个 master cc(会话 cc-<群>) 带一群 member cc(会话 <群>-<成员>)，每个节点可一键进终端。
//   Web 只读 + 广场/看板轻操作；建群/加成员/接管仍在 CLI。
import { useEffect, useMemo, useRef, useState } from 'react'
import ManagedSwarm from './ManagedSwarm'
import SwarmStudio from './SwarmStudio'
import { pollWhileVisible } from '../../visible-poll'
import { NewSwarmModal } from './NewSwarmModal'
export { NewSwarmModal } from './NewSwarmModal'
import {
  Card, Tag, Empty, Segmented, Input, Select, Button, Drawer, Tooltip,
  App as AntApp, Popconfirm, Modal, Space, Spin, AutoComplete,
} from 'antd'
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd'
import { sessionLabel } from '../sessions/session-label'
import { api, upload } from '../../api'
import { DirPicker, recentDirs, pushRecentDir } from '../sessions/DirPicker'
import { useI18n } from '../../i18n'
import Markdown from '../markdown/Markdown'
import { useLayout } from '../../layout'
import { onEnterSubmit } from '../../enter-submit'
import { BlockIcon, BotIcon, CheckIcon, ChevronLeft, ClockIcon, CloseIcon, DiamondIcon, DotIcon, KeyboardIcon, LinkIcon, MegaphoneIcon, OpenInIcon, QuestionIcon, ReplyIcon, TargetIcon } from '../../icons'

// ── 配色（与 App.tsx 一致） ──
const C = {
  bg: 'var(--bg-base)', bg2: 'var(--bg-container)', bg3: 'var(--bg-term)', line: 'var(--border-subtle)', line2: 'var(--border)',
  fg: 'var(--text-bright)', fg2: 'var(--text-dim)', fg3: 'var(--text-dimmer)',
  blue: 'var(--accent)', green: 'var(--ok)', amber: '#d29922', red: '#f85149', magenta: '#d2a8ff', cyan: '#39c5cf',
}
const COLS = ['backlog', 'assigned', 'doing', 'review', 'done', 'blocked'] as const
type Col = typeof COLS[number]
const COL_COLOR: Record<Col, string> = { backlog: C.fg2, assigned: C.blue, doing: C.amber, review: C.cyan, done: C.green, blocked: C.red }
type T = (key: string, vars?: Record<string, string | number>) => string
const colLabel = (t: T, col: Col) => t(`swarm.board.col.${col}`)
const swarmStatusLabel = (t: T, status: string) => t(`swarm.status.${status}`)
const isLeaderRole = (role?: string) => role === 'leader' || role === 'master'
const isLeaderAuthor = (author?: string) => author === 'leader' || author === 'master'
const authorLabel = (author: string, t: T) => isLeaderAuthor(author) ? t('swarm.master') : author
const displayPostText = (text: string) => text.replace(/(^|\s)@master\b/g, '$1@leader')
const memberNodeKind = (m: Member) => m.done ? 'done' : ['running', 'idle', 'waiting', 'done'].includes(m.status) ? m.status : 'exited'

interface SwarmRow { id: string; label?: string; name: string; goal: string; status: string; supervisor: string; created: string; total: number; alive: number; pending: number }
interface Member { name: string; type: string; task: string; deps: string; done: number; status: string; session: string; kind?: string; role?: string; subrole?: string; duty?: string }
interface Pending { name: string; deps: string }
interface Detail { name: string; goal: string; status: string; supervisor: string; created: string; leader_last_post?: number; members: Member[]; pending: Pending[]; done_marked: string[] }
interface Post { id: number; ts: string; author: string; kind: string; re: number | null; text: string }
interface CardT { id: string; title: string; descr: string; assignee: string; col: string; deps: string; updated: string }

function statusTag(status: string, t: T) {
  const map: Record<string, [string, string]> = {
    running: [C.amber, t('common.running')], done: [C.green, t('common.done')],
    integrating: [C.cyan, t('swarm.status.integrating')], planning: [C.fg2, t('swarm.status.planning')], archived: [C.fg3, t('swarm.status.archived')],
  }
  const [c, label] = map[status] || [C.fg2, status || t('swarm.status.planning')]
  return <Tag style={{ color: c, borderColor: c + '66', background: c + '14', margin: 0 }}>{label}</Tag>
}

export default function Swarm({ openTerm, initialSwarm, onNav }: { openTerm: (n: string) => void; initialSwarm?: string; onNav?: (name: string | null) => void }) {
  // 选中态以 URL hash 为唯一来源（深链 #/swarm/<名> 可直达/分享/后退）
  const sel = initialSwarm || null
  const nav = onNav || (() => {})
  const [list, setList] = useState<SwarmRow[]>([])
  const loadList = (signal?: AbortSignal) => api('GET', '/swarms', undefined, { signal }).then((r) => { if (!signal?.aborted) setList(Array.isArray(r) ? r : []) })
  useEffect(() => {
    if (sel) return
    return pollWhileVisible(signal => loadList(signal), 10000).stop
  }, [sel])

  if (sel?.startsWith('sw-')) return <ManagedSwarm key={sel} id={sel} onBack={() => nav(null)} openTerm={openTerm} />
  if (sel) return <SwarmDetail name={sel} onBack={() => nav(null)} openTerm={openTerm} onGone={() => { nav(null); loadList() }} />
  return <SwarmList list={list} onOpen={(n) => nav(n)} reload={() => { void loadList() }} />
}

// ── 列表页 ──
const SWARM_STATUSES = ['running', 'planning', 'integrating', 'done', 'archived'] as const
function SwarmList({ list, onOpen, reload }: { list: SwarmRow[]; onOpen: (n: string) => void; reload: () => void }) {
  const { t } = useI18n()
  const [creating, setCreating] = useState(false)
  // 默认只看「活跃」（非归档）；归档的蜂群需点「归档」筛选才显示
  const [status, setStatus] = useState<string>('active')
  const norm = (st: string) => st || 'planning'
  const isArchived = (s: SwarmRow) => norm(s.status) === 'archived'
  const count = (f: string) => f === 'active'
    ? list.filter((s) => !isArchived(s)).length
    : list.filter((s) => norm(s.status) === f).length
  // 活跃在前 + 实际存在的非归档子状态；归档单列最后（默认不展示）
  const options = [
    { label: `${t('swarm.active')} ${count('active')}`, value: 'active' },
    ...SWARM_STATUSES.filter((st) => st !== 'archived' && count(st) > 0).map((st) => ({ label: `${swarmStatusLabel(t, st)} ${count(st)}`, value: st })),
    ...(count('archived') > 0 ? [{ label: `${swarmStatusLabel(t, 'archived')} ${count('archived')}`, value: 'archived' }] : []),
  ]
  const shown = status === 'active' ? list.filter((s) => !isArchived(s)) : list.filter((s) => norm(s.status) === status)
  return (
    // 页面头与「项目」页同款（全站统一：标题 16/700 起于 tt-page 左上角，操作靠右），
    // 不再套 antd Card——卡头会把标题多缩进一层，五页起点就不齐了。
    <div style={{ width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 16, fontWeight: 700 }}>{t('nav.swarm')}</span>
        <Tag style={{ margin: 0 }}>{count('active')}</Tag>
        <span style={{ flex: 1 }} />
        <Button type="primary" size="small" onClick={() => setCreating(true)}>+ {t('swarm.new')}</Button>
      </div>
      {/* 按状态过滤 */}
      {list.length > 0 && options.length > 1 && (
        <Segmented value={status} onChange={(v) => setStatus(v as string)} options={options} style={{ marginBottom: 14 }} />
      )}
      {list.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span style={{ color: C.fg2 }}>{t('swarm.empty')}</span>}>
            <Button type="primary" onClick={() => setCreating(true)}>+ {t('swarm.newFirst')}</Button>
          </Empty>
        </div>
      ) : shown.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span style={{ color: C.fg2 }}>{t('swarm.noStatus', { status: status === 'active' ? t('swarm.active') : swarmStatusLabel(t, status) })}</span>} />
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: 14 }}>
          {shown.map((s) => <SwarmCard key={s.id || s.name} s={s} onOpen={onOpen} />)}
        </div>
      )}
      <NewSwarmModal open={creating} onClose={() => setCreating(false)} onDone={reload} />
    </div>
  )
}

function SwarmCard({ s, onOpen }: { s: SwarmRow; onOpen: (n: string) => void }) {
  const { t } = useI18n()
  const accent = s.status === 'running' ? C.amber : s.status === 'done' ? C.green : s.status === 'archived' ? C.fg3 : C.blue
  const exited = Math.max(0, s.total - s.alive)
  const [hover, setHover] = useState(false)
  return (
    <div onClick={() => onOpen(s.name)} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative', background: C.bg2, border: `1px solid ${hover ? accent + '88' : C.line2}`, borderRadius: 12,
        padding: '14px 16px 13px', cursor: 'pointer', overflow: 'hidden', transition: 'border-color .15s, transform .15s',
        transform: hover ? 'translateY(-2px)' : 'none',
      }}>
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: accent }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ color: C.magenta, display: 'inline-flex' }}><DiamondIcon size={12} /></span>
        <span style={{ fontSize: 16, fontWeight: 700, color: C.fg }}>{s.label || s.name}</span>
        <span style={{ marginLeft: 'auto' }}>{statusTag(s.status, t)}</span>
      </div>
      <div style={{ color: s.goal ? C.fg2 : C.fg3, fontSize: 13, marginBottom: 12, minHeight: 19, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
        {s.goal || t('overview.noGoal')}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center', flexWrap: 'wrap' }}>
          {s.supervisor && <i title={s.supervisor} style={{ width: 8, height: 8, borderRadius: '50%', background: C.magenta }} />}
          {Array.from({ length: Math.min(s.alive, 10) }).map((_, i) => <i key={'a' + i} style={{ width: 8, height: 8, borderRadius: '50%', background: C.green }} />)}
          {Array.from({ length: Math.min(s.pending, 10) }).map((_, i) => <i key={'p' + i} style={{ width: 8, height: 8, borderRadius: '50%', background: C.amber }} />)}
          {Array.from({ length: Math.min(exited, 10) }).map((_, i) => <i key={'e' + i} style={{ width: 8, height: 8, borderRadius: '50%', background: C.line2 }} />)}
          {s.total + s.pending === 0 && !s.supervisor && <span style={{ color: C.fg3, fontSize: 12 }}>{t('swarm.noMembers')}</span>}
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center', fontSize: 12, color: C.fg2, flexWrap: 'wrap' }}>
          {s.supervisor && <span style={{ color: C.magenta, display: 'inline-flex', alignItems: 'center', gap: 4 }}><DiamondIcon size={9} />{t('swarm.master')}</span>}
          {(s.total + s.pending) > 0 && <span>{t('swarm.memberSummary', { total: s.total, alive: s.alive })}</span>}
          {(s.total + s.pending) === 0 && !s.supervisor && <span style={{ color: C.fg3 }}>{t('swarm.noMembers')}</span>}
          {s.pending > 0 && <span style={{ color: C.amber }}>+{s.pending} {t('swarm.pendingUnlock')}</span>}
        </span>
      </div>
      <div style={{ marginTop: 10, paddingTop: 9, borderTop: `1px solid ${C.line}`, display: 'flex', alignItems: 'center', fontSize: 11.5, color: C.fg3, flexWrap: 'wrap', gap: 4 }}>
        <span style={{ color: s.supervisor ? C.magenta : C.fg3, display: 'inline-flex', alignItems: 'center', gap: 4 }}>{s.supervisor ? <><DiamondIcon size={9} />{s.supervisor}</> : t('swarm.noSupervisor')}</span>
        <span style={{ marginLeft: 'auto' }}>{(s.created || '').slice(5, 16)}</span>
      </div>
    </div>
  )
}

// initialDir/lockDir：项目页入口预填并锁定目录（09 §3——「在项目里创建」的含义）。
// roster/worktree 是 09 §4 的上下文字段：只写进指挥开场白，编排权仍在指挥。
function LegacyNewSwarmModal({ open, onClose, onDone, initialDir, lockDir }: {
  open: boolean; onClose: () => void; onDone: (name?: string) => void
  initialDir?: string; lockDir?: boolean
}) {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [name, setName] = useState(''); const [goal, setGoal] = useState(''); const [master, setMaster] = useState(true)
  const [dir, setDir] = useState(''); const [pick, setPick] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [subroles, setSubroles] = useState<{ key: string; label: string; icon?: string }[]>([])
  const [roster, setRoster] = useState<string[]>([])
  const [worktree, setWorktree] = useState(true)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const dirRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    if (!open) return
    setName(''); setGoal(''); setMaster(true); setDir(initialDir || ''); setFiles([]); setRoster([]); setWorktree(!!lockDir)
    api('GET', '/swarm/subroles').then((r) => setSubroles(Array.isArray(r) ? r : [])).catch(() => {})
  }, [open, initialDir, lockDir])
  const addFiles = (fl: FileList | null) => { if (fl?.length) setFiles((prev) => [...prev, ...Array.from(fl)]) }
  // webkitdirectory 非标准属性，React 类型里没有，用回调 ref 在 DOM 上补
  const setDirInput = (el: HTMLInputElement | null) => {
    if (el) { el.setAttribute('webkitdirectory', ''); el.setAttribute('directory', '') }
    dirRef.current = el
  }
  const ok = async () => {
    if (!name.trim()) return message.error(t('swarm.nameRequired'))
    if (files.length && !dir.trim()) return message.error(t('swarm.dirRequiredForUpload'))
    setBusy(true)
    try {
      const hasFiles = files.length > 0
      // 默认带 Leader 的行为保持原样：无文档时 swarm new 内部原子拉起 Leader。
      // 仅当要先上传文档时，才拆成 建群(不带 Leader)→上传→adopt，确保文档先就位。
      // roster/worktree 只影响指挥开场白（09 §4），adopt 时序同样带上，上下文不丢。
      await api('POST', '/swarms', { name: name.trim(), goal: goal.trim(), dir: dir.trim(), master: master && !hasFiles, roster, worktree })
      if (hasFiles) {
        const r = await upload(dir.trim(), files)
        message.success(t('swarm.uploaded', { count: r.saved.length, dir: r.dir }))
        if (master) await api('POST', `/swarms/${encodeURIComponent(name.trim())}/adopt`, { dir: dir.trim(), roster, worktree })
      }
      // 班子建议同步建看板卡（09 S2）：每个建议角色一张待办卡，指挥上板即见；
      // 仍不建成员——组建谁、怎么派活的决定权在指挥。建卡失败不阻塞建群。
      for (const key of roster) {
        const label = subroles.find((r) => r.key === key)?.label || key
        await api('POST', `/swarms/${encodeURIComponent(name.trim())}/task`, {
          title: t('swarm.rosterCardTitle', { role: label }),
          desc: t('swarm.rosterCardDesc'),
        }).catch(() => {})
      }
      if (dir.trim()) pushRecentDir(dir.trim())
      message.success(master ? t('swarm.createdWithMaster') : t('swarm.created'))
      onClose(); onDone(name.trim())
    } catch (e: any) { message.error(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <Modal open={open} onCancel={onClose} onOk={ok} okText={t('file.create')} confirmLoading={busy} title={t('swarm.new')} destroyOnClose>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input placeholder={t('swarm.namePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} autoFocus onPressEnter={onEnterSubmit(ok)} />
          <Input.TextArea rows={2} placeholder={t('swarm.goalPlaceholder')} value={goal} onChange={(e) => setGoal(e.target.value)} />
          {lockDir ? (
            <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12, color: C.fg2, padding: '6px 10px', border: `1px solid ${C.line}`, borderRadius: 6 }} title={dir}>{dir}</div>
          ) : (
            <Space.Compact style={{ width: '100%' }}>
              <AutoComplete style={{ flex: 1 }} value={dir} onChange={setDir}
                options={recentDirs().map((d) => ({ value: d }))}
                filterOption={(input, opt) => String(opt?.value).toLowerCase().includes(input.toLowerCase())}
                placeholder={t('swarm.dirPlaceholder')} />
              <Button onClick={() => setPick(true)}>{t('common.browse')}</Button>
            </Space.Compact>
          )}
          {/* 班子建议：只写进指挥开场白，最终由指挥按 dev-roles 拆定（09 §3） */}
          {subroles.length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: C.fg2, marginBottom: 5 }}>{t('swarm.rosterLabel')}</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {subroles.map((r) => {
                  const on = roster.includes(r.key)
                  return (
                    <Tag.CheckableTag key={r.key} checked={on}
                      onChange={(v) => setRoster((prev) => (v ? [...prev, r.key] : prev.filter((x) => x !== r.key)))}>
                      {r.icon} {r.label}
                    </Tag.CheckableTag>
                  )
                })}
              </div>
              {roster.length > 5 && <div style={{ fontSize: 12, color: '#d29922', marginTop: 4 }}>{t('swarm.rosterTooMany')}</div>}
            </div>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: C.fg2, fontSize: 13 }}>
            <input type="checkbox" checked={worktree} onChange={(e) => setWorktree(e.target.checked)} />
            {t('swarm.wtPolicy')}
          </label>
          <div>
            <input ref={fileRef} type="file" multiple style={{ display: 'none' }}
              onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
            <input ref={setDirInput} type="file" multiple style={{ display: 'none' }}
              onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
            <Space wrap>
              <Button size="small" onClick={() => fileRef.current?.click()}>{t('swarm.uploadFiles')}</Button>
              <Button size="small" onClick={() => dirRef.current?.click()}>{t('swarm.uploadFolder')}</Button>
              {files.length > 0 && (
                <Tag closable color="blue" onClose={() => setFiles([])}>{t('swarm.filesSelected', { count: files.length })}</Tag>
              )}
            </Space>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: C.fg2, fontSize: 13 }}>
            <input type="checkbox" checked={master} onChange={(e) => setMaster(e.target.checked)} />
            {t('swarm.autoMaster', { name: name || t('swarm.defaultName') })}
          </label>
        </Space>
      </Modal>
      <DirPicker open={pick} start={dir || undefined} onPick={(p) => { setDir(p); setPick(false) }} onClose={() => setPick(false)} />
    </>
  )
}

// ── 详情仪表盘 ──
function SwarmDetail({ name, onBack, openTerm, onGone }: { name: string; onBack: () => void; openTerm: (n: string) => void; onGone: () => void }) {
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [cards, setCards] = useState<CardT[]>([])
  const [posts, setPosts] = useState<Post[]>([])
  const [focus, setFocus] = useState<string | null>(null)   // 聚焦成员（跨面板联动）
  const [drawer, setDrawer] = useState<string | null>(null) // 抽屉里的成员
  const [lowerView, setLowerView] = useState<'board' | 'inbox'>('board')
  const [narrow, setNarrow] = useState(false)
  const [adding, setAdding] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const lastId = useRef(0)

  const reloadDetail = () => api('GET', `/swarms/${encodeURIComponent(name)}`).then(setDetail).catch(() => {})

  // 自身宽度 < 860 → 页签；否则仪表盘（终端停靠会压窄内容区，量自身比量视口准）
  useEffect(() => {
    const el = rootRef.current; if (!el) return
    const ro = new ResizeObserver((es) => setNarrow(es[0].contentRect.width < 860))
    ro.observe(el); return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const loadDetail = reloadDetail
    const loadBoard = () => api('GET', `/swarms/${encodeURIComponent(name)}/board`).then((r) => setCards(Array.isArray(r) ? r : [])).catch(() => {})
    const loadFeed = () => api('GET', `/swarms/${encodeURIComponent(name)}/feed?since=${lastId.current}`)
      .then((r) => {
        const arr: Post[] = Array.isArray(r) ? r : []
        if (arr.length) {
          lastId.current = arr[arr.length - 1].id
          setPosts((p) => (lastId.current && p.length ? [...p, ...arr] : arr))
        }
      }).catch(() => {})
    loadDetail(); loadBoard(); loadFeed()
    const t1 = setInterval(loadDetail, 3000), t2 = setInterval(loadBoard, 3000), t3 = setInterval(loadFeed, 2000)
    return () => { clearInterval(t1); clearInterval(t2); clearInterval(t3) }
  }, [name])

  const onNode = (m: string) => { setFocus(m); setDrawer(m) }
  const closeDrawer = () => { setDrawer(null); setFocus(null) }
  const enc = encodeURIComponent(name)
  const markDone = (member?: string) =>
    api('POST', `/swarms/${enc}/done`, member ? { member } : {}).then(() => { message.success(member ? t('swarm.memberMarkedDone', { member }) : t('swarm.allMarkedDone')); reloadDetail() }).catch((e: any) => message.error(e.message))
  const activate = (member?: string, force?: boolean) =>
    api('POST', `/swarms/${enc}/activate`, { member: member || '', force: !!force }).then(() => { message.success(t('swarm.unlocked')); reloadDetail() }).catch((e: any) => message.error(e.message))
  const archive = () => modal.confirm({
    title: t('swarm.archiveConfirmTitle', { name }), content: t('swarm.archiveConfirmContent'),
    okText: t('swarm.archive'), okButtonProps: { danger: true },
    onOk: async () => { try { await api('DELETE', `/swarms/${enc}`); message.success(t('swarm.archived')); onGone() } catch (e: any) { message.error(e.message) } },
  })

  const topo = <Topology detail={detail} swarm={name} cards={cards} posts={posts} focus={focus} onNode={onNode} />
  const plaza = <Plaza name={name} posts={posts} focus={focus} />
  const board = <Board name={name} cards={cards} focus={focus} onCard={(c) => onNode(c.assignee)} reload={() => api('GET', `/swarms/${encodeURIComponent(name)}/board`).then((r) => setCards(Array.isArray(r) ? r : [])).catch(() => {})} setCards={setCards} />
  const inbox = <Inbox detail={detail} cards={cards} posts={posts} onNode={onNode} />

  return (
    <div ref={rootRef} style={{ display: 'flex', flexDirection: 'column', height: 'calc(100dvh - 32px)', minHeight: 0 }}>
      {/* 顶部条 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 2px 12px', flexWrap: 'wrap' }}>
        <a onClick={onBack} style={{ color: C.fg2, display: 'inline-flex', alignItems: 'center', gap: 4 }}><ChevronLeft size={13} />{t('nav.swarm')}</a>
        <span style={{ fontSize: 17, fontWeight: 700 }}>{name}</span>
        {detail?.goal && (
          <Tooltip title={<div style={{ maxHeight: '60vh', overflow: 'auto', whiteSpace: 'pre-wrap' }}>{detail.goal}</div>} overlayStyle={{ maxWidth: 520 }}>
            <span style={{ color: C.fg2, fontSize: 13, maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{detail.goal}</span>
          </Tooltip>
        )}
        {detail && statusTag(detail.status, t)}
        {detail?.supervisor && <span style={{ color: C.magenta, fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}><DiamondIcon size={9} />{detail.supervisor}</span>}
        {detail && (
          <span style={{ color: C.fg2, fontSize: 12 }}>
            {t('swarm.memberSummary', { total: detail.members.length, alive: detail.members.filter((m) => ['running', 'idle', 'waiting'].includes(m.status)).length })}{detail.pending.length ? <> · <span style={{ color: C.amber }}>{t('swarm.pendingSummary', { count: detail.pending.length })}</span></> : null}
          </span>
        )}
        {detail && (
          <Space style={{ marginLeft: 'auto' }}>
            <Button size="small" type="primary" onClick={() => setAdding(true)}>+ {t('swarm.member')}</Button>
            {detail.pending.length > 0 && <Button size="small" onClick={() => activate()}>{t('swarm.unlockPending')}</Button>}
            <Tooltip title={t('swarm.archiveTooltip')}><Button size="small" danger onClick={archive}>{t('swarm.archive')}</Button></Tooltip>
          </Space>
        )}
      </div>

      {!detail ? <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Spin /></div> : narrow ? (
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 10, paddingBottom: 4 }}>
          <div style={{ flex: '0 0 320px', minHeight: 0 }}>{topo}</div>
          <div style={{ flex: '0 0 280px', minHeight: 0 }}>{plaza}</div>
          <Segmented block value={lowerView} onChange={(v) => setLowerView(v as any)}
            options={[{ label: t('swarm.board'), value: 'board' }, { label: t('swarm.inbox'), value: 'inbox' }]} />
          <div style={{ flex: '0 0 330px', minHeight: 0 }}>{lowerView === 'inbox' ? inbox : board}</div>
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateRows: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12 }}>
          <div className="tt-2col" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, minHeight: 0, minWidth: 0 }}>
            {topo}{plaza}
          </div>
          <div className="tt-2col" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, minHeight: 0, minWidth: 0 }}>
            {board}{inbox}
          </div>
        </div>
      )}

      <NodeDrawer swarm={name} member={drawer} detail={detail} cards={cards} posts={posts} openTerm={openTerm} onClose={closeDrawer}
        onDone={markDone} onActivate={activate} />
      <AddMemberModal open={adding} name={name} members={detail?.members.map((m) => m.name) || []} onClose={() => setAdding(false)} onDone={reloadDetail} />
    </div>
  )
}

function AddMemberModal({ open, name, members, onClose, onDone }: { open: boolean; name: string; members: string[]; onClose: () => void; onDone: () => void }) {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [mname, setMname] = useState(''); const [task, setTask] = useState(''); const [type, setType] = useState('agent')
  const [deps, setDeps] = useState<string[]>([]); const [dir, setDir] = useState(''); const [busy, setBusy] = useState(false)
  const [kind, setKind] = useState('claude') // 引擎: claude(默认) | codex
  const [subrole, setSubrole] = useState<string | undefined>(undefined); const [duty, setDuty] = useState('') // 细分角色 + 职责
  useEffect(() => { if (open) { setMname(''); setTask(''); setType('agent'); setDeps([]); setDir(''); setKind('claude'); setSubrole(undefined); setDuty('') } }, [open])
  const willBeLeader = type === 'agent' && members.length === 0 // 首个 agent 成员 → leader（最终由后端按真实状态裁定）
  const ok = async () => {
    if (!mname.trim()) return message.error(t('swarm.memberNameRequired'))
    if (!task.trim()) return message.error(type === 'agent' ? t('task.descriptionRequired') : t('swarm.commandRequired'))
    setBusy(true)
    try {
      await api('POST', `/swarms/${encodeURIComponent(name)}/members`, { name: mname.trim(), type, task: task.trim(), deps: deps.join(','), dir: dir.trim(), kind, subrole: subrole || '', duty: duty.trim() })
      message.success(deps.length ? t('swarm.memberPending', { member: mname }) : t('swarm.memberStarted', { member: mname }))
      onClose(); onDone()
    } catch (e: any) { message.error(e.message) } finally { setBusy(false) }
  }
  return (
    <Modal open={open} onCancel={onClose} onOk={ok} okText={t('swarm.addMember')} confirmLoading={busy} title={t('swarm.addMember')} destroyOnClose>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Segmented block value={type} onChange={(v) => setType(v as string)}
          options={[
            { label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><BotIcon size={12} />Agent</span>, value: 'agent' },
            { label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><KeyboardIcon size={12} />{t('common.command')}</span>, value: 'task' },
          ]} />
        {type === 'agent' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: C.fg2, fontSize: 12, whiteSpace: 'nowrap' }}>{t('swarm.engine')}</span>
            <Segmented value={kind} onChange={(v) => setKind(v as string)}
              options={[{ label: 'Claude', value: 'claude' }, { label: 'Codex', value: 'codex' }]} />
            <span style={{ flex: 1 }} />
            <Tag color={willBeLeader ? 'magenta' : 'default'} bordered={false}>
              {willBeLeader ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><DiamondIcon size={9} />{t('swarm.masterFirst')}</span> : t('swarm.member')}
            </Tag>
          </div>
        )}
        <Input placeholder={t('swarm.memberNamePlaceholder')} value={mname} onChange={(e) => setMname(e.target.value)} autoFocus />
        {type === 'agent' && (
          <Select showSearch allowClear style={{ width: '100%' }} placeholder={t('swarm.subrolePlaceholder')} value={subrole}
            onChange={(v) => setSubrole(v)} optionFilterProp="label"
            options={SUBROLES.filter((s) => s.key !== 'commander').map((s) => ({ value: s.key, label: `${s.icon} ${subroleText(t, s.key)}` }))} />
        )}
        {type === 'agent' && <Input.TextArea rows={2} placeholder={t('swarm.dutyPlaceholder')} value={duty} onChange={(e) => setDuty(e.target.value)} />}
        <Input.TextArea rows={2} placeholder={type === 'agent' ? t('swarm.taskPlaceholder') : t('swarm.shellCommand')} value={task} onChange={(e) => setTask(e.target.value)} />
        {type === 'agent' && <Input placeholder={t('swarm.workdirPlaceholder')} value={dir} onChange={(e) => setDir(e.target.value)} />}
        <div>
          <div style={{ color: C.fg2, fontSize: 12, marginBottom: 4 }}>{t('swarm.depsLabel')}</div>
          <Select mode="multiple" allowClear style={{ width: '100%' }} placeholder={t('swarm.depsPlaceholder')} value={deps} onChange={setDeps}
            options={members.filter((m) => m !== mname).map((m) => ({ value: m, label: m }))} />
        </div>
      </Space>
    </Modal>
  )
}

// 面板外壳
function Panel({ title, extra, children }: { title: React.ReactNode; extra?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ background: C.bg2, border: `1px solid ${C.line2}`, borderRadius: 10, display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', borderBottom: `1px solid ${C.line}`, fontSize: 13, color: C.fg2, flex: '0 0 auto' }}>
        {title}{extra && <span style={{ marginLeft: 'auto' }}>{extra}</span>}
      </div>
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>{children}</div>
    </div>
  )
}

// ── 实时拓扑（自绘 SVG，分层 DAG + 可拖拽节点卡） ──
function Topology({ detail, swarm, cards, posts, focus, onNode }: {
  detail: Detail | null; swarm: string; cards: CardT[]; posts: Post[]; focus: string | null; onNode: (m: string) => void
}) {
  const { t } = useI18n()
  const wrapRef = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState({ w: 0, h: 0 })
  const [view, setView] = useState<'office' | 'graph'>('office')
  const compactOffice = view === 'office' && viewport.w > 0 && viewport.w < 560
  const layout = useMemo(() => buildLayout(detail, swarm, compactOffice), [detail, swarm, compactOffice])
  const canvasW = Math.max(layout.w, Math.floor(viewport.w - 16), view === 'office' ? 320 : 420)
  const canvasH = Math.max(layout.h, Math.floor(viewport.h - 16), view === 'office' ? 280 : 320)
  const bounds = useMemo(() => {
    if (layout.nodes.length === 0) return { minX: 0, minY: 0, w: layout.w, h: layout.h }
    const minX = Math.min(...layout.nodes.map((n) => n.x))
    const minY = Math.min(...layout.nodes.map((n) => n.y))
    const maxX = Math.max(...layout.nodes.map((n) => n.x + n.w))
    const maxY = Math.max(...layout.nodes.map((n) => n.y + n.h))
    return { minX, minY, w: maxX - minX, h: maxY - minY }
  }, [layout.nodes, layout.w, layout.h])
  const initialOffsetX = view === 'office' ? Math.max(0, (canvasW - bounds.w) / 2) - bounds.minX : Math.max(0, (canvasW - layout.w) / 2)
  const initialOffsetY = view === 'office' ? Math.max(0, (canvasH - bounds.h) / 2) - bounds.minY : 0
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>({})
  const drag = useRef<{ name: string; dx: number; dy: number; sx: number; sy: number; moved: boolean } | null>(null)
  const userPositioned = useRef(false)
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setViewport({ w: entry.contentRect.width, h: entry.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    userPositioned.current = false
    setPos({})
  }, [view, compactOffice])
  useEffect(() => {
    setPos((prev) => {
      const next: Record<string, { x: number; y: number }> = {}
      layout.nodes.forEach((n) => {
        next[n.name] = userPositioned.current && prev[n.name] ? prev[n.name] : { x: n.x + initialOffsetX, y: n.y + initialOffsetY }
      })
      return next
    })
  }, [layout.nodes, initialOffsetX, initialOffsetY])
  const shown = useMemo(() => layout.nodes.map((n) => ({ ...n, x: pos[n.name]?.x ?? n.x, y: pos[n.name]?.y ?? n.y })), [layout.nodes, pos])
  const nodeByName = useMemo(() => Object.fromEntries(shown.map((n) => [n.name, n])), [shown])
  const pathFor = (e: { from: string; to: string; kind: 'cmd' | 'dep' }) => {
    const a = nodeByName[e.from], b = nodeByName[e.to]
    if (!a || !b) return ''
    return `M${a.x + a.w / 2} ${a.y + a.h} C${a.x + a.w / 2} ${a.y + a.h + 34}, ${b.x + b.w / 2} ${b.y - 34}, ${b.x + b.w / 2} ${b.y}`
  }
  const clientToSvg = (svg: SVGSVGElement, e: React.PointerEvent) => {
    const pt = svg.createSVGPoint()
    pt.x = e.clientX; pt.y = e.clientY
    return pt.matrixTransform(svg.getScreenCTM()?.inverse())
  }
  const startDrag = (e: React.PointerEvent<SVGGElement>, n: any) => {
    const svg = e.currentTarget.ownerSVGElement
    if (!svg) return
    const pt = clientToSvg(svg, e)
    drag.current = { name: n.name, dx: pt.x - n.x, dy: pt.y - n.y, sx: e.clientX, sy: e.clientY, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const moveDrag = (e: React.PointerEvent<SVGGElement>) => {
    const d = drag.current
    const svg = e.currentTarget.ownerSVGElement
    if (!d || !svg) return
    const pt = clientToSvg(svg, e)
    const current = shown.find((n) => n.name === d.name)
    const nw = current?.w || 220
    const nh = current?.h || 164
    const nx = Math.max(10, Math.min(canvasW - nw - 10, pt.x - d.dx))
    const ny = Math.max(10, Math.min(canvasH - nh - 10, pt.y - d.dy))
    if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) > 4) {
      d.moved = true
      userPositioned.current = true
    }
    setPos((p) => ({ ...p, [d.name]: { x: nx, y: ny } }))
  }
  const endDrag = (e: React.PointerEvent<SVGGElement>, name: string) => {
    const d = drag.current
    drag.current = null
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch {}
    if (!d?.moved) onNode(name)
  }
  if (view === 'office') return <Panel title={t('swarm.topologyTitle')} extra={<button type="button" className="tt-act" onClick={() => setView('graph')}>{t('swarm.topology.view.graph')}</button>}>
    <SwarmStudio nodes={[
      ...(detail?.supervisor ? [{ id: detail.supervisor, name: t('swarm.master'), executor: 'claude', main: true, state: 'idle' }] : []),
      ...(detail?.members || []).filter(member => member.session !== detail?.supervisor).map(member => ({ id: member.name, name: member.name, executor: member.kind || 'claude', state: member.status === 'done' ? 'idle' : member.status === 'waiting' ? 'blocked' : member.status })),
    ]} selected={focus || ''} onSelect={onNode} />
  </Panel>
  return (
    <Panel title={<><span>{t('swarm.topologyTitle')}</span></>} extra={<Space size={6} wrap>
      <Segmented size="small" value={view} onChange={(v) => setView(v as 'office' | 'graph')}
        options={[{ label: t('swarm.topology.view.office'), value: 'office' }, { label: t('swarm.topology.view.graph'), value: 'graph' }]} />
      <span style={{ fontSize: 11, color: C.fg3 }}>{t('swarm.topologyHelp')}</span>
    </Space>}>
      <div ref={wrapRef} style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 8 }}>
        {layout.nodes.length === 0 ? <Empty description={t('swarm.noMembersAdd')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
          <svg viewBox={`0 0 ${canvasW} ${canvasH}`} width={canvasW} height={canvasH} preserveAspectRatio="xMinYMin meet"
            style={{ display: 'block', margin: '0 auto', width: '100%', height: '100%', minHeight: 300, touchAction: 'none' }}>
            <defs>
              <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill={C.green} /></marker>
              <filter id="nodeGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="officeShadow" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="16" stdDeviation="10" floodColor="#000000" floodOpacity=".16" />
              </filter>
            </defs>

            {view === 'graph' && layout.edges.map((e, i) => (
              <path key={i} d={pathFor(e)} fill="none" stroke={e.kind === 'cmd' ? C.fg2 : C.green} strokeWidth={e.kind === 'cmd' ? 1.2 : 1.7}
                strokeDasharray={e.kind === 'cmd' ? '4 4' : undefined} opacity={e.kind === 'cmd' ? 0.55 : 0.95} markerEnd={e.kind === 'dep' ? 'url(#arr)' : undefined} />
            ))}
            {shown.map((n) => {
              const col = nodeColor(n)
              const dim = focus && focus !== n.name && n.role !== 'leader'
              const running = n.kind === 'running'
              const assigned = cards.filter((c) => c.assignee === n.name)
              const lastPost = posts.filter((p) => p.author === n.name).slice(-1)[0]
              const labelPad = 0
              return (
                <g key={n.name} className="swarm-topology-node" style={{ cursor: 'grab', opacity: dim ? 0.35 : 1 }}
                  onPointerDown={(e) => startDrag(e, n)} onPointerMove={moveDrag} onPointerUp={(e) => endDrag(e, n.name)} onPointerCancel={() => { drag.current = null }}>
                  {running && <rect className="swarm-topology-pulse" x={n.x - 5} y={n.y - 5} width={n.w + 10} height={n.h + 10} rx={14} fill="none" stroke={col} strokeWidth={1.4} filter="url(#nodeGlow)" />}
                  {/* office 视图名字药丸浮在节点上方(top:-18px)，顶部留出 labelPad 高度并允许溢出，否则会被 foreignObject 裁掉 */}
                  <foreignObject x={n.x} y={n.y - labelPad} width={n.w} height={n.h + labelPad} style={{ overflow: 'visible' }}>
                    <div style={{ height: '100%', paddingTop: labelPad, boxSizing: 'border-box' }}>

                      <div className={`swarm-node-card ${running ? 'is-running' : ''} ${n.kind === 'idle' ? 'is-idle' : ''} ${n.kind === 'waiting' ? 'is-waiting' : ''} ${n.kind === 'pending' ? 'is-pending' : ''}`} style={{ ['--node-accent' as any]: col }}>
                        <div className="swarm-node-head">
                          <span className="swarm-node-mark">{nodeIcon(n)}</span>
                          <span className="swarm-node-name">{isLeaderRole(n.mrole) ? <DiamondIcon size={10} /> : null}{n.name}</span>
                          <span className="swarm-node-status">{nodeStatus(n, t)}</span>
                        </div>
                        <div className="swarm-node-meta">
                          {subroleKey(n) ? <span style={{ color: memberHatColor(n) }}>{(SUBROLE_MAP[subroleKey(n)!]?.icon || '👤')} {subroleText(t, subroleKey(n))}</span> : <span>{nodeRole(n, t)}</span>}
                          {n.mkind && <span>{n.mkind}</span>}
                          {n.session && <span title={n.session}>{sessionLabel(n.session)}</span>}
                        </div>
                        {n.mduty && <div className="swarm-node-task" style={{ color: C.fg2 }}>{n.mduty}</div>}
                        {n.task && <div className="swarm-node-task">{n.task}</div>}
                        <div className="swarm-node-foot">
                          <span>{t('swarm.nodeCardsShort', { count: assigned.length })}</span>
                          <span>{t('swarm.nodePostsShort', { count: posts.filter((p) => p.author === n.name).length })}</span>
                          {n.deps && <span>{t('swarm.nodeDepsShort', { deps: n.deps })}</span>}
                        </div>
                        {lastPost && <div className="swarm-node-last">{lastPost.text}</div>}
                      </div>

                    </div>
                  </foreignObject>
                </g>
              )
            })}
          </svg>
        )}
      </div>
    </Panel>
  )
}

function OfficeBackdrop({ w, h }: { w: number; h: number }) {
  const rightX = 24
  const workW = Math.max(240, w - rightX - 24)
  return (
    <g className="swarm-office-backdrop">
      <rect x="0" y="0" width={w} height={h} rx="18" fill="var(--bg-container)" />
      <g opacity=".34">
        <rect x={rightX} y="74" width={workW} height={Math.max(90, h - 104)} rx="12" fill="none" stroke="var(--border-subtle)" strokeDasharray="8 10" />
        {Array.from({ length: 4 }).map((_, i) => (
          <line key={i} x1={rightX + 34} x2={rightX + workW - 34} y1={118 + i * 98} y2={118 + i * 98} stroke="var(--border-subtle)" />
        ))}
      </g>
    </g>
  )
}

const MEMBER_COLORS = ['var(--accent)', 'var(--ok)', '#d2a8ff', '#39c5cf', '#ff7b72', '#f2cc60', '#a5d6ff', '#db6d28']
const MEMBER_HAT_COLORS = ['#f2cc60', 'var(--accent)', '#d2a8ff']
function stableIndex(name: string, mod: number) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h % mod
}
function memberColor(name: string) {
  return MEMBER_COLORS[stableIndex(name, MEMBER_COLORS.length)]
}
// ── 细分角色注册表（key→图标/配色/帽形），对齐后端 subroles.go 与设计文档 §3 ──
// 帽形 cap=鸭舌(工程/前端) round=圆顶(产品/审查) flat=平顶(测试/运维)；leader 王冠。
const SUBROLES: { key: string; icon: string; color: string; hat: string }[] = [
  { key: 'pm', icon: '🧭', color: '#39c5cf', hat: 'round' },
  { key: 'architect', icon: '🏛', color: '#d2a8ff', hat: 'round' },
  { key: 'frontend', icon: '🎨', color: '#ff9bce', hat: 'cap' },
  { key: 'backend', icon: '⚙️', color: 'var(--accent)', hat: 'cap' },
  { key: 'fullstack', icon: '🛠', color: '#7ee787', hat: 'cap' },
  { key: 'qa', icon: '🧪', color: '#d29922', hat: 'flat' },
  { key: 'designer', icon: '✏️', color: '#f0883e', hat: 'round' },
  { key: 'reviewer', icon: '🔍', color: '#a5d6ff', hat: 'round' },
  { key: 'devops', icon: '🚢', color: '#56d4dd', hat: 'flat' },
  { key: 'docs', icon: '📝', color: '#8b949e', hat: 'flat' },
  { key: 'commander', icon: '◆', color: '#f85149', hat: 'leader' },
]
const SUBROLE_MAP: Record<string, { key: string; icon: string; color: string; hat: string }> = Object.fromEntries(SUBROLES.map((s) => [s.key, s]))
// 解析节点的细分角色 key：leader → commander；否则取成员 msubrole（自定义 key 也透传）
function subroleKey(n: any): string | undefined {
  if (n.role === 'leader' || isLeaderRole(n.mrole)) return 'commander'
  return n.msubrole || undefined
}
// 细分角色展示文案：枚举走 i18n，自定义原样返回
function subroleText(t: T, key?: string): string {
  if (!key) return ''
  return SUBROLE_MAP[key] ? t(('swarm.subrole.' + key) as any) : key
}
function memberHatColor(n: any) {
  const sr = SUBROLE_MAP[subroleKey(n) || '']
  if (sr) return sr.color
  if (n.role === 'leader' || isLeaderRole(n.mrole)) return '#f85149'
  return MEMBER_HAT_COLORS[stableIndex(n.name || '', MEMBER_HAT_COLORS.length)]
}
function memberHatStyle(n: any) {
  const sr = SUBROLE_MAP[subroleKey(n) || '']
  if (sr) return sr.hat
  if (n.role === 'leader' || isLeaderRole(n.mrole)) return 'leader'
  return String(stableIndex(n.name || '', 3))
}
function screenKind(n: any) {
  return n.mkind === 'codex' ? 'codex' : 'claude'
}
function nodeColor(n: any) {
  const kind = n.kind
  if (kind === 'pending') return C.amber
  if (kind === 'failed') return C.red
  if (kind === 'exited') return C.fg2
  if (kind === 'leader' && !n.name) return C.magenta
  return memberColor(n.name || kind)
}
function nodeIcon(n: any) {
  if (n.role === 'leader') return <DiamondIcon size={11} />
  if (n.kind === 'done') return <CheckIcon size={12} />
  if (n.kind === 'waiting') return <QuestionIcon size={12} />
  if (n.kind === 'pending') return <ClockIcon size={12} />
  if (n.kind === 'failed') return <CloseIcon size={12} />
  return <DotIcon size={11} />
}
function nodeStatus(n: any, t: T) {
  if (n.kind === 'pending') return t('swarm.pending')
  if (n.kind === 'running') return t('common.running')
  if (n.kind === 'idle') return t('terminal.status.idle')
  if (n.kind === 'waiting') return t('swarm.waiting')
  if (n.kind === 'done') return t('common.done')
  if (n.kind === 'failed') return t('common.failed')
  return t('swarm.exited')
}
function nodeRole(n: any, t: T) {
  if (n.role === 'leader') return t('swarm.master')
  if (isLeaderRole(n.mrole)) return t('swarm.master')
  return t('swarm.member')
}

// 分层布局：leader 顶部；成员按 deps 深度分层
function buildLayout(detail: Detail | null, swarm: string, compact = false) {
  const NW = compact ? 176 : 240
  const NH = compact ? 132 : 164
  const GX = compact ? 14 : 34
  const GY = compact ? 42 : 78
  const TOP = compact ? 8 : 14
  const MASTER_H = compact ? 124 : 154
  if (!detail) return { nodes: [], edges: [], w: 400, h: 280 }
  type N = { name: string; role: 'leader' | 'member' | 'pending'; kind: string; deps: string; session: string; task?: string; x: number; y: number; w: number; h: number; mrole?: string; mkind?: string; msubrole?: string; mduty?: string }
  // leader 顶点优先用 role=leader 的成员（它从分层行里排除，只在顶部画一次）
  const masterMember = detail.members.find((m) => isLeaderRole(m.role))
  const members = detail.members.filter((m) => m !== masterMember).map((m) => ({
    name: m.name, role: 'member' as const, deps: m.deps, session: m.session, task: m.task,
    kind: memberNodeKind(m),
    mrole: m.role, mkind: m.kind, // 成员级 角色(master/worker) 与 引擎(claude/codex)
    msubrole: m.subrole, mduty: m.duty, // 细分角色 + 职责
  }))
  const pendings = detail.pending.map((p) => ({ name: p.name, role: 'pending' as const, deps: p.deps, session: `${swarm}-${p.name}`, kind: 'pending' }))
  const all = [...members, ...pendings]
  // 注意：只有 leader、还没 member 时 all 为空，但仍要把 leader 顶点画出来，不能空返回。
  // supervisor(cc-<群>) 也是 leader，没有 role=leader 成员时要靠它兜底，否则新建带 Leader 的群看不到任何节点。
  if (all.length === 0 && !masterMember && !detail.supervisor) return { nodes: [], edges: [], w: 400, h: 280 }
  const byName: Record<string, any> = {}; all.forEach((n) => (byName[n.name] = n))
  const memo: Record<string, number> = {}
  const depth = (name: string, seen = new Set<string>()): number => {
    if (name in memo) return memo[name]
    const n = byName[name]; if (!n || !n.deps || seen.has(name)) return 0
    seen.add(name)
    let d = 0
    n.deps.split(',').map((s: string) => s.trim()).filter(Boolean).forEach((dep: string) => { if (byName[dep]) d = Math.max(d, depth(dep, seen) + 1) })
    memo[name] = d; return d
  }
  const layers: Record<number, any[]> = {}
  all.forEach((n) => { const d = depth(n.name); (layers[d] = layers[d] || []).push(n) })
  const layerKeys = Object.keys(layers).map(Number).sort((a, b) => a - b)
  const maxRow = Math.max(1, ...layerKeys.map((k) => layers[k].length))
  const w = Math.max(NW + 40, maxRow * NW + (maxRow - 1) * GX + 24)
  const nodes: N[] = []
  // leader 顶部居中：优先 role=leader 成员；否则 supervisor(cc Leader)；都没有则不画幽灵节点
  const masterName = masterMember ? masterMember.name : detail.supervisor
  if (masterName) {
    const mk = masterMember ? memberNodeKind(masterMember) : 'leader'
    nodes.push({ name: masterName, role: 'leader', kind: mk, deps: '', session: masterMember ? masterMember.session : detail.supervisor, task: masterMember?.task || detail.goal, x: w / 2 - NW / 2, y: TOP, w: NW, h: MASTER_H, mkind: masterMember?.kind, msubrole: masterMember?.subrole || 'commander', mduty: masterMember?.duty })
  }
  layerKeys.forEach((k, li) => {
    const row = layers[k]
    const rowW = row.length * NW + (row.length - 1) * GX
    const startX = (w - rowW) / 2
    const y = TOP + MASTER_H + GY * 0.5 + li * (NH + GY)
    row.forEach((n, i) => nodes.push({ ...n, x: startX + i * (NW + GX), y, w: NW, h: NH }))
  })
  const pos: Record<string, N> = {}; nodes.forEach((n) => (pos[n.name] = n))
  const edges: { from: string; to: string; kind: 'cmd' | 'dep' }[] = []
  const master = masterName ? pos[masterName] : undefined
  // Leader 指挥边：leader → 第 0 层成员（无 leader 节点时不画）
  if (master) (layers[0] || []).forEach((n) => {
    edges.push({ kind: 'cmd', from: master.name, to: n.name })
  })
  // 依赖边：dep → member
  all.forEach((n) => {
    if (!n.deps) return
    n.deps.split(',').map((s: string) => s.trim()).filter(Boolean).forEach((dep: string) => {
      const a = pos[dep], b = pos[n.name]; if (!a || !b) return
      edges.push({ kind: 'dep', from: dep, to: n.name })
    })
  })
  const h = TOP + MASTER_H + GY * 0.5 + layerKeys.length * (NH + GY)
  return { nodes, edges, w, h: Math.max(h, 260) }
}

// ── 广场 ──
function Plaza({ name, posts, focus }: { name: string; posts: Post[]; focus: string | null }) {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [text, setText] = useState('')
  const [kind, setKind] = useState('note')
  const [replyTo, setReplyTo] = useState<Post | null>(null)
  const [sending, setSending] = useState(false)
  const feedRef = useRef<HTMLDivElement>(null)
  useEffect(() => { const el = feedRef.current; if (el) el.scrollTop = el.scrollHeight }, [posts.length])

  const send = async () => {
    if (!text.trim()) return
    setSending(true)
    try {
      await api('POST', `/swarms/${encodeURIComponent(name)}/say`, { kind, text: text.trim(), re: replyTo ? String(replyTo.id) : '' })
      setText('')
      setReplyTo(null)
    }
    catch (e: any) { message.error(e.message) } finally { setSending(false) }
  }
  return (
    <Panel title={t('swarm.plazaTitle')} extra={<span style={{ fontSize: 11, color: C.fg3 }}>{t('swarm.realtime')}</span>}>
      <div ref={feedRef} style={{ flex: '1 1 0', minHeight: 0, overflow: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 9 }}>
        {posts.length === 0 ? <Empty description={t('swarm.noMessages')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> : posts.map((p) => {
              const who = isLeaderAuthor(p.author) ? C.magenta : p.author === 'human' ? C.blue : C.green
          const dim = focus && focus !== p.author
          return (
            <div key={p.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, opacity: dim ? 0.4 : 1 }}>
              <span style={{ color: C.fg3, fontSize: 11, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', paddingTop: 2 }}>#{p.id} {(p.ts || '').slice(11, 16)}</span>
              <span style={{ color: who, fontWeight: 600, whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 4 }}>{isLeaderAuthor(p.author) ? <DiamondIcon size={9} /> : <DotIcon size={9} />}{authorLabel(p.author, t)}</span>
              <span style={{ fontSize: 12 }}>{kindIcon(p.kind)}</span>
              {p.re != null && <span style={{ color: C.fg3, fontSize: 12, whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 2 }}><ReplyIcon size={11} />#{p.re}</span>}
              <span style={{ color: C.fg, flex: 1, minWidth: 0 }}>{p.text}</span>
              <Button size="small" type="link" style={{ padding: '0 2px', height: 20, fontSize: 12 }} onClick={() => setReplyTo(p)}>
                {t('swarm.reply')}
              </Button>
            </div>
          )
        })}
      </div>
      {replyTo && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderTop: `1px solid ${C.line}`, color: C.fg2, fontSize: 12 }}>
          <span style={{ whiteSpace: 'nowrap' }}>{t('swarm.replyingTo', { id: replyTo.id })}</span>
          <span style={{ color: C.fg3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{replyTo.text}</span>
          <Button size="small" type="link" style={{ padding: 0, height: 20 }} onClick={() => setReplyTo(null)}>{t('common.cancel')}</Button>
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, padding: '9px 12px', borderTop: `1px solid ${C.line}` }}>
        <Select size="small" value={kind} onChange={setKind} style={{ width: 96 }}
          options={['note', 'ask', 'decide', 'broadcast', 'block', 'done'].map((k) => ({ value: k, label: k }))} />
        <Input size="small" value={text} onChange={(e) => setText(e.target.value)} onPressEnter={onEnterSubmit(send)} placeholder={t('swarm.sayPlaceholder')} />
        <Button size="small" type="primary" loading={sending} onClick={send}>{t('swarm.say')}</Button>
      </div>
    </Panel>
  )
}
function kindIcon(k: string) {
  const m: Record<string, React.ReactNode> = {
    broadcast: <MegaphoneIcon size={13} />,
    done: <span style={{ color: C.green, display: 'flex' }}><CheckIcon size={13} /></span>,
    ask: <span style={{ color: C.amber, display: 'flex' }}><QuestionIcon size={13} /></span>,
    decide: <span style={{ color: C.cyan, display: 'flex' }}><TargetIcon size={13} /></span>,
    block: <span style={{ color: C.red, display: 'flex' }}><BlockIcon size={13} /></span>,
  }
  return m[k] || <span style={{ color: C.fg3, display: 'flex' }}><DotIcon size={9} /></span>
}

// ── Inbox：把需要 master / human 介入的事项收敛到一个队列 ──
function Inbox({ detail, cards, posts, onNode }: { detail: Detail | null; cards: CardT[]; posts: Post[]; onNode: (m: string) => void }) {
  const { t } = useI18n()
  const items = useMemo(() => {
    const out: Array<{ key: string; type: string; tone: string; title: string; meta: string; body?: string; member?: string }> = []
    cards.filter((c) => c.col === 'blocked').forEach((c) => out.push({
      key: `card-blocked-${c.id}`, type: t('swarm.inbox.type.blockedCard'), tone: C.red,
      title: `${c.id} · ${c.title}`, meta: c.assignee ? `@${c.assignee}` : colLabel(t, 'blocked'), body: c.descr, member: c.assignee,
    }))
    posts.filter((p) => p.kind === 'block').slice(-6).reverse().forEach((p) => out.push({
      key: `post-block-${p.id}`, type: t('swarm.inbox.type.block'), tone: C.red,
      title: `#${p.id} · ${authorLabel(p.author, t)}`, meta: (p.ts || '').slice(5, 16), body: displayPostText(p.text), member: p.author !== 'human' && !isLeaderAuthor(p.author) ? p.author : undefined,
    }))
    cards.filter((c) => c.col === 'review').forEach((c) => out.push({
      key: `card-review-${c.id}`, type: t('swarm.inbox.type.review'), tone: C.cyan,
      title: `${c.id} · ${c.title}`, meta: c.assignee ? `@${c.assignee}` : colLabel(t, 'review'), body: c.descr, member: c.assignee,
    }))
    ;(detail?.pending || []).forEach((p) => out.push({
      key: `pending-${p.name}`, type: t('swarm.inbox.type.pending'), tone: C.amber,
      title: p.name, meta: t('swarm.nodeDepsShort', { deps: p.deps || '?' }), member: p.name,
    }))
    const leaderLastPost = detail?.leader_last_post || 0
    posts.filter((p) => p.id > leaderLastPost && p.author === 'human' && (p.kind === 'ask' || /@(leader|master)\b/.test(p.text))).slice(-6).reverse().forEach((p) => out.push({
      key: `human-${p.id}`, type: t('swarm.inbox.type.human'), tone: C.blue,
      title: `#${p.id} · human`, meta: (p.ts || '').slice(5, 16), body: displayPostText(p.text),
    }))
    return out.slice(0, 14)
  }, [cards, detail, posts, t])

  const countByTone = (tone: string) => items.filter((x) => x.tone === tone).length
  return (
    <Panel title={t('swarm.inboxTitle')} extra={<span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: C.fg3 }}>
      {countByTone(C.red) > 0 && <Tag color="error" style={{ margin: 0 }}>{countByTone(C.red)}</Tag>}
      {items.length ? t('swarm.inboxCount', { count: items.length }) : t('swarm.inboxClear')}
    </span>}>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 9 }}>
        {items.length === 0 ? (
          <Empty description={t('swarm.inboxEmpty')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : items.map((it) => (
          <button key={it.key} onClick={() => it.member && onNode(it.member)}
            style={{
              textAlign: 'left', border: `1px solid ${C.line}`, borderLeft: `3px solid ${it.tone}`, borderRadius: 8,
              background: C.bg3, color: C.fg, padding: '8px 10px', cursor: it.member ? 'pointer' : 'default',
              display: 'flex', flexDirection: 'column', gap: 5, minWidth: 0,
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span style={{ color: it.tone, fontSize: 11, whiteSpace: 'nowrap' }}>{it.type}</span>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13, fontWeight: 600 }}>{it.title}</span>
              <span style={{ color: C.fg3, fontSize: 11, whiteSpace: 'nowrap' }}>{it.meta}</span>
            </div>
            {it.body && <div style={{ color: C.fg2, fontSize: 12, lineHeight: '17px', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{it.body}</div>}
          </button>
        ))}
      </div>
    </Panel>
  )
}

// ── 看板（真拖拽） ──
function Board({ name, cards, focus, onCard, reload, setCards }: {
  name: string; cards: CardT[]; focus: string | null; onCard: (c: CardT) => void
  reload: () => void; setCards: React.Dispatch<React.SetStateAction<CardT[]>>
}) {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [adding, setAdding] = useState(false)
  const byCol = (c: Col) => cards.filter((k) => (k.col || 'backlog') === c)

  const onDragEnd = async (r: any) => {
    if (!r.destination) return
    const id = r.draggableId, to = r.destination.droppableId as Col
    const card = cards.find((k) => k.id === id); if (!card || card.col === to) return
    setCards((cs) => cs.map((k) => (k.id === id ? { ...k, col: to } : k)))  // 乐观
    try { await api('PATCH', `/swarms/${encodeURIComponent(name)}/task/${id}`, { move: to }) }
    catch (e: any) { message.error(e.message); reload() }
  }
  const del = async (id: string) => {
    try { await api('DELETE', `/swarms/${encodeURIComponent(name)}/task/${id}`); reload() } catch (e: any) { message.error(e.message) }
  }

  return (
    <Panel title={t('swarm.boardTitle')} extra={<Button size="small" type="primary" ghost onClick={() => setAdding(true)}>+ {t('swarm.addCard')}</Button>}>
      <DragDropContext onDragEnd={onDragEnd}>
        <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 10, padding: 10, overflowX: 'auto' }}>
          {COLS.map((c) => (
            <Droppable droppableId={c} key={c}>
              {(prov, snap) => (
                <div ref={prov.innerRef} {...prov.droppableProps}
                  style={{ flex: '0 0 184px', background: snap.isDraggingOver ? C.line : C.bg3, border: `1px solid ${C.line}`, borderRadius: 9, display: 'flex', flexDirection: 'column', minHeight: 150, transition: 'background .15s' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', fontSize: 12, color: COL_COLOR[c], borderBottom: `1px solid ${C.line}` }}>
                    {c} <span style={{ color: C.fg3 }}>{colLabel(t, c)}</span>
                    <span style={{ marginLeft: 'auto', background: C.line2, borderRadius: 9, padding: '0 7px', fontSize: 11, color: C.fg2 }}>{byCol(c).length}</span>
                  </div>
                  <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
                    {byCol(c).map((card, idx) => (
                      <Draggable draggableId={card.id} index={idx} key={card.id}>
                        {(dp, ds) => {
                          const dim = focus && card.assignee !== focus
                          return (
                            <div ref={dp.innerRef} {...dp.draggableProps} {...dp.dragHandleProps}
                              onClick={() => card.assignee && onCard(card)}
                              style={{ ...dp.draggableProps.style, background: C.bg2, border: `1px solid ${ds.isDragging ? C.blue : C.line2}`, borderRadius: 8, padding: 9, opacity: dim ? 0.4 : 1, boxShadow: ds.isDragging ? `0 4px 12px rgba(0,0,0,.4)` : 'none' }}>
                              <div style={{ fontSize: 13, marginBottom: 6, display: 'flex', gap: 6 }}>
                                <span style={{ color: C.fg3, fontSize: 11 }}>{card.id}</span>
                                <span style={{ flex: 1 }}>{card.title}</span>
                                <Popconfirm title={t('swarm.deleteCardConfirm')} onConfirm={() => del(card.id)}><a onClick={(e) => e.stopPropagation()} style={{ color: C.fg3, display: 'inline-flex' }}><CloseIcon size={12} /></a></Popconfirm>
                              </div>
                              <div style={{ display: 'flex', gap: 6, alignItems: 'center', color: C.fg2, fontSize: 11 }}>
                                {card.assignee && <span style={{ color: C.green }}>@{card.assignee}</span>}
                                {card.deps && <span style={{ color: C.fg3, display: 'inline-flex', alignItems: 'center', gap: 3 }}><LinkIcon size={11} />{card.deps}</span>}
                              </div>
                            </div>
                          )
                        }}
                      </Draggable>
                    ))}
                    {prov.placeholder}
                  </div>
                </div>
              )}
            </Droppable>
          ))}
        </div>
      </DragDropContext>
      <AddCardModal open={adding} name={name} onClose={() => setAdding(false)} onDone={reload} />
    </Panel>
  )
}

function AddCardModal({ open, name, onClose, onDone }: { open: boolean; name: string; onClose: () => void; onDone: () => void }) {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [title, setTitle] = useState(''); const [assignee, setAssignee] = useState(''); const [col, setCol] = useState<Col>('backlog')
  useEffect(() => { if (open) { setTitle(''); setAssignee(''); setCol('backlog') } }, [open])
  const ok = async () => {
    if (!title.trim()) return message.error(t('swarm.cardTitleRequired'))
    try { await api('POST', `/swarms/${encodeURIComponent(name)}/task`, { title: title.trim(), assignee: assignee.trim(), col }); onClose(); onDone() }
    catch (e: any) { message.error(e.message) }
  }
  return (
    <Modal open={open} onCancel={onClose} onOk={ok} okText={t('swarm.addCard')} title={t('swarm.newCard')} destroyOnClose>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Input placeholder={t('swarm.cardTitlePlaceholder')} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus onPressEnter={onEnterSubmit(ok)} />
        <Input placeholder={t('swarm.assigneePlaceholder')} value={assignee} onChange={(e) => setAssignee(e.target.value)} />
        <Select value={col} onChange={(v) => setCol(v as Col)} style={{ width: '100%' }}
          options={COLS.map((c) => ({ value: c, label: `${c} (${colLabel(t, c)})` }))} />
      </Space>
    </Modal>
  )
}

// ── 节点详情抽屉（每个 cc 的身份 + 终端快照 + 卡 + 发言） ──
function NodeDrawer({ swarm, member, detail, cards, posts, openTerm, onClose, onDone, onActivate }: {
  swarm: string; member: string | null; detail: Detail | null; cards: CardT[]; posts: Post[]
  openTerm: (n: string) => void; onClose: () => void
  onDone: (m?: string) => void; onActivate: (m?: string, force?: boolean) => void
}) {
  const { t } = useI18n()
  const isMaster = !!detail && (member === detail.supervisor)
  const m = detail?.members.find((x) => x.name === member)
  const pend = detail?.pending.find((x) => x.name === member)
  const session = isMaster ? (detail?.supervisor || `cc-${swarm}`) : m?.session || `${swarm}-${member}`
  // 抽屉至少占屏宽一半（窄屏则占满）
  const { phone } = useLayout()
  const drawerW = phone ? '100%' : 'min(100vw, max(520px, 50vw))'
  // 初始化指令（成员收到的提示词 / master 的目标），按 markdown 渲染
  const initCmd = isMaster ? (detail?.goal ? `**${t('swarm.goal')}**\n\n${detail.goal}` : '') : (m?.task || '')

  const myCards = cards.filter((c) => c.assignee === member)
  const myPosts = posts.filter((p) => p.author === member)
  const color = isMaster ? C.magenta : pend ? C.amber : m?.done ? C.green : m?.status === 'running' ? C.green : m?.status === 'idle' ? C.blue : m?.status === 'waiting' ? C.amber : C.fg2
  const tagStatus = m?.done ? 'done' : (m?.status || 'exited')
  const tagColor = tagStatus === 'running' ? 'processing' : tagStatus === 'idle' ? 'blue' : tagStatus === 'waiting' ? 'warning' : tagStatus === 'done' ? 'success' : 'default'
  // 细分角色：leader → commander；否则成员 subrole（自定义 key 透传）
  const srKey = isMaster ? 'commander' : (m?.subrole || undefined)
  const srInfo = srKey ? SUBROLE_MAP[srKey] : undefined
  const srColor = srInfo?.color || C.fg2
  const srIcon = srInfo?.icon || '👤'

  return (
    <Drawer open={!!member} onClose={onClose} width={drawerW} title={
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <i style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
        <b>{member}</b>
        {srKey && <Tag bordered style={{ color: srColor, borderColor: srColor + '88', background: srColor + '18' }}>{srIcon} {subroleText(t, srKey)}</Tag>}
        {isMaster ? <Tag color="blue">{t('swarm.master')}</Tag> : pend ? <Tag color="warning">{t('swarm.pending')}</Tag> : <Tag color={tagColor}>{nodeStatus({ kind: tagStatus }, t)}</Tag>}
      </span>
    }>
      {member && (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <div style={{ color: C.fg2, fontSize: 12, marginBottom: 4 }}>{t('swarm.identity')}</div>
            <div style={{ fontSize: 13 }}>{isMaster ? t('swarm.master') : `${m?.type || 'agent'} · ${t('swarm.member')}`}{srKey && <> · {srIcon} {subroleText(t, srKey)}</>} · {t('common.terminal')} <b title={session}>{sessionLabel(session)}</b></div>
            {(m?.deps || pend?.deps) && <div style={{ fontSize: 12, color: C.fg3, marginTop: 4 }}>{t('swarm.depsArrow')} {m?.deps || pend?.deps}</div>}
            <Space wrap style={{ marginTop: 10 }}>
              <Button size="small" type="primary" iconPosition="end" icon={<OpenInIcon size={12} />} onClick={() => { openTerm(session); onClose() }}>{t('swarm.openTerminal')}</Button>
              {!isMaster && (pend ? (
                <>
                  <Button size="small" onClick={() => { onActivate(member!); onClose() }}>{t('swarm.unlockWhenReady')}</Button>
                  <Popconfirm title={t('swarm.forceUnlockConfirm')} onConfirm={() => { onActivate(member!, true); onClose() }}><Button size="small" danger>{t('swarm.forceUnlock')}</Button></Popconfirm>
                </>
              ) : !m?.done ? (
                <Popconfirm title={t('swarm.markMemberDoneConfirm', { member })} onConfirm={() => { onDone(member!); onClose() }}>
                  <Button size="small">{t('swarm.markDone')}</Button>
                </Popconfirm>
              ) : <Tag color="success" icon={<CheckIcon size={11} />}>{t('swarm.doneMarked')}</Tag>)}
            </Space>
          </div>
          {m?.duty && (
            <div>
              <div style={{ color: C.fg2, fontSize: 12, marginBottom: 6 }}>{t('swarm.duty')}</div>
              <div style={{ background: srColor + '14', border: `1px solid ${srColor}44`, borderRadius: 8, padding: '9px 12px', fontSize: 13 }}>{m.duty}</div>
            </div>
          )}
          {initCmd && (
            <div>
              <div style={{ color: C.fg2, fontSize: 12, marginBottom: 6 }}>{t('swarm.initialInstruction')}</div>
              <div style={{ background: C.bg3, border: `1px solid ${C.line}`, borderRadius: 8, padding: '10px 14px', maxHeight: '48vh', overflow: 'auto' }}>
                <Markdown>{initCmd}</Markdown>
              </div>
            </div>
          )}
          <div>
            <div style={{ color: C.fg2, fontSize: 12, marginBottom: 6 }}>{t('swarm.memberCards', { count: myCards.length })}</div>
            {myCards.length ? myCards.map((c) => (
              <div key={c.id} style={{ background: C.bg3, border: `1px solid ${C.line}`, borderRadius: 7, padding: '7px 9px', marginBottom: 6, fontSize: 13 }}>
                <span style={{ color: C.fg3, fontSize: 11 }}>{c.id}</span> {c.title} <span style={{ color: COL_COLOR[(c.col as Col)] || C.fg2 }}>[{c.col}]</span>
              </div>
            )) : <div style={{ color: C.fg3, fontSize: 12 }}>{t('common.empty')}</div>}
          </div>
          <div>
            <div style={{ color: C.fg2, fontSize: 12, marginBottom: 6 }}>{t('swarm.memberPosts', { count: myPosts.length })}</div>
            {myPosts.length ? myPosts.slice(-6).map((p) => (
              <div key={p.id} style={{ fontSize: 13, marginBottom: 5 }}>{kindIcon(p.kind)} <span style={{ color: C.fg }}>{p.text}</span></div>
            )) : <div style={{ color: C.fg3, fontSize: 12 }}>{t('common.empty')}</div>}
          </div>
        </Space>
      )}
    </Drawer>
  )
}
