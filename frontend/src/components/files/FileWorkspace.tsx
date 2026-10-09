// 统一「文件工作区」：左侧文件浏览器(可拖拽调宽) + VSCode 式多文件编辑 tab + Monaco 编辑器。
// 支持左右双栏(编辑组 A/B)：拖 tab 到另一栏、或从文件树拖文件到某栏；会话(终端)作为固定首 tab 常驻 A 栏。
// 两处复用：独立 Files 页（纯文件）与新标签 SoloTerminal（会话经 leading* 槽传入）。
import { type ReactNode, Fragment, useEffect, useRef, useState } from 'react'
import { App as AntApp, Dropdown, type MenuProps } from 'antd'
import FileBrowser from './FileBrowser'
import { FileView } from './fileview'
import { FileTypeIcon } from './file-icons'
import { useI18n } from '../../i18n'
import type { AgentKind } from '../../agent-kind'
import { PointerResizeShield, usePointerResize } from '../mirror/PointerResize'
import { useLayout } from '../../layout'
import { CloseIcon, MoreIcon } from '../../icons'
import { INTENT_EVENT, OPEN_FILE_INTENT, takeIntentData } from '../../intents'
import { RailControls, RAIL_STEP, isGripEvent, isStepEvent } from '../shell/RailGrip'

type Group = 'A' | 'B'
const TAB_MIME = 'application/x-ttmux-tab'
const PATH_MIME = 'application/x-ttmux-path'
const LEAD_MIME = 'application/x-ttmux-lead' // 拖会话(首)tab → 左右易位
const PREVIEW_PREFIX = 'preview://' // 侧栏预览 tab 的标识前缀（区别于同文件的源码 tab）
const DOCK_MIN = 160, DOCK_MAX = 640, DOCK_DEFAULT = 240 // 240：文件名够看，正文那栏多出 40

function baseName(p: string): string {
  return p.split('/').pop() || p
}
const isPreview = (id: string) => id.startsWith(PREVIEW_PREFIX)
const realPath = (id: string) => (isPreview(id) ? id.slice(PREVIEW_PREFIX.length) : id)

