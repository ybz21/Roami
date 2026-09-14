// 文件侧栏 —— 在 Claude / Codex 对话页右侧浏览工作目录、查看文件内容（类似 codex 右侧边栏）。
// 单层可导航列表：目录在前可进入、↑ 回上级、点文件在弹层里查看正文。
import { type ReactNode, Fragment, createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { nodeApi } from '../cluster/node-url'
import { AutoComplete, Button, ConfigProvider, Dropdown, Input, Modal, Spin, App as AntApp, Tooltip, type MenuProps } from 'antd'
import { api, upload } from '../../api'
import { useI18n } from '../../i18n'
import { download as p2pDownload } from '../../p2p/download'
import { pathLabelKey, type P2PPathLabel } from '../../p2p/labels'
import { P2PTransferStatus, type TransferView } from '../../p2p/P2PTransferStatus'
import { recentDirs } from '../sessions/DirPicker'
import { usePreferences } from '../../preferences'
import { dirname, fileNameOf, fmtSize, joinPath, normalizePath } from './file-utils'
import { loadExpandedDirs, saveExpandedDirs } from './tree-expansion-memory'
import { copyText } from '../chat/blocks'
import {
  BackIcon, Chevron, ClosePanelButton, CloseIcon, DownloadIcon, EyeIcon, EyeOffIcon, FileTypeIcon, FolderIcon,
  FolderUpIcon, ForwardIcon, IconButton, ListIcon, NewFolderIcon, RefreshIcon, SearchIcon, SortIcon, TreeIcon, UploadIcon,
} from './file-icons'
import { Viewer } from './fileview'
import { InspectorLayers, type LayerSize } from '../shell/InspectorLayers'
import { ArrowUp } from '../../icons'
import { searchContent } from '../search/client'
import type { SearchHit } from '../search/types'
import { composingEnter, onEnterSubmit } from '../../enter-submit'

interface Entry { name: string; dir: boolean; size: number; mtime: number; ctime: number }
interface Dir { path: string; parent: string; entries: Entry[] }
interface FileTarget extends Entry { path: string }
interface FileStat {
  path: string
  name: string
  dir: boolean
  size: number
  mtime: number
  ctime: number
  mode: string
  entryCount?: number
}

type SortKey = 'name' | 'kind' | 'mtime' | 'ctime' | 'size'

function entryExt(name: string): string {
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(i + 1).toLowerCase() : ''
}

function sortEntries(entries: Entry[], key: SortKey): Entry[] {
  const sorted = [...entries]
  sorted.sort((a, b) => {
    // ponytail: dirs always first, secondary sort by key
    if (a.dir !== b.dir) return a.dir ? -1 : 1
    switch (key) {
      case 'name': return a.name.localeCompare(b.name)
      case 'kind': return entryExt(a.name).localeCompare(entryExt(b.name)) || a.name.localeCompare(b.name)
      case 'mtime': return b.mtime - a.mtime || a.name.localeCompare(b.name)
      case 'ctime': return b.ctime - a.ctime || a.name.localeCompare(b.name)
      case 'size': return b.size - a.size || a.name.localeCompare(b.name)
    }
  })
  return sorted
}

function displayPath(path: string): string {
  return path || '/'
}

const PathOption = ({ kind, path, name, dir }: { kind: string; path: string; name?: string; dir?: boolean }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 260, maxWidth: 560 }}>
    <span style={{ color: dir ? 'var(--text-bright)' : 'var(--text-dimmer)', width: 20, display: 'inline-flex', justifyContent: 'center' }}>
      {dir ? <FolderIcon /> : name ? <FileTypeIcon name={name} /> : <FolderIcon />}
    </span>
    <span style={{ color: 'var(--text-bright)', fontSize: 12, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
      {name || path}
    </span>
    <span style={{ color: 'var(--text-dimmer)', fontSize: 11, flex: '0 0 auto' }}>{kind}</span>
  </div>
)
function formatJSON(text: string): string {
  try { return JSON.stringify(JSON.parse(text), null, 2) } catch { return text }
}

function fence(lang: string, content: string): string {
  return '```' + lang + '\n' + content + '\n```'
}

// 统一：把文件绝对路径写进拖拽载荷（对话框识别 application/x-ttmux-path，其余认 text/plain）。
function startPathDrag(ev: React.DragEvent, full: string) {
  ev.dataTransfer.setData('application/x-ttmux-path', full)
  ev.dataTransfer.setData('text/plain', full)
  ev.dataTransfer.effectAllowed = 'copy'
}

// 右键菜单的全部动作，收拢成一个对象在 FileBrowser → FileTree → FileContextMenu 间传递。
interface FileMenuActions {
  onOpen: (target: FileTarget) => void
  onRename: (target: FileTarget) => void
  onCopyTo: (target: FileTarget) => void
  onMoveTo: (target: FileTarget) => void
  onUploadHere: (target: FileTarget) => void
  onNewFile: (target: FileTarget) => void
  onNewFolder: (target: FileTarget) => void
  onDownload: (target: FileTarget) => void
  onCopyPath: (target: FileTarget) => void
  onProperties: (target: FileTarget) => void
  onDelete: (target: FileTarget) => void
  onInsertPath?: (path: string) => void
}

// 文件名 Tooltip 与右键 Dropdown 都基于浮层触发器。右键菜单打开时暂停 Tooltip，
// 避免鼠标从文件行移向菜单的过程中，两个浮层竞争 hover 状态而把菜单关闭。
const FileContextMenuOpen = createContext(false)

function FileContextMenu({ target, children, actions }: {
  target: FileTarget
  children: ReactNode
  actions: FileMenuActions
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLDivElement>(null)
  // rc-trigger 的 contextMenu 模式在右侧 fixed 抽屉里会把鼠标移入浮层误判成离开触发区，
  // 菜单刚出现就关闭。这里由文件行显式打开，并自行处理点外部/Escape 关闭。
  useEffect(() => {
    if (!open) return
    const closeOutside = (ev: PointerEvent) => {
      const node = ev.target as Node | null
      if (node && triggerRef.current?.contains(node)) return
      if (node instanceof Element && node.closest('.ant-dropdown')) return
      setOpen(false)
    }
    const closeOnEscape = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside, true)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside, true)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])
  const items: MenuProps['items'] = [
    { key: 'open', label: target.dir ? t('file.openFolder') : t('file.open') },
    { type: 'divider' as const },
    ...(target.dir ? [
      { key: 'newFile', label: t('file.newFile') },
      { key: 'newFolder', label: t('file.newFolder') },
      { key: 'uploadHere', label: t('file.uploadHere') },
      { type: 'divider' as const },
    ] : []),
    { key: 'rename', label: t('file.rename') },
    { key: 'copyTo', label: t('file.copyTo') },
    { key: 'moveTo', label: t('file.moveTo') },
    { type: 'divider' as const },
    { key: 'download', label: target.dir ? t('file.downloadZip') : t('file.download') },
    ...(actions.onInsertPath ? [{ key: 'insertPath', label: t('file.insertPath') }] : []),
    { key: 'copyPath', label: t('file.copyPath') },
    { key: 'properties', label: t('file.properties') },
    { type: 'divider' as const },
    { key: 'delete', label: t('file.delete'), danger: true },
  ]
  const onClick: MenuProps['onClick'] = ({ key, domEvent }) => {
    domEvent.stopPropagation()
    setOpen(false)
    if (key === 'open') actions.onOpen(target)
    else if (key === 'newFile') actions.onNewFile(target)
    else if (key === 'newFolder') actions.onNewFolder(target)
    else if (key === 'uploadHere') actions.onUploadHere(target)
    else if (key === 'rename') actions.onRename(target)
    else if (key === 'copyTo') actions.onCopyTo(target)
    else if (key === 'moveTo') actions.onMoveTo(target)
    else if (key === 'download') actions.onDownload(target)
    else if (key === 'insertPath') actions.onInsertPath?.(target.path)
    else if (key === 'copyPath') actions.onCopyPath(target)
    else if (key === 'properties') actions.onProperties(target)
    else if (key === 'delete') actions.onDelete(target)
  }
  return (
    <FileContextMenuOpen.Provider value={open}>
      <Dropdown
        trigger={[]}
        menu={{ items, onClick }}
        open={open}
        onOpenChange={setOpen}
        transitionName=""
        overlayClassName="tt-file-context-menu"
      >
        <div
          ref={triggerRef}
          className={open ? 'tt-file-context-open' : undefined}
          onContextMenu={(ev) => {
            ev.preventDefault()
            ev.stopPropagation()
            setOpen(true)
          }}
        >{children}</div>
      </Dropdown>
    </FileContextMenuOpen.Provider>
  )
}