export default function FileWorkspace({
  dir,
  accent = 'var(--accent)',
  onOpenAgent,
  explorerOpen = true,
  onExplorerClose,
  onExplorerOpen,
  leadingTab,
  leadingTitle,
  leadingContent,
  chrome,
  footer,
  emptyText,
}: {
  dir: string
  accent?: string
  onOpenAgent?: (kind: AgentKind, path: string) => void
  explorerOpen?: boolean
  onExplorerClose?: () => void
  /** 收起后把手留在原地，点它把文件树叫回来；不给就没有回程，那时把手也不画 */
  onExplorerOpen?: () => void
  leadingTab?: ReactNode
  leadingTitle?: string
  leadingContent?: ReactNode
  chrome?: ReactNode
  footer?: ReactNode
  emptyText?: string
}) {
  const { t } = useI18n()
  const { modal } = AntApp.useApp()
  const hasLeading = leadingTab != null

  // 文件树的开合：外面给了回调就听外面的（会话页那枚「文件」按钮），没给就自己记
  // （独立文件页没有别的开关，握把是唯一入口）。
  const treeControlled = onExplorerClose != null || onExplorerOpen != null
  const [treeOpenLocal, setTreeOpenLocal] = useState(true)
  const treeOpen = treeControlled ? explorerOpen : treeOpenLocal
  const toggleTree = () => {
    if (!treeControlled) { setTreeOpenLocal((v) => !v); return }
    if (explorerOpen) onExplorerClose?.(); else onExplorerOpen?.()
  }

  // 两个编辑组：A 主（含固定首 tab）、B 副（filesB 非空时出现，即分栏）
  const [filesA, setFilesA] = useState<string[]>([])
  const [filesB, setFilesB] = useState<string[]>([])
  const [activeA, setActiveA] = useState<string | null>(null) // null = 固定首 tab(会话)
  const [activeB, setActiveB] = useState<string | null>(null)
  const [focus, setFocus] = useState<Group>('A')
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set())
  const [dropHint, setDropHint] = useState<Group | 'split' | null>(null) // 拖拽落点提示
  // tab 条容器引用：标签多到溢出时，新开/切到的 tab 可能落在横向滚动区域外点不到，
  // 靠 scrollIntoView 把当前激活的 tab 拉回可见区（见下方 effect）。
  const tabStripRef = useRef<Record<Group, HTMLDivElement | null>>({ A: null, B: null })
  const [dragging, setDragging] = useState(false) // 原生拖拽进行中 → 每栏内容盖一层透明接盘层，压过终端/Monaco
  // 拖的是 tab/会话(需接盘层压过终端才能移栏) 还是文件路径(要落回终端/对话做 @引用注入,不能被接盘层截走)
  const [dragKind, setDragKind] = useState<'tab' | 'lead' | 'path' | null>(null)
  const resize = usePointerResize()
  useEffect(() => {
    // drop 用「冒泡阶段」清理：React 事件委托挂在 document 内层根节点，冒泡到 document 时
    // onDrop 已派发完，此时卸接盘层安全。若用捕获阶段则会赶在 onDrop 前卸掉接盘层 →
    // drop 落到已移除的元素 → onDrop 不触发 → tab 不动。dragend 兜底（拖到界外/取消）。
    const end = () => { setDropHint(null); setDragging(false); setDragKind(null) }
    document.addEventListener('dragend', end)
    document.addEventListener('drop', end)
    return () => { document.removeEventListener('dragend', end); document.removeEventListener('drop', end) }
  }, [])
  const split = filesB.length > 0

  const filesOf = (g: Group) => (g === 'A' ? filesA : filesB)
  const setFilesOf = (g: Group, v: string[]) => (g === 'A' ? setFilesA(v) : setFilesB(v))
  const activeOf = (g: Group) => (g === 'A' ? activeA : activeB)
  const setActiveOf = (g: Group, v: string | null) => (g === 'A' ? setActiveA(v) : setActiveB(v))

  useEffect(() => {
    ;(['A', 'B'] as Group[]).forEach((g) => {
      const strip = tabStripRef.current[g]
      if (!strip) return
      const key = activeOf(g) ?? 'lead'
      const el = strip.querySelector<HTMLElement>(`[data-tab-key="${CSS.escape(key)}"]`)
      if (!el) return
      // 只挪 tab 条自己的 scrollLeft，不用 Element.scrollIntoView——它会顺带滚动外层
      // 祖先(哪怕 overflow:hidden 不出滚动条也会被program改 scrollLeft)，
      // 标签一多就把旁边的文件树 dock 也一起挤出可视区。
      const stripRect = strip.getBoundingClientRect()
      const elRect = el.getBoundingClientRect()
      if (elRect.left < stripRect.left) strip.scrollLeft -= stripRect.left - elRect.left
      else if (elRect.right > stripRect.right) strip.scrollLeft += elRect.right - stripRect.right
    })
  }, [activeA, activeB, filesA, filesB])

  const setFileDirty = (p: string, dirty: boolean) => setDirtyFiles((prev) => {
    if (prev.has(p) === dirty) return prev
    const n = new Set(prev); dirty ? n.add(p) : n.delete(p); return n
  })

  // 在某组打开文件；若已在另一组则跳到那一组，避免同一文件跨组重复
  const openInGroup = (p: string, g: Group) => {
    const other: Group = g === 'A' ? 'B' : 'A'
    if (filesOf(other).includes(p)) { setActiveOf(other, p); setFocus(other); return }
    if (!filesOf(g).includes(p)) setFilesOf(g, [...filesOf(g), p])
    setActiveOf(g, p); setFocus(g)
  }
  const openFileTab = (p: string) => openInGroup(p, split ? focus : 'A')
  // 从对话里点 Read/Edit 的路径开文件：**一律开到右栏**，不占 A 栏。
  // A 栏的首 tab 是会话（终端/对话）本身，开在那儿等于把你正在看的对话顶掉——
  // 而你点这个路径的动机恰恰是「一边对着看」。已经在 A 栏开着的就挪过来，不留两份。
  const openFileToSide = (p: string) => {
    if (filesA.includes(p)) {
      const nextA = filesA.filter((x) => x !== p)
      setFilesA(nextA)
      if (activeA === p) setActiveA(hasLeading ? null : (nextA[0] ?? null))
    }
    if (!filesB.includes(p)) setFilesB([...filesB, p])
    setActiveB(p); setFocus('B')
  }
  // 对话页点「Grep 命中 path:line」跳过来时要定位到那一行。按路径记，nonce 自增——
  // 同一文件已经开着时 FileView 的 props 不变，没有 nonce 第二次点同一处就毫无反应。
  const [reveal, setReveal] = useState<{ path: string; line: number; nonce: number } | null>(null)
  // ⌘K 搜到文件 → 切到文件页 → 这里把它开成标签页。挂载时也取一次：从别的页面
  // 点过来时，意图早在本组件存在之前就发完了（见 intents.ts）。
  const openFileRef = useRef(openFileTab)
  openFileRef.current = openFileTab
  const openSideRef = useRef(openFileToSide)
  openSideRef.current = openFileToSide
  useEffect(() => {
    const on = () => {
      const data = takeIntentData<{ path?: string; line?: number; side?: boolean }>(OPEN_FILE_INTENT)
      if (!data || data === true || !data.path) return
      // side 只有「A 栏被会话占着」时才有意义（文件页没有首 tab，开哪栏都不挡事）
      if (data.side && hasLeading) openSideRef.current(data.path)
      else openFileRef.current(data.path)
      const line = Number(data.line)
      if (line > 0) setReveal((prev) => ({ path: data.path!, line, nonce: (prev?.nonce || 0) + 1 }))
    }
    on()
    window.addEventListener(INTENT_EVENT, on)
    return () => window.removeEventListener(INTENT_EVENT, on)
  }, [hasLeading])
  // VSCode「侧栏打开预览」：把该 markdown 的渲染预览开到另一栏（预览 tab 用前缀区分，可与源码同时存在）
  const openPreviewToSide = (fromGroup: Group, p: string) => {
    const to: Group = fromGroup === 'A' ? 'B' : 'A'
    const id = PREVIEW_PREFIX + p
    if (!filesOf(to).includes(id)) setFilesOf(to, [...filesOf(to), id])
    setActiveOf(to, id); setFocus(to)
  }

  const neighbor = (arr: string[], removedIdx: number, g: Group): string | null => {
    const next = arr
    return next[removedIdx - 1] ?? next[removedIdx] ?? (g === 'A' && hasLeading ? null : (next[0] ?? null))
  }
  const doClose = (p: string, g: Group) => {
    const arr = filesOf(g)
    const i = arr.indexOf(p)
    if (i < 0) return
    const next = arr.filter((x) => x !== p)
    setFilesOf(g, next)
    setFileDirty(p, false)
    if (activeOf(g) === p) setActiveOf(g, neighbor(next, i, g))
    if (g === 'B' && next.length === 0) setFocus('A')
  }
  const closeFileTab = (p: string, g: Group) => {
    if (dirtyFiles.has(p)) {
      modal.confirm({
        title: t('file.closeUnsavedTitle'), content: baseName(p),
        okText: t('file.closeWithoutSaving'), cancelText: t('common.cancel'),
        okButtonProps: { danger: true }, onOk: () => doClose(p, g),
      })
    } else doClose(p, g)
  }
  // 把 tab 从 from 组移到 to 组（拖拽到另一栏）
  const moveTab = (p: string, from: Group, to: Group) => {
    if (from === to) { setActiveOf(to, p); setFocus(to); return }
    const fromArr = filesOf(from)
    const i = fromArr.indexOf(p)
    const fromNext = fromArr.filter((x) => x !== p)
    setFilesOf(from, fromNext)
    if (activeOf(from) === p) setActiveOf(from, neighbor(fromNext, i, from))
    if (!filesOf(to).includes(p)) setFilesOf(to, [...filesOf(to), p])
    setActiveOf(to, p); setFocus(to)
    if (from === 'B' && fromNext.length === 0) setFocus('A')
  }

  const leadingActive = hasLeading && activeA === null

  // 两栏：宽度比(左栏占比，拖分隔条调整) + 左右易位
  const panesRef = useRef<HTMLDivElement>(null)
  // 占比同样记 localStorage：分隔条是用户拖出来的，刷新后自己挪回正中间就是把这次调整丢了
  const clampFrac = (v: number) => Math.min(0.85, Math.max(0.15, v))
  const [splitFrac, setSplitFrac] = useState(() => {
    const s = Number(localStorage.getItem('ttmux.fileSplitFrac'))
    return Number.isFinite(s) && s > 0 ? clampFrac(s) : 0.5
  })
  const [swapped, setSwapped] = useState(false)
  const leftGroup: Group = swapped ? 'B' : 'A'

  const fracRef = useRef(splitFrac)
  fracRef.current = splitFrac
  // 拖动期间每帧都写 localStorage 没必要，松手落一次盘就够
  const saveFrac = (v: number) => localStorage.setItem('ttmux.fileSplitFrac', String(v))
  const startSplitResize = (e: React.PointerEvent<HTMLDivElement>) => {
    resize.start(e, {
      onMove: (ev) => {
        const el = panesRef.current; if (!el) return
        const r = el.getBoundingClientRect(); if (r.width <= 0) return
        setSplitFrac(clampFrac((ev.clientX - r.left) / r.width))
      },
      onEnd: () => saveFrac(fracRef.current),
    })
  }

  // 左侧文件栏宽度：可拖拽调整，记 localStorage
  const [dockW, setDockW] = useState(() => { const s = Number(localStorage.getItem('ttmux.fileDockW')); return s >= DOCK_MIN && s <= DOCK_MAX ? s : DOCK_DEFAULT })
  const dockWRef = useRef(dockW)
  dockWRef.current = dockW
  const saveDockW = (v: number) => {
    const w = Math.min(DOCK_MAX, Math.max(DOCK_MIN, v))
    setDockW(w); localStorage.setItem('ttmux.fileDockW', String(w))
  }
  const startResize = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isStepEvent(e)) return
    // 握把上按下但没挪 → 当成点击去开合文件树；挪了就是正常拖宽
    const onGrip = isGripEvent(e)
    let moved = false
    const startX = e.clientX, startW = dockW
    resize.start(e, {
      onMove: (ev) => {
        if (Math.abs(ev.clientX - startX) > 3) moved = true
        setDockW(Math.min(DOCK_MAX, Math.max(DOCK_MIN, startW + ev.clientX - startX)))
      },
      onEnd: () => {
        if (onGrip && !moved) { toggleTree(); return }
        localStorage.setItem('ttmux.fileDockW', String(dockWRef.current))
      },
    })
  }
  // 把手聚焦后用 ←/→ 微调（.tt-split-rail 自带 :focus-visible 描边，得有键盘路径才算数）
  const railKey = (e: React.KeyboardEvent, step: (dir: -1 | 1, big: boolean) => void, reset: () => void) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); step(e.key === 'ArrowLeft' ? -1 : 1, e.shiftKey) }
    else if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); reset() }
  }

  const dragHasPayload = (e: React.DragEvent) => e.dataTransfer.types.includes(TAB_MIME) || e.dataTransfer.types.includes(PATH_MIME) || e.dataTransfer.types.includes(LEAD_MIME)
  const applyDrop = (e: React.DragEvent, to: Group) => {
    if (e.dataTransfer.types.includes(LEAD_MIME)) { setSwapped(to !== leftGroup); return } // 会话拖到某栏 → 会话那栏挪到该侧
    const tab = e.dataTransfer.getData(TAB_MIME)
    if (tab) { try { const { path, from } = JSON.parse(tab); moveTab(path, from, to) } catch {} ; return }
    const p = e.dataTransfer.getData(PATH_MIME)
    if (p) openInGroup(p, to)
  }

  // ── 触屏拖拽 + 点按菜单兜底 ──
  // HTML5 原生拖拽在触屏不触发；且拖到另一栏时，那栏的终端/Monaco 会吞掉 drag 事件，
  // 导致「拖不进另一个分栏」。这里改用 PointerEvent + elementFromPoint 命中落点栏（爬到
  // 带 data-drop-group 的祖先），绕开内层控件，落点栏一定能识别。
  const { coarse } = useLayout()
  type Payload = { kind: 'tab'; path: string; from: Group } | { kind: 'lead' }
  const [touchDrag, setTouchDrag] = useState<{ label: string; x: number; y: number } | null>(null)
  const draggedRef = useRef(false)
  const rightGroup: Group = leftGroup === 'A' ? 'B' : 'A'

  const resolveDropAt = (x: number, y: number): { group: Group; hint: Group | 'split' } | null => {
    const el = document.elementFromPoint(x, y) as HTMLElement | null
    const zone = el?.closest('[data-drop-group]') as HTMLElement | null
    if (!zone) return null
    const g = zone.getAttribute('data-drop-group') as Group
    if (zone.getAttribute('data-drop-content') === '1' && !split && g === 'A') {
      const r = zone.getBoundingClientRect()
      if (x > r.left + r.width / 2) return { group: 'B', hint: 'split' } // 单栏拖到右半 → 拆栏
    }
    return { group: g, hint: g }
  }
  const applyPayload = (p: Payload, to: Group) => {
    if (p.kind === 'lead') { setSwapped(to !== leftGroup); return }
    moveTab(p.path, p.from, to)
  }
  const startTouchDrag = (e: React.PointerEvent, p: Payload, label: string) => {
    if (e.pointerType === 'mouse') return // 桌面走原生 HTML5 拖拽
    const sx = e.clientX, sy = e.clientY
    let started = false
    const move = (ev: PointerEvent) => {
      if (!started && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 8) return
      started = true; draggedRef.current = true
      ev.preventDefault()
      const hit = resolveDropAt(ev.clientX, ev.clientY)
      setDropHint(hit ? hit.hint : null)
      setTouchDrag({ label, x: ev.clientX, y: ev.clientY })
    }
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
      setTouchDrag(null); setDropHint(null)
      if (started) { const hit = resolveDropAt(ev.clientX, ev.clientY); if (hit) applyPayload(p, hit.group) }
      setTimeout(() => { draggedRef.current = false }, 0) // 让紧随的 click 被忽略
    }
    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
  }
  // 触屏兜底：tab 上「⋯」菜单，不拖也能移到左右栏 / 分栏
  const buildMenu = (p: Payload): NonNullable<MenuProps['items']> => {
    if (p.kind === 'lead') {
      if (!split) return []
      return leftGroup === 'A'
        ? [{ key: 'r', label: t('file.sessionRight'), onClick: () => setSwapped(true) }]
        : [{ key: 'l', label: t('file.sessionLeft'), onClick: () => setSwapped(false) }]
    }
    if (!split) return [
      { key: 'sr', label: t('file.splitRight'), onClick: () => { moveTab(p.path, p.from, 'B'); setSwapped(false) } },
      { key: 'sl', label: t('file.splitLeft'), onClick: () => { moveTab(p.path, p.from, 'B'); setSwapped(true) } },
    ]
    return p.from === leftGroup
      ? [{ key: 'mr', label: t('file.moveRight'), onClick: () => moveTab(p.path, p.from, rightGroup) }]
      : [{ key: 'ml', label: t('file.moveLeft'), onClick: () => moveTab(p.path, p.from, leftGroup) }]
  }
  const tabMenuBtn = (p: Payload) => {
    if (!coarse) return null
    const items = buildMenu(p)
    if (items.length === 0) return null
    return (
      <Dropdown trigger={['click']} placement="bottomRight" menu={{ items }}>
        <span className="cc-tabmenu" title={t('file.tabActions')} onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}
          style={{ display: 'inline-flex', padding: '0 var(--sp-1)', color: 'var(--text-dim)', lineHeight: 1 }}><MoreIcon size={14} /></span>
      </Dropdown>
    )
  }

  // 内容区(终端/编辑器)拖放：单栏 primary 落右半 → 拆栏，否则落本栏。content div 与拖拽期覆盖层共用。
  const onContentDragOver = (e: React.DragEvent, g: Group, primary: boolean) => {
    if (!dragHasPayload(e)) return
    e.preventDefault()
    if (!split && primary) setDropHint('split'); else setDropHint(g)
  }
  const onContentDrop = (e: React.DragEvent, g: Group, primary: boolean) => {
    if (!dragHasPayload(e)) return
    e.preventDefault()
    const r = e.currentTarget.getBoundingClientRect()
    const inRightHalf = e.clientX > r.left + r.width / 2
    const target: Group = (!split && primary && inRightHalf) ? 'B' : g
    setDropHint(null); applyDrop(e, target)
  }

  const tabBase: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', whiteSpace: 'nowrap', fontSize: 'var(--fs-meta)', cursor: 'pointer', borderRight: '1px solid var(--border-subtle)', touchAction: 'none' }

  const fileTab = (f: string, g: Group) => {
    const prev = isPreview(f)
    const rp = realPath(f)
    const isDirty = !prev && dirtyFiles.has(f)
    const act = activeOf(g) === f
    return (
      <div key={g + f} data-tab-key={f} title={prev ? `${t('file.preview')} · ${rp}` : f} draggable
        onDragStart={(e) => { e.dataTransfer.setData(TAB_MIME, JSON.stringify({ path: f, from: g })); e.dataTransfer.effectAllowed = 'move'; setDragging(true); setDragKind('tab') }}
        onPointerDown={(e) => startTouchDrag(e, { kind: 'tab', path: f, from: g }, baseName(f))}
        onClick={() => { if (draggedRef.current) return; setActiveOf(g, f); setFocus(g) }}
        className={`cc-filetab${isDirty ? ' dirty' : ''}`}
        style={{ ...tabBase, gap: 'var(--sp-1)', padding: 'var(--sp-1) var(--sp-2)', color: act ? 'var(--text-bright)' : 'var(--text-dim)', background: act ? 'var(--bg-base)' : 'transparent', boxShadow: act ? 'inset 0 2px 0 var(--accent)' : undefined }}>
        <span style={{ display: 'inline-flex', transform: 'scale(0.72)' }}><FileTypeIcon name={rp} /></span>
        <span style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', fontStyle: prev ? 'italic' : undefined }}>{prev ? `${t('file.preview')}: ${baseName(rp)}` : baseName(f)}</span>
        {tabMenuBtn({ kind: 'tab', path: f, from: g })}
        <a className="cc-tabx" onClick={(e) => { e.stopPropagation(); closeFileTab(f, g) }} onPointerDown={(e) => e.stopPropagation()} title={isDirty ? t('file.unsaved') : t('file.closeTab')}>
          <span className="dot" /><span className="x"><CloseIcon size={11} /></span>
        </a>
      </div>
    )
  }

  // 渲染一个编辑组（栏）：tab 条 + 内容（会话内容仅 A 栏；文件用 Monaco 覆盖）
  const pane = (g: Group) => {
    const primary = g === 'A'
    const files = filesOf(g)
    const active = activeOf(g)
    const grow = !split ? 1 : (g === leftGroup ? splitFrac : 1 - splitFrac)
    return (
      <div style={{ flex: `${grow} 1 0`, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}
        onClick={() => setFocus(g)}>
        <div style={{ display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-container)' }}>
          <div data-drop-group={g} ref={(el) => { tabStripRef.current[g] = el }} style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'stretch', overflowX: 'auto' }}
            onDragOver={(e) => { if (dragHasPayload(e)) { e.preventDefault(); setDropHint(g) } }}
            onDragLeave={() => setDropHint((h) => (h === g ? null : h))}
            onDrop={(e) => { if (dragHasPayload(e)) { e.preventDefault(); setDropHint(null); applyDrop(e, g) } }}>
            {primary && hasLeading && (
              <div data-tab-key="lead" onClick={() => { if (draggedRef.current) return; setActiveOf('A', null) }} title={leadingTitle}
                draggable={split}
                onDragStart={(e) => { e.dataTransfer.setData(LEAD_MIME, '1'); e.dataTransfer.effectAllowed = 'move'; setDragging(true); setDragKind('lead') }}
                onPointerDown={(e) => { if (split) startTouchDrag(e, { kind: 'lead' }, leadingTitle || '') }}
                style={{ ...tabBase, gap: 'var(--sp-2)', padding: 'var(--sp-1) var(--sp-3)', color: leadingActive ? 'var(--text-bright)' : 'var(--text-dim)', background: leadingActive ? 'var(--bg-base)' : 'transparent', boxShadow: leadingActive ? 'inset 0 2px 0 var(--accent)' : undefined }}>
                {leadingTab}
                {tabMenuBtn({ kind: 'lead' })}
              </div>
            )}
            {files.map((f) => fileTab(f, g))}
            {dropHint === g && <div style={{ flex: 1, minWidth: 24, background: 'var(--accent-soft)' }} />}
          </div>
        </div>
        {/* 会话工具栏：只属会话，放在会话首 tab 的正下方、终端之上（跟着会话那栏走） */}
        {primary && leadingActive && chrome}
        <div data-drop-group={g} data-drop-content="1" style={{ flex: 1, minWidth: 0, minHeight: 0, position: 'relative', display: 'flex' }}
          onDragOver={(e) => onContentDragOver(e, g, primary)}
          onDragLeave={(e) => { if (e.currentTarget === e.target) setDropHint(null) }}
          onDrop={(e) => onContentDrop(e, g, primary)}>
          {primary && leadingContent}
          {files.map((f) => {
            const prev = isPreview(f)
            return (
              <div key={f} style={{ position: 'absolute', inset: 0, zIndex: 6, background: 'var(--bg-base)', display: active === f ? 'block' : 'none' }}>
                <FileView path={realPath(f)} accent={accent} inline tabbed forcePreview={prev} active={active === f}
                  onClose={() => closeFileTab(f, g)} onOpenPath={(p) => openInGroup(p, g)}
                  onDirtyChange={prev ? undefined : setFileDirty} onOpenAgent={onOpenAgent}
                  revealLine={!prev && reveal?.path === realPath(f) ? { line: reveal.line, nonce: reveal.nonce } : undefined}
                  onPreviewToSide={prev ? undefined : (p) => openPreviewToSide(g, p)} />
              </div>
            )
          })}
          {(!primary || !hasLeading) && active === null && files.length === 0 && (
            <div style={{ flex: 1, display: 'grid', placeItems: 'center', color: 'var(--text-dimmer)', fontSize: 'var(--fs-sm)' }}>{emptyText || t('file.selectPreview')}</div>
          )}
          {/* 拖拽期透明接盘层：盖在终端/Monaco 之上，抢在它们之前接住 dragover/drop，
              否则拖 tab 到有终端/编辑器的那一栏时事件被内层吞掉 → 拖不进去。
              但拖「文件路径」到正显示会话(终端/对话)的首栏时不盖 → 让终端/ChatShell 自己接住做 @引用注入,
              否则文件会被当成「开文件/分栏」而进不了对话。tab/lead 拖拽照旧盖(移栏必须压过终端)。 */}
          {dragging && !(primary && leadingActive && dragKind === 'path') && (
            <div data-drop-group={g} data-drop-content="1" style={{ position: 'absolute', inset: 0, zIndex: 15 }}
              onDragOver={(e) => onContentDragOver(e, g, primary)}
              onDragLeave={(e) => { if (e.currentTarget === e.target) setDropHint(null) }}
              onDrop={(e) => onContentDrop(e, g, primary)} />
          )}
          {/* 单栏时拖到右半区 → 拆出第二栏 */}
          {!split && primary && dropHint === 'split' && (
            <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: '50%', zIndex: 20, pointerEvents: 'none', background: 'var(--accent-soft)', borderLeft: '1px dashed var(--accent-border)', display: 'grid', placeItems: 'center', color: 'var(--accent)', fontSize: 'var(--fs-sm)', fontWeight: 600 }}>{t('file.splitHere')}</div>
          )}
        </div>
        {/* 会话底部输入/快捷键栏：只属会话，放在会话那栏终端下方 */}
        {primary && leadingActive && footer}
      </div>
    )
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex' }}
      onDragEnter={(e) => {
        if (dragging || !dragHasPayload(e)) return
        setDragging(true)
        // 文件树拖出的路径:onDragStart 在 FileBrowser 里不置 kind,这里补判(唯一非 tab/lead 的来源)
        setDragKind(e.dataTransfer.types.includes(PATH_MIME) ? 'path' : e.dataTransfer.types.includes(LEAD_MIME) ? 'lead' : 'tab')
      }}>
      {treeOpen && (
        <div style={{ flex: `0 0 ${dockW}px`, minWidth: 0, minHeight: 0, display: 'flex' }}>
          <FileBrowser dir={dir} accent={accent} layout="dock" onClose={onExplorerClose} onOpenFile={openFileTab} selectedPath={activeA ? realPath(activeA) : null} onOpenAgent={onOpenAgent} />
        </div>
      )}
      {/* 分栏把手统一走 .tt-split-rail（设计系统 §4.3）：细底槽 + 居中握把，
          别再自画一条 --border 实心竖条——那条在页面上就是一道大粗线。
          收起文件树后把手不撤：它带着的那枚握把是把树叫回来的第二条路（第一条是工具栏
          的「文件」按钮），撤了就只剩那一个入口。 */}
      <div data-resize-handle="dock" className={`tt-split-rail${treeOpen ? '' : ' collapsed'}`}
        role="separator" aria-orientation="vertical" tabIndex={0}
        aria-label={t('file.dragResize')} aria-valuemin={DOCK_MIN} aria-valuemax={DOCK_MAX}
        aria-valuenow={treeOpen ? Math.round(dockW) : 0}
        onPointerDown={treeOpen ? startResize : undefined} title={treeOpen ? t('file.dragResize') : undefined}
        onDoubleClick={treeOpen ? () => saveDockW(DOCK_DEFAULT) : undefined}
        onKeyDown={treeOpen ? (e) => railKey(e, (dir, big) => saveDockW(dockW + dir * (big ? 48 : 16)), () => saveDockW(DOCK_DEFAULT)) : undefined}>
        <RailControls collapsed={!treeOpen} side="left"
          label={treeOpen ? t('file.collapseTree') : t('file.expandTree')} onToggle={toggleTree}
          onStep={(dir) => saveDockW(dockW + dir * RAIL_STEP)}
          stepLabels={{ minus: t('file.narrowTree'), plus: t('file.widenTree') }} />
      </div>
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div ref={panesRef} style={{ flex: 1, minHeight: 0, display: 'flex' }}>
          {(split ? (swapped ? ['B', 'A'] : ['A', 'B']) : ['A'] as Group[]).map((g, i) => (
            // key 按组固定 → 易位/分栏时 React 不重挂终端(会话)，PTY/xterm 不断
            <Fragment key={g}>
              {i > 0 && (
                <div data-resize-handle="split" className="tt-split-rail"
                  role="separator" aria-orientation="vertical" tabIndex={0}
                  aria-label={t('file.dragResize')} aria-valuemin={15} aria-valuemax={85} aria-valuenow={Math.round(splitFrac * 100)}
                  onPointerDown={startSplitResize} title={t('file.dragResize')}
                  onDoubleClick={() => { setSplitFrac(0.5); saveFrac(0.5) }}
                  onKeyDown={(e) => railKey(
                    e,
                    (dir, big) => { const n = clampFrac(fracRef.current + dir * (big ? 0.1 : 0.02)); setSplitFrac(n); saveFrac(n) },
                    () => { setSplitFrac(0.5); saveFrac(0.5) },
                  )} />
              )}
              {pane(g as Group)}
            </Fragment>
          ))}
        </div>
      </div>
      {touchDrag && (
        <div style={{ position: 'fixed', left: touchDrag.x + 12, top: touchDrag.y + 12, zIndex: 9999, pointerEvents: 'none', padding: 'var(--sp-1) var(--sp-3)', fontSize: 'var(--fs-meta)', borderRadius: 'var(--r-xs)', background: 'var(--bg-container)', border: '1px solid var(--accent-border)', color: 'var(--text-bright)', boxShadow: 'var(--card-hover-shadow)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{touchDrag.label}</div>
      )}
      <PointerResizeShield active={resize.active} />
    </div>
  )
}