// 统一：一行文件/目录的图标 + 名称 + 大小 + @插入 + 下载。平铺列表与树共用（外层容器各自处理缩进/展开）。
function FileRowBody({ full, name, isDir, size, accent, onInsertPath, onDownload }: {
  full: string; name: string; isDir: boolean; size: number; accent: string; onInsertPath?: (p: string) => void
  onDownload?: (t: FileTarget) => void
}) {
  const { t } = useI18n()
  const contextMenuOpen = useContext(FileContextMenuOpen)
  return (
    <>
      <span style={{ color: isDir ? accent : 'var(--text-dimmer)', flex: '0 0 auto', display: 'inline-flex', width: 22, justifyContent: 'center' }}>{isDir ? <FolderIcon /> : <FileTypeIcon name={name} />}</span>
      {/* 面板窄时名字被省略号截断 → 悬浮显示完整名字（长名换行显示，不再被裁掉） */}
      <Tooltip title={name} placement="topLeft" mouseEnterDelay={0.4} open={contextMenuOpen ? false : undefined} styles={{ root: { maxWidth: 420, wordBreak: 'break-all' } }}>
        <span style={{ color: 'var(--text-bright)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
      </Tooltip>
      {!isDir && <span style={{ color: 'var(--text-dimmer)', fontSize: 11, flex: '0 0 auto' }}>{fmtSize(size)}</span>}
      {onInsertPath && (
        <span data-file-action>
          <IconButton title={t('file.insertPath')} onClick={() => onInsertPath(full)}>@</IconButton>
        </span>
      )}
      {!isDir && (
        <span data-file-action>
          <Tooltip title={t('file.download')}>
            {/* 走 downloadEntry(P2P 直连状态机)，不再直连 frp 的 file/raw；无 onDownload 时才退回锚点。 */}
            {onDownload ? (
              <Button type="text" size="small" onClick={(e) => { e.stopPropagation(); onDownload({ path: full, name, dir: isDir, size, mtime: 0, ctime: 0 }) }}
                style={{ width: 24, height: 24, minWidth: 24, padding: 0, color: 'var(--text-dim)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><DownloadIcon /></Button>
            ) : (
              <Button type="text" size="small" href={nodeApi(`/file/raw?path=${encodeURIComponent(full)}&dl=1`)} download={name}
                style={{ width: 24, height: 24, minWidth: 24, padding: 0, color: 'var(--text-dim)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><DownloadIcon /></Button>
            )}
          </Tooltip>
        </span>
      )}
    </>
  )
}

// VSCode 风格可展开目录树：以 root 为根，子目录首次展开时懒加载（复用 GET /files?path=）。
// 排序/隐藏文件过滤、点文件预览、拖入终端 @mention、右键删除都与平铺行一致。
function FileTree({
  root, rootEntries, accent, showHidden, sortKey, tick, selected, onOpenFile, actions,
}: {
  root: string
  rootEntries: Entry[]
  accent: string
  showHidden: boolean
  sortKey: SortKey
  tick: number
  selected: string | null
  onOpenFile: (full: string) => void
  actions: FileMenuActions
}) {
  // 展开到哪几层记在本机（按根目录），刷新和换任务再回来都还在（tree-expansion-memory）
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(loadExpandedDirs(root)))
  const [childMap, setChildMap] = useState<Record<string, Entry[]>>({})
  const [loading, setLoading] = useState<Record<string, boolean>>({})
  const { t } = useI18n()

  const loadDir = (dirPath: string) => {
    setLoading((m) => ({ ...m, [dirPath]: true }))
    api('GET', `/files?path=${encodeURIComponent(dirPath)}`)
      .then((r) => setChildMap((m) => ({ ...m, [dirPath]: r.data?.entries || [] })))
      .catch(() => setChildMap((m) => ({ ...m, [dirPath]: [] })))
      .finally(() => setLoading((m) => ({ ...m, [dirPath]: false })))
  }
  // 静默重拉子项：不置 loading（保留旧子项直到新数据到），刷新时展开的目录不闪 spinner
  const reloadDir = (dirPath: string) => {
    api('GET', `/files?path=${encodeURIComponent(dirPath)}`)
      .then((r) => setChildMap((m) => ({ ...m, [dirPath]: r.data?.entries || [] })))
      .catch(() => {})
  }

  const prevRoot = useRef(root)
  // 换根目录 → 子项缓存作废，展开态换成**新根记着的那份**（旧根的展开对新目录无意义，
  // 但新根自己上次展开到哪儿是该留着的）。
  // 刷新(tick 变、root 不变) → 保留展开层级，静默重拉各已展开目录的子项，
  // 让新增/删除的文件显示出来而不折叠（顶层 rootEntries 由父组件随 tick 重拉）。
  // 挂载那一跑走的也是下面这支：把记着的那几层的子项拉回来，树才展得开。
  useEffect(() => {
    if (prevRoot.current !== root) {
      prevRoot.current = root
      const remembered = loadExpandedDirs(root)
      setExpanded(new Set(remembered)); setChildMap({}); setLoading({})
      remembered.forEach((dirPath) => loadDir(dirPath))
      return
    }
    expanded.forEach((dirPath) => reloadDir(dirPath))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root, tick])
  const toggleDir = (dirPath: string) => {
    // 在更新函数外面算好再 setState：里面顺手存盘的话，StrictMode 会把这段跑两遍
    const next = new Set(expanded)
    if (next.has(dirPath)) next.delete(dirPath)
    else { next.add(dirPath); if (!(dirPath in childMap)) loadDir(dirPath) }
    setExpanded(next)
    saveExpandedDirs(root, [...next])
  }
  const visible = (entries: Entry[]) => sortEntries((entries || []).filter((e) => showHidden || !e.name.startsWith('.')), sortKey)

  const renderLevel = (dirPath: string, entries: Entry[], depth: number): ReactNode =>
    visible(entries).map((e) => {
      const full = joinPath(dirPath, e.name)
      const target: FileTarget = { ...e, path: full }
      const isOpen = e.dir && expanded.has(full)
      return (
        <Fragment key={full}>
          <FileContextMenu target={target} actions={actions}>
            <div className="cc-filerow"
              draggable
              onDragStart={(ev) => startPathDrag(ev, full)}
              onClick={(ev) => {
                if ((ev.target as HTMLElement).closest('[data-file-action]')) return
                e.dir ? toggleDir(full) : onOpenFile(full)
              }}
              style={{ ...rowStyle(), gap: 0, padding: 0, alignItems: 'stretch', minHeight: 26, background: full === selected ? 'var(--accent-soft)' : undefined }}>
              {/* VSCode 式层级缩进导引线：每深一层一条竖线，逐行拼成连续的层级线 */}
              <span style={{ flex: '0 0 auto', width: 8 }} />
              {Array.from({ length: depth }).map((_, i) => (
                <span key={i} aria-hidden style={{ flex: '0 0 auto', width: 14, boxSizing: 'border-box', borderLeft: '1px solid var(--border-subtle)' }} />
              ))}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, flex: 1, minWidth: 0, padding: '4px 8px 4px 2px' }}>
                <span style={{ flex: '0 0 auto', width: 14, display: 'inline-flex', justifyContent: 'center', color: 'var(--text-dim)' }}>
                  {e.dir ? <Chevron open={!!isOpen} /> : null}
                </span>
                <FileRowBody full={full} name={e.name} isDir={e.dir} size={e.size} accent={accent} onInsertPath={actions.onInsertPath} onDownload={actions.onDownload} />
              </div>
            </div>
          </FileContextMenu>
          {isOpen && (
            loading[full]
              ? <div style={{ padding: '4px 0 4px', paddingLeft: 8 + (depth + 1) * 14 }}><Spin size="small" /></div>
              : renderLevel(full, childMap[full] || [], depth + 1)
          )}
        </Fragment>
      )
    })

  return <>{renderLevel(root, rootEntries, 0)}</>
}

// dock 布局的两层折叠（文件树 ｜ 预览）交给 <InspectorLayers>——Git 的「改动列表 ｜ diff」
// 用的是同一份机制，契约写在那个文件顶上。这里只给这两层的尺寸。
const TREE: LayerSize = { key: 'ttmux.fileTreeW', min: 180, max: 480, def: 300 } // 再窄就只剩省略号；300 够放两级缩进 + 20 个字
const PREVIEW: LayerSize = { key: 'ttmux.filePreviewW', min: 280, max: 1200, def: 560 } // 280 以下读不了代码；560 = 80 列等宽正文 + 留白

export default function FileBrowser({
  dir,
  accent = 'var(--accent)',
  layout = 'sidebar',
  onClose,
  onInsertPath,
  onOpenAgent,
  onOpenFile,
  selectedPath,
  openRequest,
  chrome = 'full',
  onOpenLine,
  focusSearchNonce,
}: {
  /** 全文搜索点中一行：开文件并定位到那一行；不传就只开文件 */
  onOpenLine?: (path: string, line: number) => void
  /** 外面（⌘⇧F）要求打开并聚焦搜索框；自增触发 */
  focusSearchNonce?: number
  /** 'tree'：只要树 + 搜索（右栏当前任务的文件面板，22 设计 §3.4）——标题行、项目芯片、路径框都不画，
      作用域头由外层给；'full' 是今天的文件管理器 */
  chrome?: 'full' | 'tree'
  dir?: string
  accent?: string
  layout?: 'sidebar' | 'split' | 'dock'
  onClose?: () => void
  onInsertPath?: (p: string) => void
  onOpenAgent?: (kind: 'claude' | 'codex', path: string) => void
  // dock 布局下由外层（编辑器 tab 区）接管文件打开：点文件不再弹内置预览，而是回调让外层开 tab。
  onOpenFile?: (path: string) => void
  /** 外部要求打开某个路径（对话里点 Read/Edit 的文件名）。
      nonce 自增才触发——同一个文件点第二次时 path 没变，没有 nonce 就毫无反应。 */
  openRequest?: { path: string; nonce: number }
  // 外层当前激活的文件 tab，用于在浏览器里高亮选中项（覆盖内部 view）。
  selectedPath?: string | null
}) {
  const [path, setPath] = useState(dir || '')
  const [data, setData] = useState<Dir | null>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<string | null>(null)
  const [pathDraft, setPathDraft] = useState('')
  const [tick, setTick] = useState(0) // 上传后强制重载当前目录
  const [uploading, setUploading] = useState(false)
  const [history, setHistory] = useState<string[]>([dir || '']) // 浏览器式前进/后退历史
  const [histIdx, setHistIdx] = useState(0)
  const [mkdirOpen, setMkdirOpen] = useState(false)
  const [mkdirName, setMkdirName] = useState('')
  const [mkdirBusy, setMkdirBusy] = useState(false)
  const [renameTarget, setRenameTarget] = useState<FileTarget | null>(null)
  const [renameName, setRenameName] = useState('')
  const [renameBusy, setRenameBusy] = useState(false)
  const [mkdirDir, setMkdirDir] = useState<string | null>(null) // 右键「新建目录」的目标目录；空则用当前目录
  const [touchDir, setTouchDir] = useState<string | null>(null) // 新建文件弹窗的目标目录；null 表示关闭
  const [touchName, setTouchName] = useState('')
  const [touchBusy, setTouchBusy] = useState(false)
  const [moveTarget, setMoveTarget] = useState<FileTarget | null>(null)
  const [moveDest, setMoveDest] = useState('')
  const [moveBusy, setMoveBusy] = useState(false)
  const [copyTarget, setCopyTarget] = useState<FileTarget | null>(null)
  const [copyDest, setCopyDest] = useState('')
  const [copyBusy, setCopyBusy] = useState(false)
  const [propertiesTarget, setPropertiesTarget] = useState<FileTarget | null>(null)
  const [properties, setProperties] = useState<FileStat | null>(null)
  const [propertiesLoading, setPropertiesLoading] = useState(false)
  const [showHidden, setShowHidden] = useState(false) // 隐藏文件（点号开头）默认不显示，眼睛开关切换
  const [sortKey, setSortKey] = useState<SortKey>('name')
  // P2P 传输可见状态：按 transferId 维护进行中的下载，展示角标/进度/详情（§5.7）。
  const [transfers, setTransfers] = useState<TransferView[]>([])
  // 递归按文件名搜索（当前目录向下），放大镜开关切换；有查询词时列表区改显搜索结果。
  const [searchOpen, setSearchOpen] = useState(chrome === 'tree') // 树模式一上来就带搜索框
  const [query, setQuery] = useState('')
  const searchRef = useRef<import('antd').InputRef>(null)
  useEffect(() => { if (focusSearchNonce) { setSearchOpen(true); setTimeout(() => searchRef.current?.focus(), 0) } }, [focusSearchNonce])
  const [results, setResults] = useState<{ path: string; name: string; rel: string }[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchTrunc, setSearchTrunc] = useState(false)
  // 平铺列表 / VSCode 树 两种展示，所有文件面板都可切；localStorage 记住选择。
  // dock（新标签左侧）与 split（独立 Files 页）默认树模式，会话右侧抽屉(sidebar)默认平铺。
  const canToggleView = true
  const [browseMode, setBrowseMode] = useState<'flat' | 'tree'>(() => {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('ttmux.fileBrowseMode') : null
    if (saved === 'tree' || saved === 'flat') return saved
    return layout === 'sidebar' ? 'flat' : 'tree'
  })
  useEffect(() => {
    if (canToggleView && typeof localStorage !== 'undefined') localStorage.setItem('ttmux.fileBrowseMode', browseMode)
  }, [browseMode, canToggleView])
  const fileRef = useRef<HTMLInputElement>(null)
  const uploadTargetRef = useRef<string | null>(null)
  const { message, modal } = AntApp.useApp()
  const { t, locale } = useI18n()
  const [prefs] = usePreferences() // P2P 直连下载开关（设置页可关，网络抖动时回退纯 frp）

  // 会话切换（dir 变化）→ 回到工作目录根，并重置历史
  // 预览也一起收：树都回新会话的工作目录了，右边还挂着上个会话（往往是另一个项目）的文件，
  // 看起来就是「点开文件面板，它自己带出个不相干的旧文件」。
  // 首帧的 '' → cwd 不算切会话（cwd 是异步取回来的），那会把刚从对话里点开的文件误关掉。
  const prevDirRef = useRef(dir)
  useEffect(() => {
    setPath(dir || '')
    setHistory([dir || ''])
    setHistIdx(0)
    if (prevDirRef.current && prevDirRef.current !== dir) setView(null)
    prevDirRef.current = dir
  }, [dir])

  // 进入新目录：截断当前位置之后的前进记录，再追加并前移
  const navigate = (target: string) => {
    if (target === path) return
    setPath(target)
    setView(null)
    setHistory((h) => [...h.slice(0, histIdx + 1), target])
    setHistIdx((i) => i + 1)
  }
  const canBack = histIdx > 0
  const canForward = histIdx < history.length - 1
  const goBack = () => {
    if (!canBack) return
    const i = histIdx - 1
    setHistIdx(i); setPath(history[i]); setView(null)
  }
  const goForward = () => {
    if (!canForward) return
    const i = histIdx + 1
    setHistIdx(i); setPath(history[i]); setView(null)
  }

  useEffect(() => {
    let stop = false
    setErr('')
    setLoading(true)
    const q = path ? `?path=${encodeURIComponent(path)}` : ''
    api('GET', `/files${q}`)
      .then((r) => { if (!stop) setData(r.data) })
      .catch((e: any) => { if (!stop) setErr(e.apiError?.code === 'DIR_ACCESS_TIMEOUT' ? t('file.dirAccessTimeout', { path: e.apiError.path || path }) : e.message) })
      .finally(() => { if (!stop) setLoading(false) })
    return () => { stop = true }
  }, [path, tick])

  const cur = data?.path || path
  const refresh = () => setTick((t) => t + 1)
  const goUp = () => { if (data && canUp) navigate(data.parent) }
  // 隐藏文件（点号开头）默认过滤掉；眼睛开关开启后全部显示。
  const visibleEntries = sortEntries((data?.entries || []).filter((e) => showHidden || !e.name.startsWith('.')), sortKey)
  const hiddenCount = (data?.entries.length || 0) - visibleEntries.length

  useEffect(() => {
    setPathDraft(displayPath(cur))
  }, [cur])

  // 递归文件名搜索：防抖 250ms，作用域为当前目录 cur。
  const searchQ = query.trim()
  useEffect(() => {
    if (!searchOpen || !searchQ || !cur) { setResults(null); setSearching(false); return }
    setSearching(true)
    let stop = false
    const h = setTimeout(() => {
      api('GET', `/file/search?dir=${encodeURIComponent(cur)}&q=${encodeURIComponent(searchQ)}`)
        .then((r) => { if (!stop) { setResults(r.data?.results || []); setSearchTrunc(!!r.data?.truncated) } })
        .catch(() => { if (!stop) { setResults([]); setSearchTrunc(false) } })
        .finally(() => { if (!stop) setSearching(false) })
    }, 250)
    return () => { stop = true; clearTimeout(h) }
  }, [searchQ, searchOpen, cur, tick])

  // 全文搜索（回车才跑：比名字搜索贵一到两个数量级）。同一个框：打字按名字过滤，回车搜内容；
  // 改了字就退回名字结果。原来右栏另开一段「全文搜索」，两个搜索框并排没人分得清哪个是哪个
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [hitsMeta, setHitsMeta] = useState<{ truncated: boolean; tookMs: number } | null>(null)
  const [hitsBusy, setHitsBusy] = useState(false)
  const [hitsErr, setHitsErr] = useState('')
  const hitsAbort = useRef<AbortController | null>(null)
  const runContentSearch = async () => {
    const q = query.trim()
    if (!q || !cur) return
    hitsAbort.current?.abort()
    const ac = new AbortController()
    hitsAbort.current = ac
    setHitsBusy(true); setHitsErr('')
    try {
      const r = await searchContent(q, { dir: cur, signal: ac.signal })
      if (ac.signal.aborted) return
      setHits(r.hits); setHitsMeta({ truncated: r.truncated, tookMs: r.tookMs })
    } catch (e: any) {
      if (!ac.signal.aborted) setHitsErr(e?.message || String(e))
    } finally {
      if (!ac.signal.aborted) setHitsBusy(false)
    }
  }
  useEffect(() => { hitsAbort.current?.abort(); setHits(null); setHitsMeta(null); setHitsErr(''); setHitsBusy(false) }, [query, cur])
  const hitGroups = useMemo(() => {
    const groups: { path: string; rel: string; lines: SearchHit[] }[] = []
    for (const h of hits || []) {
      const g = groups.find((x) => x.path === h.path)
      if (g) g.lines.push(h); else groups.push({ path: h.path!, rel: h.subtitle || h.path!, lines: [h] })
    }
    return groups
  }, [hits])

  const doUpload = async (files: FileList | File[], targetDir = cur) => {
    if (!files || !files.length || !targetDir || uploading) return
    setUploading(true)
    try {
      const res = await upload(targetDir, files)
      message.success(t('file.uploadedCount', { count: res.saved.length }))
      refresh()
    } catch (e: any) { message.error(t('chat.uploadFailed', { message: e.message })) }
    finally { setUploading(false) }
  }
  const doMkdir = async () => {
    const name = mkdirName.trim()
    const dir = mkdirDir || cur
    if (!name || !dir || mkdirBusy) return
    setMkdirBusy(true)
    try {
      await api('POST', '/file/mkdir', { dir, name })
      message.success(t('file.folderCreated'))
      setMkdirOpen(false)
      setMkdirName('')
      setMkdirDir(null)
      refresh()
    } catch (e: any) { message.error(t('file.mkdirFailed', { message: e.message })) }
    finally { setMkdirBusy(false) }
  }
  const doTouch = async () => {
    const name = touchName.trim()
    if (!name || !touchDir || touchBusy) return
    setTouchBusy(true)
    try {
      const res = await api('POST', '/file/touch', { dir: touchDir, name })
      message.success(t('file.fileCreated'))
      setTouchDir(null)
      setTouchName('')
      refresh()
      if (res.data?.path) openFile(res.data.path)
    } catch (e: any) { message.error(t('file.newFileFailed', { message: e.message })) }
    finally { setTouchBusy(false) }
  }
  const deletePath = async (target: string, recursive = false) => {
    try {
      const res = await api('DELETE', `/file?path=${encodeURIComponent(target)}${recursive ? '&recursive=1' : ''}`)
      message.success(res.data?.missing ? t('file.alreadyMissingRefreshed') : t('file.deleted'))
      if (view === target) setView(null)
      refresh()
    } catch (e: any) {
      message.error(t('file.deleteFailed', { message: e.message }))
      throw e
    }
  }
  const confirmDelete = (target: string, isDir: boolean) => {
    modal.confirm({
      title: isDir ? t('file.deleteDirConfirm') : t('file.deleteFileConfirm'),
      content: target,
      okText: t('file.delete'),
      cancelText: t('common.cancel'),
      okButtonProps: { danger: true },
      onOk: () => deletePath(target, isDir),
    })
  }
  const confirmDeleteTarget = (target: FileTarget) => confirmDelete(target.path, target.dir)
  const openEntry = (target: FileTarget) => { target.dir ? navigate(target.path) : openFile(target.path) }
  const startRename = (target: FileTarget) => {
    setRenameTarget(target)
    setRenameName(target.name)
  }
  const doRename = async () => {
    const name = renameName.trim()
    if (!renameTarget || !name || renameBusy) return
    setRenameBusy(true)
    try {
      const res = await api('POST', '/file/rename', { path: renameTarget.path, name })
      message.success(t('file.renamed'))
      if (view === renameTarget.path) setView(res.data?.path || null)
      setRenameTarget(null)
      refresh()
    } catch (e: any) { message.error(t('file.renameFailed', { message: e.message })) }
    finally { setRenameBusy(false) }
  }
  const startCopy = (target: FileTarget) => {
    setCopyTarget(target)
    setCopyDest(joinPath(dirname(target.path), target.name))
  }
  const doCopy = async () => {
    const target = copyDest.trim()
    if (!copyTarget || !target || copyBusy) return
    setCopyBusy(true)
    try {
      await api('POST', '/file/copy', { path: copyTarget.path, target: resolveTypedPath(target) })
      message.success(t('file.copiedToPath'))
      setCopyTarget(null)
      refresh()
    } catch (e: any) { message.error(t('file.copyToFailed', { message: e.message })) }
    finally { setCopyBusy(false) }
  }
  const startMove = (target: FileTarget) => {
    setMoveTarget(target)
    setMoveDest(joinPath(dirname(target.path), target.name))
  }
  const doMove = async () => {
    const target = moveDest.trim()
    if (!moveTarget || !target || moveBusy) return
    setMoveBusy(true)
    try {
      const res = await api('POST', '/file/move', { path: moveTarget.path, target: resolveTypedPath(target) })
      message.success(t('file.movedToPath'))
      if (view === moveTarget.path) setView(res.data?.path || null)
      setMoveTarget(null)
      refresh()
    } catch (e: any) { message.error(t('file.moveToFailed', { message: e.message })) }
    finally { setMoveBusy(false) }
  }
  const mkdirInto = (target: FileTarget) => {
    setMkdirDir(target.path)
    setMkdirName('')
    setMkdirOpen(true)
  }
  const touchInto = (target: FileTarget) => {
    setTouchDir(target.path)
    setTouchName('')
  }
  const copyEntryPath = (target: FileTarget) => {
    copyText(target.path)
    message.success(t('file.pathCopied'))
  }
  const uploadInto = (target: FileTarget) => {
    uploadTargetRef.current = target.dir ? target.path : dirname(target.path)
    fileRef.current?.click()
  }
  // legacy：系统 a[download]（走 frp）。手机护栏命中或不支持 File System Access 时用它。
  const legacyAnchorDownload = (target: FileTarget) => {
    const a = document.createElement('a')
    a.href = nodeApi(`/file/download?path=${encodeURIComponent(target.path)}`)
    a.download = target.dir ? `${target.name}.zip` : target.name
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }
  // 更新某条传输的视图字段（按 transferId 合并）。
  const patchTransfer = (id: string, patch: Partial<TransferView>) =>
    setTransfers((list) => list.map((tf) => (tf.id === id ? { ...tf, ...patch } : tf)))
  const dropTransfer = (id: string) => setTransfers((list) => list.filter((tf) => tf.id !== id))
  const downloadEntry = (target: FileTarget) => {
    // 用户开关关闭（网络抖动等）→ 一律走 frp 中转，不碰 P2P。
    if (!prefs.p2pEnabled) {
      legacyAnchorDownload(target)
      return
    }
    // 护栏（技术拆解 §4.5）：只有目录仍走 legacy（目录 P2P 是后续）。
    // 大小/浏览器能力判断已收敛进 download.ts 的三级 sink：
    //   picker（Chromium 桌面）/ StreamSaver（移动端·Firefox·Safari，自托管流式落盘，不占内存、任意大小）
    //   都是流式落盘，移动端大文件也走 P2P；只有「无 picker 且无 StreamSaver 且超 Blob 上限」才由
    //   download.ts 经 blobFallback 回退 frp。故此处不再对移动端大文件无脑走 frp。
    if (target.dir) {
      legacyAnchorDownload(target)
      return
    }
    // 一条可见传输：先建条目（negotiating），download.ts 各回调实时刷角标/进度/详情。
    const id = `${target.path}#${Date.now()}`
    const initial: TransferView = { id, name: target.name, state: 'negotiating', fellBack: false }
    setTransfers((list) => [...list, initial])
    void p2pDownload({ path: target.path, name: target.name, size: target.size }, {
      onState: (state) => patchTransfer(id, { state }),
      onFallback: (reason) => { patchTransfer(id, { fellBack: true, fallbackReason: reason }); message.info(t('p2p.fellBackToHttp')) },
      onPath: (label: P2PPathLabel) => {
        patchTransfer(id, { path: label })
        if (label !== 'frp') message.success(t('p2p.connectedVia', { path: t(pathLabelKey(label)) }))
      },
      onProgress: (p) => patchTransfer(id, { progress: p }),
      onDiagnostics: (d) => patchTransfer(id, { diag: d }),
      onDone: () => {
        message.success(t('p2p.downloadDone', { name: target.name }))
        // 完成后短暂保留完成态，随后移除角标。
        window.setTimeout(() => dropTransfer(id), 4000)
      },
      onError: (msg) => { message.error(t('p2p.downloadFailed', { message: msg })); dropTransfer(id) },
    }, {
      // Blob sink 路径（无 picker）P2P 真失败时兜底：触发 legacy frp 系统下载（唯一一次）。
      blobFallback: () => legacyAnchorDownload(target),
    })
  }
  const showProperties = async (target: FileTarget) => {
    setPropertiesTarget(target)
    setProperties(null)
    setPropertiesLoading(true)
    try {
      const res = await api('GET', `/file/stat?path=${encodeURIComponent(target.path)}`)
      setProperties(res.data)
    } catch (e: any) {
      message.error(t('file.propertiesFailed', { message: e.message }))
    } finally {
      setPropertiesLoading(false)
    }
  }
  const fmtTime = (ts?: number) => {
    if (!ts) return t('file.unknown')
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(ts * 1000))
  }
  // 根目录之上不再回退（防止越过工作目录乱逛；dir 为空时允许一直向上）
  const canUp = !!data && data.parent !== data.path && (!dir || cur !== dir)

  // 打开一个文件：dock 布局把打开交给外层（开编辑器 tab），否则用内置预览。
  const openFile = (target: string) => { if (onOpenFile) onOpenFile(target); else setView(target) }
  // 浏览器里高亮的选中项：外层受控（selectedPath）优先，否则用内部 view。
  const sel = selectedPath !== undefined ? selectedPath : view

  // 右键菜单全部动作，平铺列表与树共用一份。
  const menuActions: FileMenuActions = {
    onOpen: openEntry,
    onRename: startRename,
    onCopyTo: startCopy,
    onMoveTo: startMove,
    onUploadHere: uploadInto,
    onNewFile: touchInto,
    onNewFolder: mkdirInto,
    onDownload: downloadEntry,
    onCopyPath: copyEntryPath,
    onProperties: showProperties,
    onDelete: confirmDeleteTarget,
    onInsertPath,
  }

  const openPath = async (target: string) => {
    try {
      const res = await api('GET', `/file/stat?path=${encodeURIComponent(target)}`)
      if (res.data?.dir) {
        navigate(target)
      } else {
        openFile(target)
      }
    } catch (e: any) {
      message.error(t('file.openReferenceFailed', { message: e.message }))
    }
  }

  // 对话里点了文件名 → 在这个浏览器里打开它：先把树导航到它所在目录，再开预览。
  // 走 openPath 而不是直接 setView：不 navigate 的话左边的树还停在别处，
  // 你看到的是「一个文件凭空出现」，不知道它在哪。
  // 两栏并排的下限：窄于这个宽度就只显示一栏。420 的抽屉硬塞两栏，
  // 树只剩 160、预览只剩 250，两边都没法看——宁可少一栏，也不要两栏都残。
  const openReqRef = useRef(0)
  useEffect(() => {
    if (!openRequest?.path || openRequest.nonce === openReqRef.current) return
    openReqRef.current = openRequest.nonce
    const dirOf = openRequest.path.replace(/\/[^/]*$/, '') || '/'
    navigate(dirOf)
    openFile(openRequest.path)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRequest?.path, openRequest?.nonce])

  const resolveTypedPath = (value: string): string => {
    const raw = value.trim()
    if (!raw) return cur || '/'
    if (raw.startsWith('/')) return normalizePath(raw)
    return normalizePath(joinPath(cur || '/', raw))
  }

  const submitTypedPath = (value = pathDraft) => {
    const target = resolveTypedPath(value)
    setPathDraft(displayPath(target))
    openPath(target)
  }

  const pathOptions = useMemo(() => {
    const q = pathDraft.trim().toLowerCase()
    const list: { value: string; label: ReactNode }[] = []
    const add = (value: string, label: ReactNode) => {
      if (!value || list.some((x) => x.value === value)) return
      if (q && !value.toLowerCase().includes(q) && !fileNameOf(value).toLowerCase().includes(q)) return
      list.push({ value, label })
    }
    if (cur) add(cur, <PathOption kind={t('file.currentLocation')} path={cur} />)
    if (data?.parent && data.parent !== cur) add(data.parent, <PathOption kind={t('file.parentDir')} path={data.parent} />)
    if (dir && dir !== cur) add(dir, <PathOption kind={t('file.workingDir')} path={dir} />)
    for (const e of data?.entries || []) {
      const full = joinPath(cur || '/', e.name)
      add(full, <PathOption kind={e.dir ? t('file.directory') : t('common.file')} path={full} name={e.name} dir={e.dir} />)
    }
    return list.slice(0, 24)
  }, [cur, data?.entries, data?.parent, dir, pathDraft])

  const browserPane = (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', minHeight: 0, width: '100%', background: 'var(--bg-container)', borderLeft: '1px solid var(--border-subtle)', position: 'relative', overflow: 'hidden' }}>
      <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
        {chrome !== 'tree' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span style={{ color: accent }}><FolderIcon /></span>
            <span style={{ color: 'var(--text-bright)', fontWeight: 600, fontSize: 13 }}>{t('chat.fileManager')}</span>
            <span style={{ flex: 1 }} />
            {onClose && <ClosePanelButton title={t('file.closePanel')} onClick={onClose} />}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'nowrap', overflowX: 'auto' }}>
          <input ref={fileRef} type="file" multiple style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files?.length) doUpload(e.target.files, uploadTargetRef.current || cur)
              uploadTargetRef.current = null
              e.target.value = ''
            }} />
          <IconButton title={t('file.back')} disabled={!canBack} onClick={goBack}><BackIcon /></IconButton>
          <IconButton title={t('file.forward')} disabled={!canForward} onClick={goForward}><ForwardIcon /></IconButton>
          <IconButton title={t('file.up')} disabled={!canUp} onClick={goUp}><FolderUpIcon /></IconButton>
          <IconButton title={t('file.refreshDir')} onClick={refresh}><RefreshIcon /></IconButton>
          <IconButton title={showHidden ? t('file.hideHidden') : t('file.showHidden')} onClick={() => setShowHidden((s) => !s)}>{showHidden ? <EyeIcon /> : <EyeOffIcon />}</IconButton>
          {canToggleView && (
            <IconButton title={browseMode === 'tree' ? t('file.flatView') : t('file.treeView')} onClick={() => setBrowseMode((m) => (m === 'tree' ? 'flat' : 'tree'))}>{browseMode === 'tree' ? <ListIcon /> : <TreeIcon />}</IconButton>
          )}
          <IconButton title={t('file.searchFiles')} onClick={() => { setSearchOpen((s) => { if (s) setQuery(''); return !s }) }}><SearchIcon /></IconButton>
          <Dropdown menu={{ items: ([['name', 'file.sort.name'], ['kind', 'file.sort.kind'], ['mtime', 'file.sort.mtime'], ['ctime', 'file.sort.ctime'], ['size', 'file.sort.size']] as const).map(([k, label]) => ({ key: k, label: t(label), style: k === sortKey ? { color: accent, fontWeight: 600 } : undefined, onClick: () => setSortKey(k) })) }} trigger={['click']}>
            <Tooltip title={t('file.sort')}>
              <Button type="text" size="small" style={{ width: 24, height: 24, minWidth: 24, padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><SortIcon /></Button>
            </Tooltip>
          </Dropdown>
          <IconButton title={t('file.newFolder')} disabled={!cur} onClick={() => { setMkdirName(''); setMkdirDir(null); setMkdirOpen(true) }}><NewFolderIcon /></IconButton>
          <IconButton title={t('file.uploadHere')} disabled={uploading || !cur} onClick={() => { uploadTargetRef.current = cur; fileRef.current?.click() }}>{uploading ? <Spin size="small" /> : <UploadIcon />}</IconButton>
        </div>
      </div>
      {searchOpen && (
        <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
          <Input
            ref={searchRef}
            size="small"
            autoFocus
            allowClear
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={(e) => { if (composingEnter(e)) return; void runContentSearch() }}
            prefix={<span style={{ color: 'var(--text-dimmer)', display: 'inline-flex' }}><SearchIcon /></span>}
            suffix={searching || hitsBusy ? <Spin size="small" /> : null}
            placeholder={t('file.searchPlaceholder')}
            style={{ fontSize: 12 }}
          />
        </div>
      )}
      {chrome !== 'tree' && (
      <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
        {(() => {
          const chips: { label: string; path: string }[] = []
          const seen = new Set<string>()
          const add = (label: string, path: string) => { if (path && !seen.has(path)) { seen.add(path); chips.push({ label, path }) } }
          if (dir) add(t('file.workingDir'), dir)
          for (const rd of recentDirs()) { if (rd !== dir) add(fileNameOf(rd), rd) }
          return chips.length > 0 ? (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
              {chips.map((c) => (
                <Tooltip key={c.path} title={c.path}>
                  <span onClick={() => navigate(c.path)} style={{
                    cursor: 'pointer', fontSize: 11, padding: '1px 8px', borderRadius: 4,
                    background: c.path === cur ? 'var(--accent-solid)' : 'var(--bg-base)', color: c.path === cur ? '#fff' : 'var(--text-dim)',
                    border: '1px solid var(--border-subtle)', whiteSpace: 'nowrap',
                  }}>{c.label}</span>
                </Tooltip>
              ))}
            </div>
          ) : null
        })()}
        <AutoComplete
          value={pathDraft}
          options={pathOptions}
          onChange={(v) => setPathDraft(v)}
          onSelect={(v) => submitTypedPath(v)}
          style={{ width: '100%' }}
          popupMatchSelectWidth={false}
          filterOption={false}
        >
          <Input.Search
            size="small"
            allowClear
            enterButton={t('file.open')}
            onSearch={(v) => submitTypedPath(v)}
            onPressEnter={(e) => { if (composingEnter(e)) return; submitTypedPath((e.target as HTMLInputElement).value) }}
            placeholder={t('file.pathPlaceholder')}
            style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }}
          />
        </AutoComplete>
      </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '4px 0' }}>
        {searchOpen && searchQ && (hits !== null || hitsBusy || hitsErr) ? (
          <div className="tt-csearch" style={{ padding: '0 6px 8px' }}>
            {hitsBusy && <div className="tt-csearch-note"><Spin size="small" /></div>}
            {!hitsBusy && hitsErr && <div className="tt-csearch-note">{hitsErr}</div>}
            {!hitsBusy && !hitsErr && hits && hits.length === 0 && <div className="tt-csearch-note">{t('search.contentNone')}</div>}
            {!hitsBusy && !hitsErr && hits && hits.length > 0 && hitsMeta && (
              <div className="tt-csearch-note">{t('search.contentSummary', { n: hits.length, files: hitGroups.length, ms: hitsMeta.tookMs })}{hitsMeta.truncated ? ` · ${t('search.contentTruncated')}` : ''}</div>
            )}
            {!hitsBusy && hitGroups.map((g) => (
              <div key={g.path} className="tt-csearch-file">
                <button type="button" className="tt-csearch-fname" onClick={() => openFile(g.path)} title={g.path}>
                  <span className="fi"><FileTypeIcon name={g.rel} /></span>
                  <span className="nm">{g.rel.split('/').pop()}</span>
                  <span className="dir">{g.rel.split('/').slice(0, -1).join('/')}</span>
                  <span className="cnt">{g.lines.length}</span>
                </button>
                {g.lines.map((h) => (
                  <button key={h.id} type="button" className="tt-csearch-line" onClick={() => (onOpenLine && h.line != null ? onOpenLine(g.path, h.line) : openFile(g.path))} title={`${g.rel}:${h.line}`}>
                    <span className="no">{h.line}</span><span className="tx">{h.title}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        ) : searchOpen && searchQ ? (
          searching && !results ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 16 }}><Spin size="small" /></div>
          ) : results && results.length === 0 ? (
            <div style={{ color: 'var(--text-dimmer)', fontSize: 12, padding: '6px 10px' }}>{t('file.noMatches')}</div>
          ) : (
            <>
              <div className="tt-csearch-note" style={{ padding: '4px 10px' }}>{t('file.enterForContent', { q: searchQ })}</div>
              {searchTrunc && <div style={{ color: '#d29922', fontSize: 11, padding: '4px 10px' }}>{t('file.searchTruncated')}</div>}
              {(results || []).map((r) => (
                <div key={r.path} className="cc-filerow" draggable
                  onDragStart={(ev) => startPathDrag(ev, r.path)}
                  onClick={() => openFile(r.path)}
                  style={{ ...rowStyle(), background: r.path === sel ? 'var(--accent-soft)' : undefined }}>
                  <span style={{ color: 'var(--text-dimmer)', flex: '0 0 auto', display: 'inline-flex', width: 25, justifyContent: 'center' }}><FileTypeIcon name={r.name} /></span>
                  <Tooltip title={<><div>{r.name}</div><div style={{ opacity: .65, fontSize: 11 }}>{r.rel}</div></>} placement="topLeft" mouseEnterDelay={0.4} styles={{ root: { maxWidth: 420, wordBreak: 'break-all' } }}>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ color: 'var(--text-bright)', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
                      <span style={{ color: 'var(--text-dimmer)', fontSize: 11, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.rel}</span>
                    </span>
                  </Tooltip>
                </div>
              ))}
            </>
          )
        ) : (
        <>
        {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: 16 }}><Spin size="small" /></div>}
        {err && <div style={{ color: '#f85149', fontSize: 12, padding: '6px 10px' }}>{err}</div>}
        {canUp && (
          <div onClick={goUp} style={rowStyle()}>
            <span style={{ color: 'var(--text-dim)', display: 'inline-flex' }}><ArrowUp size={13} /></span><span style={{ color: 'var(--text-dim)' }}>{t('file.parentDir')}</span>
          </div>
        )}
        {browseMode === 'tree' ? (
          <FileTree root={cur} rootEntries={data?.entries || []} accent={accent} showHidden={showHidden} sortKey={sortKey} tick={tick} selected={sel} onOpenFile={openFile} actions={menuActions} />
        ) : visibleEntries.map((e) => {
          const full = joinPath(cur, e.name)
          const target: FileTarget = { ...e, path: full }
          return (
            <FileContextMenu key={e.name} target={target} actions={menuActions}>
              <div className="cc-filerow"
                draggable
                onDragStart={(ev) => startPathDrag(ev, full)}
                onClick={(ev) => {
                  if ((ev.target as HTMLElement).closest('[data-file-action]')) return
                  e.dir ? navigate(full) : openFile(full)
                }}
                style={{ ...rowStyle(), background: full === sel ? 'var(--accent-soft)' : undefined }}>
                <FileRowBody full={full} name={e.name} isDir={e.dir} size={e.size} accent={accent} onInsertPath={onInsertPath} onDownload={downloadEntry} />
              </div>
            </FileContextMenu>
          )
        })}
        {data && data.entries.length === 0 && <div style={{ color: 'var(--text-dimmer)', fontSize: 12, padding: '6px 10px' }}>{t('file.emptyDirectory')}</div>}
        {browseMode !== 'tree' && data && data.entries.length > 0 && visibleEntries.length === 0 && (
          <div style={{ color: 'var(--text-dimmer)', fontSize: 12, padding: '6px 10px' }}>{t('file.allHidden', { count: hiddenCount })}</div>
        )}
        </>
        )}
      </div>
      <P2PTransferStatus transfers={transfers} onDismiss={dropTransfer} />
      <Modal
        open={mkdirOpen}
        title={t('file.newFolder')}
        okText={t('file.create')}
        cancelText={t('common.cancel')}
        confirmLoading={mkdirBusy}
        onOk={doMkdir}
        onCancel={() => { setMkdirOpen(false); setMkdirName(''); setMkdirDir(null) }}
      >
        <Input autoFocus value={mkdirName} onChange={(e) => setMkdirName(e.target.value)} onPressEnter={onEnterSubmit(doMkdir)} placeholder={t('file.folderName')} />
        <div style={{ marginTop: 8, color: 'var(--text-dimmer)', fontSize: 12, wordBreak: 'break-all' }}>
          {t('file.createUnder', { path: displayPath(mkdirDir || cur) })}
        </div>
      </Modal>
      <Modal
        open={touchDir !== null}
        title={t('file.newFile')}
        okText={t('file.create')}
        cancelText={t('common.cancel')}
        confirmLoading={touchBusy}
        onOk={doTouch}
        onCancel={() => { setTouchDir(null); setTouchName('') }}
      >
        <Input autoFocus value={touchName} onChange={(e) => setTouchName(e.target.value)} onPressEnter={onEnterSubmit(doTouch)} placeholder={t('file.fileName')} />
        <div style={{ marginTop: 8, color: 'var(--text-dimmer)', fontSize: 12, wordBreak: 'break-all' }}>
          {touchDir ? t('file.createUnder', { path: displayPath(touchDir) }) : null}
        </div>
      </Modal>
      <Modal
        open={!!moveTarget}
        title={t('file.moveTo')}
        okText={t('common.move')}
        cancelText={t('common.cancel')}
        confirmLoading={moveBusy}
        onOk={doMove}
        onCancel={() => { setMoveTarget(null); setMoveDest('') }}
      >
        <Input autoFocus value={moveDest} onChange={(e) => setMoveDest(e.target.value)} onPressEnter={onEnterSubmit(doMove)} placeholder={t('file.copyTargetPlaceholder')} />
        <div style={{ marginTop: 8, color: 'var(--text-dimmer)', fontSize: 12, wordBreak: 'break-all' }}>
          {moveTarget ? t('file.copySourceHint', { path: moveTarget.path }) : null}
        </div>
      </Modal>
      <Modal
        open={!!renameTarget}
        title={t('file.rename')}
        okText={t('file.rename')}
        cancelText={t('common.cancel')}
        confirmLoading={renameBusy}
        onOk={doRename}
        onCancel={() => { setRenameTarget(null); setRenameName('') }}
      >
        <Input autoFocus value={renameName} onChange={(e) => setRenameName(e.target.value)} onPressEnter={onEnterSubmit(doRename)} placeholder={t('file.namePlaceholder')} />
        <div style={{ marginTop: 8, color: 'var(--text-dimmer)', fontSize: 12, wordBreak: 'break-all' }}>
          {renameTarget ? t('file.renamePathHint', { path: renameTarget.path }) : null}
        </div>
      </Modal>
      <Modal
        open={!!copyTarget}
        title={t('file.copyTo')}
        okText={t('common.copy')}
        cancelText={t('common.cancel')}
        confirmLoading={copyBusy}
        onOk={doCopy}
        onCancel={() => { setCopyTarget(null); setCopyDest('') }}
      >
        <Input autoFocus value={copyDest} onChange={(e) => setCopyDest(e.target.value)} onPressEnter={onEnterSubmit(doCopy)} placeholder={t('file.copyTargetPlaceholder')} />
        <div style={{ marginTop: 8, color: 'var(--text-dimmer)', fontSize: 12, wordBreak: 'break-all' }}>
          {copyTarget ? t('file.copySourceHint', { path: copyTarget.path }) : null}
        </div>
      </Modal>
      <Modal
        open={!!propertiesTarget}
        title={t('file.properties')}
        footer={<Button onClick={() => setPropertiesTarget(null)}>{t('common.close')}</Button>}
        onCancel={() => setPropertiesTarget(null)}
      >
        {propertiesLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 20 }}><Spin /></div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'max-content minmax(0,1fr)', gap: '8px 12px', fontSize: 13 }}>
            <span style={{ color: 'var(--text-dim)' }}>{t('file.property.name')}</span>
            <span style={{ color: 'var(--text-bright)', wordBreak: 'break-all' }}>{properties?.name || propertiesTarget?.name}</span>
            <span style={{ color: 'var(--text-dim)' }}>{t('file.property.type')}</span>
            <span>{properties?.dir ?? propertiesTarget?.dir ? t('file.directory') : t('common.file')}</span>
            <span style={{ color: 'var(--text-dim)' }}>{t('file.property.path')}</span>
            <span style={{ wordBreak: 'break-all' }}>{properties?.path || propertiesTarget?.path}</span>
            <span style={{ color: 'var(--text-dim)' }}>{t('file.property.size')}</span>
            <span>{properties?.dir ? t('file.property.folderEntries', { count: properties.entryCount ?? 0 }) : fmtSize(properties?.size ?? propertiesTarget?.size ?? 0)}</span>
            <span style={{ color: 'var(--text-dim)' }}>{t('file.property.modified')}</span>
            <span>{fmtTime(properties?.mtime || propertiesTarget?.mtime)}</span>
            <span style={{ color: 'var(--text-dim)' }}>{t('file.property.created')}</span>
            <span>{fmtTime(properties?.ctime || propertiesTarget?.ctime)}</span>
            <span style={{ color: 'var(--text-dim)' }}>{t('file.property.mode')}</span>
            <span style={{ fontFamily: 'ui-monospace, monospace' }}>{properties?.mode || t('file.unknown')}</span>
          </div>
        )}
      </Modal>
    </div>
  )

  const content = (() => {
  if (layout === 'split') {
    return (
      <div style={{ height: '100%', minHeight: 0, display: 'flex', background: 'var(--bg-base)' }}>
        <div style={{ flex: '0 0 clamp(220px, 22vw, 300px)', minWidth: 0, borderRight: '1px solid var(--border-subtle)' }}>
          {browserPane}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {view ? (
            <Viewer path={view} accent={accent} inline onClose={() => setView(null)} onOpenPath={openPath} onOpenAgent={onOpenAgent} />
          ) : (
            <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-dimmer)', fontSize: 13 }}>
              {t('file.selectPreview')}
            </div>
          )}
        </div>
      </div>
    )
  }

  // 停靠布局（右侧「文件管理」抽屉 / 新标签左侧栏）：**树和文件两栏并排，中间可拖**，
  // 而且不弹模态框——抽屉本来就是一块常驻侧栏，从里面再弹个居中浮层等于把它整个盖住，
  // 而你点开文件恰恰是想「一边看树、一边看文件、还一边看左边的对话」。
  //
  // 面板窄到放不下两栏时（< SPLIT_MIN）自动退回单栏：预览盖住树，左上角给返回。
  // 420 宽硬塞两栏的结果是两边都没法看——宁可少一栏，也不要两栏都残。
  //
  // **列表靠右缘，文件内容往左展开。**这块面板是从屏幕右边拉出来的：列表原本铺满整个
  // 面板、贴着右缘，一点开文件却被挤到左半边，等于你刚点的那一列自己跑了。现在列表钉在
  // 右缘不动，内容从它左边长出来——新出现的东西占新地方，已经在看的那列不动。
  if (layout === 'dock') {
    return (
      <InspectorLayers
        pinned={browserPane} pinnedSize={TREE} grownSize={PREVIEW}
        handle="filetree"
        grown={view ? (twoPane) => (
          <Viewer path={view} accent={accent} inline
            onBack={twoPane ? undefined : () => setView(null)} onClose={() => setView(null)}
            onOpenPath={openPath} onOpenAgent={onOpenAgent} />
        ) : null}
      />
    )
  }

  if (layout === 'sidebar') {
    return (
      <>
        {browserPane}
        {view && (
          <div
            className="tt-file-detail"
            style={{
              position: 'fixed',
              top: 0,
              bottom: 0,
              height: '100dvh',
              right: 'min(420px, 92vw)',
              zIndex: 1199,
              background: 'var(--bg-base)',
              borderLeft: '1px solid var(--border)',
              boxShadow: 'var(--elevated-shadow)',
            }}
          >
            <Viewer path={view} accent={accent} inline onClose={() => setView(null)} onOpenPath={openPath} />
          </div>
        )}
      </>
    )
  }

  return browserPane
  })()

  // 文件浏览器可能挂在高 z-index 的悬浮抽屉(FloatingFileDrawer, z=1200)里，而 antd 弹层
  // (右键菜单/下拉/Modal)默认基线低于抽屉 → 弹层被抽屉盖住，表现为「右键没反应」。
  // 统一抬高弹层基线，保证无论挂在抽屉、停靠栏还是独立文件页，行为都一致。
  return <ConfigProvider theme={{ token: { zIndexPopupBase: 1300 } }}>{content}</ConfigProvider>
}

function rowStyle(): React.CSSProperties {
  return { display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', cursor: 'pointer', fontSize: 13, userSelect: 'none' }
}
