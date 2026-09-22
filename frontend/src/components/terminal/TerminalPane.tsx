import { TBtn, TI } from './terminal-toolbar'
import { atPath, atPaths } from '../../agent-paths'
import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import ClaudeChat from '../chat/ClaudeChat'
import CodexChat from '../chat/CodexChat'
import FileBrowser from '../files/FileBrowser'
import { FileView } from '../files/fileview'
import { FileTypeIcon } from '../files/file-icons'
import { ChangesView, FilePathBar, type FileTabMode } from '../files/FilePathBar'
import type { FileTab } from './term-tabs-store'
import FileWorkspace from '../files/FileWorkspace'
import GitPanel from '../git/GitPanel'
import MobileSubPage from '../MobileSubPage'
import { PaneCloseConfirm, type PaneCloseTarget } from './PaneCloseConfirm'
import Term, { TermHandle, TermStatus } from './Terminal'
import { api, makeClipboardImageFile, upload, uploadedPathOf } from '../../api'
import { VoiceInput } from '../chat/VoiceInput'
import { copyText } from '../chat/blocks'
import RenameSessionModal from '../sessions/RenameSessionModal'
import { type ClaudeInfo } from './claude-info'
import { KEYS, PFX, tmuxMenu } from './tmux-keys'
import { useI18n } from '../../i18n'
import { SESSION_MIME, buildIntro, canDrop, readDrag } from '../shell/session-drop'
import { currentNodeId } from '../cluster/node-url'
import { OPEN_FILE_INTENT, requestIntent } from '../../intents'
import { useLayout } from '../../layout'
import { savePreferences, saveWorkspace, usePreferences } from '../../preferences'
import { PromptDialog, PromptSignal, advancePromptSignal, detectPrompt } from '../prompt'
import { SessionTitle, TabName, sessionDisplay } from '../sessions/session-label'
import { sessionProject } from '../sessions/session-project'
import AdaptivePanel from '../shell/AdaptivePanel'
import { DPad } from '../shell/DPad'
import { MobileSheet, SheetRow, SheetSection } from '../shell/MobileSheet'
import { SessionSwitchSheet } from '../shell/SessionDock'
import { Button, Dropdown, Input, Modal, Spin, Tooltip, App as AntApp } from 'antd'
import { AgentLogo, ChevronDown, ChevronLeft, ChevronRight, PlusIcon, StopIcon, TabsIcon, TerminalIcon, PanelRightIcon } from '../../icons'
// ── 终端面板（多标签 + 工具栏 + 快捷键栏），桌面右栏与手机覆盖层共用 ──
export default function TerminalPane(props: {
  terms: string[]; active: string | null; setActive: (n: string) => void; closeTerm: (n: string) => void
  fontSize: number; setFontSize: (n: number) => void
  statusMap: Record<string, TermStatus>; setStatus: (n: string, s: TermStatus) => void
  termRefs: React.MutableRefObject<Record<string, TermHandle | null>>
  sendKey: (seq: string) => void; onCollapse?: () => void
  claudeMap: Record<string, ClaudeInfo>; claudeView: Record<string, boolean>; setClaudeView: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
  codexMap: Record<string, ClaudeInfo>; codexView: Record<string, boolean>; setCodexView: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
  onRename: (oldName: string, newName: string) => void
  /** 标签拖拽排序；不传就不可拖（独立单终端页没有多标签） */
  onReorder?: (name: string, to: number) => void
  /** 把「哪些会话在等输入」递给外层（手机会话坞要用），避免第二份抓屏轮询 */
  onNeedsInput?: (map: Record<string, boolean>) => void
  /** 终端 Focus：传了才渲染工具条右侧那枚按钮（手机没有这个概念） */
  focus?: { on: boolean; toggle: () => void; hint: string }
  fileDock?: 'right' | 'left'   // 文件面板停靠：'right'=右侧浮动抽屉（默认），'left'=左侧 VSCode 栏（新标签全屏页）
  /** 标签条右端「新建 ▾」：在当前任务里开终端 / 去项目页开新任务。不传就不画 */
  /** 标签条「新建」：三样都在当前任务的 worktree 里派生；taskLabel 写在菜单顶上说明白 */
  onNew?: { terminal: () => void; claude: () => void; codex: () => void; taskLabel?: string }
  /** 右栏开关（任务视图）：亮着 = 开着 */
  inspector?: { open: boolean; toggle: () => void }
  /** 对话里点 Read/Edit 的路径 → 右栏文件面板打开（22 设计 §3.4）；不传就退回今天的路（文件页） */
  onOpenFile?: (path: string, line?: number) => void
  /** 对话里点「Git」→ 右栏切到 Git 面板 */
  onOpenGit?: () => void
  /** 当前任务的文件标签（22 设计 §3.3）：会话标签后面接着画；内容用 FileView，只有当前一个渲染 Monaco */
  fileTabs?: FileTab[]
  /** 当前标签是哪个文件；空 = 当前标签是会话 */
  activeFile?: string
  /** 当前任务的 worktree 根：路径条面包屑与「改动」都从它算 */
  taskDir?: string
  onFileTab?: (path: string) => void
  onCloseFile?: (path: string) => void
  onPinFile?: (path: string) => void
  onFileMode?: (path: string, mode: FileTabMode) => void
  /** 从对话里点「path:line」跳过来要定位到那一行；nonce 让同一处点第二次也响 */
  reveal?: { path: string; line: number; nonce: number }
}) {
  const { terms, active, setActive, closeTerm, fontSize, setFontSize, statusMap, setStatus, termRefs, sendKey, onCollapse, claudeMap, claudeView, setClaudeView, codexMap, codexView, setCodexView, onRename, onReorder, onNeedsInput, focus, onNew, inspector, onOpenFile, onOpenGit, fileTabs, activeFile, taskDir, onFileTab, onCloseFile, onPinFile, onFileMode, reveal } = props
  const tabs = terms
  const curFile = activeFile || ''
  // 文件标签的脏标记：FileView 报上来，关标签前问一句（FileWorkspace 同款）
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(() => new Set())
  const setFileDirty = (p: string, dirty: boolean) => setDirtyFiles((prev) => {
    if (prev.has(p) === dirty) return prev
    const n = new Set(prev); dirty ? n.add(p) : n.delete(p); return n
  })
  const fileDock = props.fileDock || 'right'
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const closeFile = (p: string) => {
    if (!onCloseFile) return
    if (dirtyFiles.has(p)) {
      modal.confirm({
        title: t('file.closeUnsavedTitle'), content: p.split('/').pop() || p,
        okText: t('file.closeWithoutSaving'), cancelText: t('common.cancel'),
        okButtonProps: { danger: true }, onOk: () => { setFileDirty(p, false); onCloseFile(p) },
      })
    } else onCloseFile(p)
  }
  const st = active ? statusMap[active] : undefined
  const [termNeedsInput, setTermNeedsInput] = useState<Record<string, boolean>>({})
  const promptSignals = useRef<Record<string, PromptSignal>>({})
  // 危险操作目标可视化 / 就地确认：关闭 pane 前先定位目标（几何+cwd+前台进程），
  // confirm 走结构化后端接口，不再盲发 Ctrl-b x 字节（那样只会撞上 tmux 底部原生 y/n 提示）。
  const [paneCloseTarget, setPaneCloseTarget] = useState<PaneCloseTarget | null>(null)
  const [paneCloseBusy, setPaneCloseBusy] = useState(false)
  const [paneCloseError, setPaneCloseError] = useState<string>()
  const openPaneCloseConfirm = async () => {
    if (!active) return
    try {
      const r = await api('GET', `/sessions/${encodeURIComponent(active)}/panes/active`)
      const p = r.data
      const rect = termRefs.current[active]?.paneScreenRect(p)
      if (!rect) { message.error(t('pane.close.locateFailed')); return }
      setPaneCloseError(undefined)
      setPaneCloseTarget({ session: active, paneId: p.paneId, cwd: p.cwd, cmd: p.cmd, panesInWindow: p.panesInWindow, rect })
    } catch {
      message.error(t('pane.close.locateFailed'))
    }
  }
  const confirmPaneClose = async () => {
    if (!paneCloseTarget) return
    setPaneCloseBusy(true)
    try {
      await api('POST', `/sessions/${encodeURIComponent(paneCloseTarget.session)}/panes/${encodeURIComponent(paneCloseTarget.paneId)}/close`, {})
      setPaneCloseTarget(null)
    } catch (e: any) {
      setPaneCloseError(e?.message || t('pane.close.failed'))
    } finally {
      setPaneCloseBusy(false)
    }
  }
  const activeNeedsInput = !!(active && termNeedsInput[active])
  const dot = activeNeedsInput ? 'var(--warn)' : st === 'connected' ? 'var(--ok)' : st === 'connecting' ? 'var(--warn)' : 'var(--danger)'
  // 灵动岛的「活着」判据：有 Agent 在跑。会话只是连着（st==='connected'）不算——
  // 那是个静态事实，让点一直呼吸等于把呼吸这个信号用废了。
  const activeAgentLive = !!(active && (claudeMap[active]?.running || codexMap[active]?.running))
  // 当前标签是否在 Claude/Codex 对话视图：此时聊天 UI 自带输入框，
  // 终端那条移动输入条 + 快捷键栏要隐藏，否则手机上会出现两个输入框。
  const inChat = !!active && ((claudeView[active] && claudeMap[active]?.running) || (codexView[active] && codexMap[active]?.running))

  // 移动端可靠输入：xterm 隐藏 textarea 在软键盘/输入法「合成/预测词」下会把字留在
  // 合成缓冲里不提交，onData 不触发 → 打完字发不出去。触摸设备改用独立输入框：整行送 PTY。
  const { coarse: isTouch } = useLayout()
  const [line, setLine] = useState('')
  const mobileInputRef = useRef<import('antd').InputRef>(null)
  const sendRaw = (s: string) => { if (active) termRefs.current[active]?.send(s, true) } // keepFocus：不抢 xterm 焦点 → 软键盘不收起
  // 滚上去看历史会让 tmux 进 copy-mode，此时输入被它截走（要先按「底」才生效）。
  // 输入框聚焦/发送前先回到底部退出 copy-mode，省去手动按「底」。
  const exitCopyMode = () => { if (active) termRefs.current[active]?.toBottom() }
  const flushLine = () => { if (line) { exitCopyMode(); sendRaw(line); setLine('') } }   // 把输入框待发文本先送出（不带回车）
  const submitLine = () => { exitCopyMode(); sendRaw(line + '\r'); setLine('') }          // 整行 + 回车
  const tapKey = (seq: string) => { flushLine(); if (isTouch) sendRaw(seq); else sendKey(seq) } // 控制键：先 flush 待发文本

  /**
   * 中断当前会话（^C）。
   *
   * 走 HTTP 注入而不是终端 ws：真要按停的时候人常常不在终端画布上（在对话视图、
   * 或刚从别处切回来 ws 还在重连），ws 那条路那一下就静悄悄地丢了。
   * 只发一次——Claude Code 里短时间连按两次 Ctrl+C 是退出整个 TUI，不是中断。
   */
  const interruptActive = async () => {
    if (!active) return
    try {
      await api('POST', `/sessions/${encodeURIComponent(active)}/keys`, { keys: ['C-c'] })
      message.success(t('terminal.interruptSent'))
    } catch (e: any) { message.error(e.message) }
  }
  const noBlur = isTouch ? (e: React.MouseEvent) => e.preventDefault() : undefined        // 点按钮不夺走输入框焦点（软键盘保持）

  // 弹框提醒全局开关
  const [prefsData] = usePreferences()
  const promptOff = !!prefsData.promptPopupOff
  const togglePromptOff = () => savePreferences({ promptPopupOff: !promptOff })

  // 语音开关不再在桌面工具条上（22 设计 §3.3 语音归 composer）；手机「⋯」sheet 里那一行与设置页仍能关掉
  const showVoice = prefsData.showVoiceButton !== false
  const setShowVoice = (v: boolean | ((prev: boolean) => boolean)) => {
    const next = typeof v === 'function' ? v(showVoice) : v
    savePreferences({ showVoiceButton: next })
  }

  // 文件侧栏（终端视图下也可用）：定位到当前会话的工作目录。左侧停靠时默认展开。
  // 编辑器多 tab / 打开的文件 / 拖拽调宽等都下沉到 <FileWorkspace>（左侧停靠时用），这里只保留 showFiles。
  const [showFiles, setShowFiles] = useState(fileDock === 'left')
  const [showGit, setShowGit] = useState(false)
  const [cwd, setCwd] = useState('')
  // 右侧停靠：文件 / Git 不再是这里的抽屉，归右栏三面板（InspectorPanels，22 设计 §3.4），
  // 这里只把「要看哪个」递上去。左侧停靠（#/term 独立页）的 FileWorkspace 照旧。
  const toggleFiles = () => setShowFiles((s) => !s)
  const toggleGit = () => setShowGit((s) => !s)
  // 稳定引用：这两个回调经 ChatShell 的 context 送到每一条工具行，引用一变整卷对话的 memo 全失效
  const openGitRef = useRef(() => {})
  openGitRef.current = () => { if (onOpenGit) onOpenGit(); else setShowGit(true) }
  const openGitFromChat = useCallback(() => openGitRef.current(), [])
  // 对话页里点工具行的文件路径 → 在文件面板打开（带行号就跳到那一行）。
  // 左侧停靠时 <FileWorkspace> 已挂载在同一页，直接发意图即可开成对话旁边的标签页；
  // 否则先切到文件页再发，跟 ⌘K 搜索结果打开文件是同一条路（见 intents.ts）。
  // 从对话里点 Read/Edit 的文件名。两种停靠各走各的路，**都不离开会话页**：
  //   左停靠：FileWorkspace 分栏 → 开到右栏（side），对话留在左栏
  //   右停靠：右侧「文件管理」抽屉 → 打开抽屉并在里面预览这个文件
  // 之前右停靠走的是 `location.hash = '#/files'`，直接把人跳去文件页——
  // 那正是「点了跑到左边栏去」的由来。
  // 手机同样走右停靠这条：AdaptivePanel 在手机档换成 MobileSubPage（覆盖在会话之上的
  // 全屏二级页，带 ← 和物理返回键），返回就回到原会话原滚动位置——**不是**跳走。
  // 早先这里按 isPhone 把 onOpenFile 置空，结果手机上工具行里的路径根本点不动。
  const [dockFileReq, setDockFileReq] = useState<{ path: string; nonce: number } | null>(null)
  // 请求是一次性的：抽屉一关 <FileBrowser> 就整个卸载，下次点「文件」是全新挂载，
  // 留着的旧请求会被当成新请求重放一遍——于是点「文件」总把上次点开的那个文件又开出来，
  // 换了会话也照开（那是上个会话工作目录里的文件）。开完就丢，关抽屉/换会话时清干净。
  useEffect(() => { if (!showFiles) setDockFileReq(null) }, [showFiles])
  useEffect(() => { setDockFileReq(null) }, [active])
  const openFileRef = useRef<(path: string, line?: number) => void>(() => {})
  openFileRef.current = (path, line) => {
    if (fileDock === 'left') {
      requestIntent(OPEN_FILE_INTENT, { path, line, side: true })
      return
    }
    if (onOpenFile) { onOpenFile(path, line); return }
    setShowFiles(true)
    setDockFileReq((prev) => ({ path, nonce: (prev?.nonce || 0) + 1 }))
  }
  const openFileFromChat = useCallback((path: string, line?: number) => openFileRef.current(path, line), [])


  // 标签溢出时两侧给渐隐，提示"这边还有"（14 §7.1）。滚动条本身是隐藏的，
  // 没有这个提示，窄栏下多出来的标签等于不存在。
  const tabScrollRef = useRef<HTMLDivElement | null>(null)
  const [fadeL, setFadeL] = useState(false)
  const [fadeR, setFadeR] = useState(false)
  const syncFade = useCallback(() => {
    const el = tabScrollRef.current
    if (!el) return
    setFadeL(el.scrollLeft > 2)
    setFadeR(el.scrollLeft + el.clientWidth < el.scrollWidth - 2)
  }, [])
  useEffect(() => {
    syncFade()
    const el = tabScrollRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(syncFade)
    ro.observe(el)
    return () => ro.disconnect()
  }, [syncFade, terms.length])
  // 两端的翻页钮：一下翻八成可视宽（留两成重叠，翻完还认得出刚才看到哪儿了）。
  // 渐隐只是「这边还有」的暗示，鼠标用户没有横向滚轮时照样够不着——这两枚是能点的那一版。
  const scrollTabs = (dir: 1 | -1) => {
    const el = tabScrollRef.current
    if (!el) return
    el.scrollBy({ left: dir * Math.max(160, Math.round(el.clientWidth * 0.8)), behavior: 'smooth' })
  }

  // 标签条是单行横向滑动（见 index.css .tt-tabs）：窄栏/手机上会话一多，当前标签会滑出视口，
  // 切换后把它带回来——而且是带回**正中间**：贴在条边上的话，左右还有什么邻居全看不见，
  // 居中之后两边各露一截，接着往哪边翻一目了然。
  //
  // 只动标签条自己的 scrollLeft，不用 Element.scrollIntoView：它会连着滚外层祖先
  //（overflow:hidden 的祖先照滚，只是没有滚动条能看出来），于是页头被顶出可视区——
  // 文件页那个被裁掉半截的「文件管理」标题就是这么来的。FileWorkspace 早先踩过同一个坑，
  // 那边的注释还在。
  const activeTabRef = useRef<HTMLSpanElement | null>(null)
  // 文件标签激活时 active（会话）不变，也得滚：否则点开的文件标签在条外，人不知道开在哪了
  useEffect(() => {
    const strip = tabScrollRef.current
    const el = activeTabRef.current
    if (!strip || !el) return
    const sr = strip.getBoundingClientRect(), er = el.getBoundingClientRect()
    const delta = (er.left + er.width / 2) - (sr.left + sr.width / 2) // 标签中心 → 条中心
    const next = Math.max(0, Math.min(strip.scrollWidth - strip.clientWidth, strip.scrollLeft + delta))
    if (Math.abs(next - strip.scrollLeft) > 1) strip.scrollTo({ left: next, behavior: 'smooth' })
  }, [active, activeFile])

  // 标签拖拽排序（14 §7.1）：dragTab / dropAt 只用来画反馈（半透明 + 插入线），
  // 落点判定全部走事件本身，见下面两个 helper。
  const { phone: isPhone } = useLayout()
  const ws = prefsData.workspace
  const [typing, setTyping] = useState(false)
  // 快捷键条的两侧渐隐：和标签条同一套做法（溢出时才提示"这边还有"）
  const keyRowRef = useRef<HTMLDivElement>(null)
  const [keyFadeL, setKeyFadeL] = useState(false)
  const [keyFadeR, setKeyFadeR] = useState(false)
  const syncKeyFade = useCallback(() => {
    const el = keyRowRef.current
    if (!el) return
    setKeyFadeL(el.scrollLeft > 2)
    setKeyFadeR(el.scrollLeft + el.clientWidth < el.scrollWidth - 2)
  }, [])
  const [switchOpen, setSwitchOpen] = useState(false)
  const [moreSheet, setMoreSheet] = useState(false)
  const [dragTab, setDragTab] = useState<string | null>(null)
  const [dropAt, setDropAt] = useState<number | null>(null)
  // 自定义 MIME：文件区/终端的拖放判定按 type 分流，共用 text/plain 会被它们当路径接走
  const isTabDrag = (e: React.DragEvent) => e.dataTransfer.types.includes('application/x-tt-tab')
  // 会话拖到标签上（21 设计）：不建链路、不留台账，只往**这个**会话里注一段话，
  // 告诉它旁边那个是谁、怎么用 ttmux send 跟它说话。剩下的交给大模型自己安排。
  const isSessionDrag = (e: React.DragEvent) => e.dataTransfer.types.includes(SESSION_MIME)
  const [dropPeer, setDropPeer] = useState('')
  const introduce = async (e: React.DragEvent, target: string) => {
    const src = readDrag(e.dataTransfer)
    const v = canDrop(src, {
      id: target, node: currentNodeId() || '',
      hasAgent: !!(claudeMap[target]?.running || codexMap[target]?.running),
    })
    if (!src) return
    if (!v.ok) {
      // 跨机说清楚原因：ttmux send 走本机 tmux，静默失败会让 Agent 拿到
      // 一句「会话不存在」然后开始瞎猜
      if (v.why === 'cross') message.warning(t('pair.crossNode', { name: src.label || src.id }))
      // 落进普通 shell 会把介绍词的每一行当命令跑掉（真机撞出来的）
      if (v.why === 'noagent') message.warning(t('pair.noAgent', { name: sessionDisplay(target) }))
      return
    }
    try {
      await api('POST', '/tasks/_/send', { sess: target, msg: buildIntro(src, target, t) })
      message.success(t('pair.sent', { name: sessionDisplay(target), peer: src.label || src.id }))
    } catch (err: any) { message.error(err.message) }
  }
  /** 落在标签右半边 = 插到它后面 */
  const dropIndexAt = (e: React.DragEvent, i: number) => {
    const b = e.currentTarget.getBoundingClientRect()
    return e.clientX > b.left + b.width / 2 ? i + 1 : i
  }

  // 从文件/Git 面板把文件拖到终端 → 插入为 @绝对路径。
  const [dragOver, setDragOver] = useState(false)
  useEffect(() => {
    const clear = () => setDragOver(false)
    document.addEventListener('dragend', clear)
    document.addEventListener('drop', clear, true)
    return () => { document.removeEventListener('dragend', clear); document.removeEventListener('drop', clear, true) }
  }, [])
  // 拖拽载荷就是文件绝对路径，原样作为 @mention（不转相对路径）。
  const toMention = (raw: string) => {
    const p = raw.trim()
    return atPath(p)
  }
  const readDropPath = (e: React.DragEvent) =>
    e.dataTransfer.getData('application/x-ttmux-path') || e.dataTransfer.getData('text/plain') || ''
  const isPathDrag = (e: React.DragEvent) => e.dataTransfer.types.includes('application/x-ttmux-path')
  // 系统文件拖入（非内部路径拖拽）：types 含 'Files'。不接住的话浏览器会把文件当新标签打开。
  const isFileDrag = (e: React.DragEvent) => e.dataTransfer.types.includes('Files')
  const allowPathDrop = (e: React.DragEvent) => {
    if (!isPathDrag(e)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }
  // 落点是否在终端区右半 → 让给 FileWorkspace 做分栏（VSCode 式：右半区拆栏，左/中区注入@）。
  const inTermSplitZone = (e: React.DragEvent) => {
    const r = e.currentTarget.getBoundingClientRect()
    return e.clientX > r.left + r.width / 2
  }
  // 从系统拖入真实文件：上传后把绝对路径以 @ 注入当前会话（等同 Ctrl+V 粘图）。
  // 图片走 /tmp（不污染工作目录），其余文件走会话工作目录。
  const onTermFileDrop = async (e: React.DragEvent) => {
    const files = Array.from(e.dataTransfer.files || [])
    if (!files.length || !active) return
    const imgs = files.filter((f) => f.type.startsWith('image/'))
    const rest = files.filter((f) => !f.type.startsWith('image/'))
    const saved: string[] = []
    try {
      if (imgs.length) saved.push(...(await upload('/tmp', imgs)).saved)
      if (rest.length) {
        if (!cwd) { message.error(t('chat.cwdMissing')) }
        else saved.push(...(await upload(cwd, rest)).saved)
      }
    } catch (err: any) { message.error(t('terminal.imageUploadFailed', { message: err.message })); return }
    if (!saved.length) return
    exitCopyMode()
    termRefs.current[active]?.send(atPaths(saved), true)
  }
  // 拖到终端区：直接把 @路径 送进当前会话（claude/codex TUI 或 shell 提示符的光标处）。
  const onTermDrop = (e: React.DragEvent) => {
    if (isSessionDrag(e)) { // 拖到画面上 = 说给当前会话听
      e.preventDefault(); e.stopPropagation(); setDragOver(false)
      if (active) void introduce(e, active)
      return
    }
    if (isFileDrag(e) && e.dataTransfer.files?.length) { // 系统文件：上传并注入（无视左右半区，不做分栏）
      e.preventDefault(); e.stopPropagation(); setDragOver(false)
      onTermFileDrop(e)
      return
    }
    if (!isPathDrag(e)) return
    if (inTermSplitZone(e)) { setDragOver(false); return } // 右半区：不拦截，冒泡给 FileWorkspace 分栏
    e.preventDefault()
    e.stopPropagation() // 左/中区：拖到终端=注入@，不冒泡到分栏
    setDragOver(false)
    const mention = toMention(readDropPath(e))
    if (!mention || !active) return
    // 分窗(tmux split pane)时：先按落点坐标激活对应 pane，@路径才会注入到拖放的那个窗格。
    termRefs.current[active]?.selectPaneAt(e.clientX, e.clientY)
    exitCopyMode()
    termRefs.current[active]?.send(mention + ' ', true)
  }
  // 拖到移动端输入框：追加到待编辑文本，用户可改后再发。
  const onInputDrop = (e: React.DragEvent) => {
    if (!isPathDrag(e)) return
    e.preventDefault()
    const mention = toMention(readDropPath(e))
    if (mention) setLine((l) => (l ? l.replace(/\s*$/, ' ') : '') + mention + ' ')
  }
  const [ctx, setCtx] = useState<{ x: number; y: number; session: string; selection: string } | null>(null)
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteSession, setPasteSession] = useState('')
  const [pasteText, setPasteText] = useState('')
  const [renameSession, setRenameSession] = useState<string | null>(null)
  useEffect(() => {
    if (!active) { setCwd(''); return }
    // 优先用 claude/codex 已知工作目录，否则查会话 pane 当前路径
    const known = claudeMap[active]?.dir || codexMap[active]?.dir
    if (known) { setCwd(known); return }
    let stop = false
    api('GET', `/sessions/${encodeURIComponent(active)}/cwd`).then((r) => { if (!stop) setCwd(r.data?.dir || '') }).catch(() => {})
    return () => { stop = true }
  }, [active, claudeMap, codexMap])

  useEffect(() => {
    if (!terms.length) {
      promptSignals.current = {}
      setTermNeedsInput((previous) => Object.keys(previous).length ? {} : previous)
      return
    }
    let stop = false
    const checkPrompts = async () => {
      const entries = await Promise.all(terms.map(async (name) => {
        try {
          const r = await api('GET', `/sessions/${encodeURIComponent(name)}/capture?lines=50`)
          return [name, !!detectPrompt(r.data || '')] as const
        } catch {
          return [name, false] as const
        }
      }))
      if (stop) return
      const nextSignals: Record<string, PromptSignal> = {}
      const nextState: Record<string, boolean> = {}
      entries.forEach(([name, candidate]) => {
        const signal = advancePromptSignal(promptSignals.current[name], candidate)
        nextSignals[name] = signal
        nextState[name] = signal.stable
      })
      promptSignals.current = nextSignals
      // 未发生语义变化时复用旧对象，避免后台抓屏每 4 秒让整个终端区无意义重渲染。
      setTermNeedsInput((previous) => {
        const keys = Object.keys(nextState)
        const unchanged = keys.length === Object.keys(previous).length && keys.every((name) => previous[name] === nextState[name])
        return unchanged ? previous : nextState
      })
    }
    checkPrompts()
    const t = setInterval(checkPrompts, 4000)
    return () => { stop = true; clearInterval(t) }
  }, [terms])

  useEffect(() => { onNeedsInput?.(termNeedsInput) }, [termNeedsInput, onNeedsInput])

  useEffect(() => {
    syncKeyFade()
    const el = keyRowRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(syncKeyFade)
    ro.observe(el)
    return () => ro.disconnect()
  }, [syncKeyFade, typing, inChat])

  // 软键盘开合会改可视高度，但 xterm 不会自己重算行数——不重新 fit 就会出现
  // 「PTY 以为还有 25 行、实际只画得下 7 行」的错位，表现为花屏。等一帧让布局落定再量。
  const kb = useLayout().keyboard
  useEffect(() => {
    if (!active) return
    const id = requestAnimationFrame(() => termRefs.current[active]?.fit())
    return () => cancelAnimationFrame(id)
  }, [kb, active, typing])

  const sendPaste = (session: string, text: string) => {
    if (!text) return
    termRefs.current[session]?.send(text.replace(/\r\n/g, '\n'), true)
  }
  const openManualPaste = (session: string) => {
    setPasteSession(session)
    setPasteText('')
    setPasteOpen(true)
  }
  /**
   * 粘贴图片：**先把 @路径 敲进去，再后台上传**。
   *
   * 反过来（await upload 之后再敲）会吞掉用户的输入：上传要几百毫秒到几秒，
   * 而用户按完 Ctrl+V 就以为贴好了、立刻接着打字——那些字符实时进了 pty，
   * 等上传回来，@路径 插在**光标当前位置**，正好戳进已经打了一半的句子中间。
   * 用户看到的就是「后半段文字被淹没」。
   *
   * 路径能提前算出来，靠的是文件名里那截随机串（见 makeClipboardImageFile）：
   * 后端 uniquePath 只在重名时才改名，不重名就原样落盘。
   * 万一真撞了名，下面会拿实际路径和预敲的比一次，不一致就明说。
   */
  const pasteImage = async (session: string, rawFiles: File[]) => {
    const files = rawFiles.map((f, i) => makeClipboardImageFile(f, f.type, i))
    const expected = files.map((f) => uploadedPathOf('/tmp', f))
    // 末尾补一个空格：紧接着打字时不会和路径粘成一坨。
    sendPaste(session, atPaths(expected))
    message.loading({ content: t('terminal.imageUploading'), key: 'img-paste', duration: 0 })
    try {
      const res = await upload('/tmp', files)
      const saved: string[] = res.saved || []
      const drifted = saved.filter((p, i) => p !== expected[i])
      if (drifted.length) {
        // 极罕见（撞名了）。不去改终端里已经敲下的字——那要靠退格删，
        // 而用户这会儿多半已经在上面接着打了。老实报出真实路径，让用户自己改。
        message.warning({
          content: t('terminal.imagePathDrifted', { paths: drifted.join(' ') }),
          key: 'img-paste', duration: 8,
        })
        return
      }
      message.success({ content: t('terminal.imagePasted', { count: files.length }), key: 'img-paste' })
    } catch (e: any) {
      // 路径已经敲进去了但文件没上去，必须说清楚，否则用户会对着一个不存在的
      // 路径按回车，然后困惑于 agent 说找不到文件。
      message.error({ content: t('terminal.imageUploadFailed', { message: e.message }), key: 'img-paste', duration: 8 })
    }
  }
  const pasteClipboard = async (session: string) => {
    try {
      if (navigator.clipboard?.read) {
        try {
          const items = await navigator.clipboard.read()
          const imageFiles: File[] = []
          let text = ''
          for (const item of items) {
            for (const type of item.types) {
              if (type.startsWith('image/')) {
                // 同一张图多种 MIME 只取一张，避免重复上传出现两次 @路径
                if (!imageFiles.length) { const blob = await item.getType(type); imageFiles.push(new File([blob], 'image', { type })) }
              } else if (type === 'text/plain') {
                text = await (await item.getType(type)).text()
              }
            }
          }
          if (imageFiles.length > 0) { pasteImage(session, imageFiles); return }
          if (text) { sendPaste(session, text); return }
        } catch { /* clipboard.read() failed — fall through to readText */ }
      }
      const text = await navigator.clipboard.readText()
      if (text) sendPaste(session, text)
      else openManualPaste(session)
    } catch {
      openManualPaste(session)
    }
  }
  const selText = ctx?.selection?.trim() || ''
  const selPreview = selText.replace(/\s+/g, ' ').slice(0, 28)
  const ctxItems = ctx ? [
    ...(selText ? [
      {
        key: 'copy',
        label: (
          <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontWeight: 600 }}>{t('terminal.copySelected')}</span>
            <span style={{ color: 'var(--text-dimmer)', fontSize: 12, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              “{selPreview}{selText.length > selPreview.length ? '…' : ''}”
            </span>
          </span>
        ),
      },
      { type: 'divider' as const },
    ] : []),
    { key: 'paste', label: t('terminal.pasteClipboard') },
    { key: 'manual-paste', label: t('terminal.manualPaste') },
    { type: 'divider' as const },
    { key: 'scroll-up', label: t('terminal.scrollHistory') },
    { key: 'bottom', label: t('terminal.toBottom') },
    { key: 'redraw', label: t('terminal.redraw') },
    { key: 'reconnect', label: t('terminal.reconnect') },
    { type: 'divider' as const },
    {
      key: 'tmux',
      label: 'tmux',
      children: [
        { key: PFX + '[', label: t('terminal.tmuxCopyMode') },
        { key: PFX + 'w', label: t('terminal.tmuxWindowList') },
        { key: PFX + '%', label: t('terminal.tmuxSplitVertical') },
        { key: PFX + '"', label: t('terminal.tmuxSplitHorizontal') },
      ],
    },
    { type: 'divider' as const },
    { key: 'cancel', label: t('common.cancel') },
  ] : []
  const onCtxClick = ({ key }: { key: string }) => {
    if (!ctx) return
    const h = termRefs.current[ctx.session]
    if (key === 'cancel') { /* 仅关闭菜单 */ }
    else if (key === 'copy') { copyText(ctx.selection); message.success(t('common.copied')); h?.clearSelection() }
    else if (key === 'paste') pasteClipboard(ctx.session)
    else if (key === 'manual-paste') openManualPaste(ctx.session)
    else if (key === 'scroll-up') h?.scroll(-12)
    else if (key === 'bottom') h?.toBottom()
    else if (key === 'redraw') h?.redraw()
    else if (key === 'reconnect') h?.reconnect()
    else h?.send(key)
    setCtx(null)
  }
  if (terms.length === 0) {
    return (
      <div style={{ flex: 1, display: 'grid', placeItems: 'center', color: 'var(--text-dim)' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ display: 'flex', justifyContent: 'center', color: 'var(--text-dimmer)' }}><TerminalIcon size={40} /></div>
          <div>{t('terminal.openHint', { terminal: t('common.terminal') })}</div>
        </div>
      </div>
    )
  }

  // ── 会话（终端）各部件抽成局部 JSX：左侧停靠走 <FileWorkspace> 的槽位，右侧抽屉走原地布局，二者共用同一份 ──
  // 标签条是单行横向滑动：窄栏/手机上开的会话一多，当前标签就滑出视口了 → 切换后把它带回来。
  // 会话状态点：等待确认=琥珀，已连接=绿，连接中=琥珀，断开=红（与列表页同一套色）
  const dotOf = (name: string) => termNeedsInput[name] ? 'var(--warn)'
    : statusMap[name] === 'connected' ? 'var(--ok)' : statusMap[name] === 'connecting' ? 'var(--warn)' : 'var(--danger)'
  const statusDot = (color: string, size = 7) => (
    <i style={{ width: size, height: size, borderRadius: '50%', flex: `0 0 ${size}px`, background: color, boxShadow: `0 0 0 3px ${color}26` }} />
  )
  // 标签内的会话标记：官方品牌标，跟状态点同一行且同一光学尺寸（颜色由标自己带，见 AgentLogo）
  const agentMarks = (name: string) => (
    <>
      {claudeMap[name]?.running && <span title={t('session.runningClaude')} style={{ display: 'inline-flex' }}><AgentLogo kind="claude" /></span>}
      {codexMap[name]?.running && <span title={t('session.runningCodex')} style={{ display: 'inline-flex' }}><AgentLogo kind="codex" /></span>}
    </>
  )
  const sessionTab = (
    <>
      {statusDot(active ? dotOf(active) : '#f85149')}
      {active && agentMarks(active)}
      {active && <SessionTitle name={active} />}
    </>
  )
  // 标签条：左侧「收起」固定不滚，标签区独立横滚（14 §7.1）。
  // 收起按钮原来跟着标签一起滚，会话一多它就滑出视口——那是常驻动作，不该跟着内容跑。
  const tabStrip = (
    <div className="tt-tabs-wrap">
      {onCollapse && (
        <div className="tt-tabs-lead">
          <TBtn icon={TI.collapse} label={t('common.collapse')} onClick={onCollapse} />
          <span className="tt-sep" />
        </div>
      )}
      {fadeL && (
        <button type="button" className="tt-tabs-nav" aria-label={t('tabs.scrollLeft')} title={t('tabs.scrollLeft')}
          onClick={() => scrollTabs(-1)}><ChevronLeft size={15} /></button>
      )}
      <div className="tt-tabs" ref={tabScrollRef} data-l={fadeL ? '1' : undefined} data-r={fadeR ? '1' : undefined}
        onScroll={syncFade}
        // 竖滚轮横移：标签条只有一行，鼠标滚轮在它上面本来什么也不做
        onWheel={(e) => {
          const el = tabScrollRef.current
          if (!el || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return
          el.scrollLeft += e.deltaY
        }}>
        {tabs.map((termName, i) => {
          const on = termName === active
          const waiting = termNeedsInput[termName]
          const proj = sessionProject(termName)
          // 分支进 Tooltip，不占标签宽度（14 §6.3.2）
          const tip = [proj && proj.name, sessionDisplay(termName), proj?.branch]
            .filter(Boolean).join(' · ')
          const tab = (
            <span key={termName} ref={on ? activeTabRef : undefined}
              className={`tt-tab${on ? ' on' : ''}${dragTab === termName ? ' dragging' : ''}${dropAt === i ? ' dropL' : ''}${dropPeer === termName ? ' dropPeer' : ''}`}
              title={tip} onClick={() => setActive(termName)}
              draggable={!!onReorder}
              onDragStart={(e) => {
                // 自定义 MIME：文件区/终端的拖放判定按 type 分流，用通用 text/plain
                // 会被它们当成路径拖拽接走（见 isPathDrag）
                e.dataTransfer.setData('application/x-tt-tab', String(i))
                e.dataTransfer.effectAllowed = 'move'
                setDragTab(termName)
              }}
              onDragOver={(e) => {
                if (isSessionDrag(e)) {
                  // dragover 里读不到 dataTransfer 的内容（浏览器只在 drop 时给），
                  // 所以这里只按「目标有没有 Agent」决定亮不亮；剩下的判定落在 drop
                  const ok = !!(claudeMap[termName]?.running || codexMap[termName]?.running)
                  e.preventDefault(); e.stopPropagation()
                  // **一律 copy**：dropEffect='none' 会让浏览器干脆不投递 drop 事件，
                  // 于是「不接」变成静默失败，人连原因都看不到。接住再解释。
                  e.dataTransfer.dropEffect = 'copy'
                  setDropPeer(ok ? termName : '') // 高亮只给接得住的
                  return
                }
                if (!isTabDrag(e)) return
                e.preventDefault(); e.stopPropagation()
                e.dataTransfer.dropEffect = 'move'
                setDropAt(dropIndexAt(e, i))
              }}
              onDragLeave={() => setDropPeer((cur) => (cur === termName ? '' : cur))}
              onDrop={(e) => {
                if (isSessionDrag(e)) {
                  e.preventDefault(); e.stopPropagation()
                  setDropPeer('')
                  void introduce(e, termName)
                  return
                }
                if (!isTabDrag(e)) return
                e.preventDefault(); e.stopPropagation()
                // 源标签从 dataTransfer 读，不从 dragTab 状态读：状态只用来画拖拽反馈，
                // 落点判定必须只依赖事件本身，否则 setState 还没刷新时这一拖就静默丢了
                const from = Number(e.dataTransfer.getData('application/x-tt-tab'))
                const name = tabs[from]
                if (name) onReorder?.(name, dropIndexAt(e, i))
                setDragTab(null); setDropAt(null)
              }}
              onDragEnd={() => { setDragTab(null); setDropAt(null); setDropPeer('') }}>
              {statusDot(dotOf(termName))}
              {waiting && <span className="tt-wait" title={t('prompt.confirmRequired')}>{t('session.waiting')}</span>}
              {agentMarks(termName)}
              <TabName name={termName} />
              <a className="tt-x" title={t('common.close')} onClick={(e) => { e.stopPropagation(); closeTerm(termName) }}>{TI.close}</a>
            </span>
          )
          // 右键菜单：标签是跨页常驻的，「这个会话是哪来的」得有个地方能问（14 §6.3.4）
          return (
            <Dropdown key={termName} trigger={['contextMenu']} menu={{ items: [
              ...(proj ? [{ key: 'proj', label: t('terminal.openOwnerProject', { name: proj.name }),
                onClick: () => { location.hash = '#/projects/' + encodeURIComponent(proj.key) } }] : []),
              { key: 'newtab', label: t('terminal.openInNewTabTitle'),
                onClick: () => window.open(`/#/term/${encodeURIComponent(termName)}`, '_blank') },
              { type: 'divider' as const },
              { key: 'close', danger: true, label: t('common.close'), onClick: () => closeTerm(termName) },
            ] }}>{tab}</Dropdown>
          )
        })}
        {/* 文件标签（22 设计 §3.3）：接在会话标签后面，同一款 .tt-tab；预览态斜体，单击别的文件会替换它，
            双击转正；脏了标签上带点。文件标签第一期不参与拖拽排序。 */}
        {(fileTabs || []).map((f) => {
          const on = curFile === f.path
          const name = f.path.split('/').pop() || f.path
          const dirty = dirtyFiles.has(f.path)
          return (
            <span key={'file:' + f.path} ref={on ? activeTabRef : undefined}
              className={`tt-tab tt-tab-file${on ? ' on' : ''}${f.preview ? ' prev' : ''}${dirty ? ' dirty' : ''}`}
              title={f.path} onClick={() => onFileTab?.(f.path)} onDoubleClick={() => onPinFile?.(f.path)}>
              <span className="tt-tab-fi"><FileTypeIcon name={name} /></span>
              <span className="tt-tab-nm">{name}</span>
              <a className="tt-x" title={dirty ? t('file.unsaved') : t('common.close')} onClick={(e) => { e.stopPropagation(); closeFile(f.path) }}>{dirty ? <span className="tt-tab-dirty" /> : TI.close}</a>
            </span>
          )
        })}
        {/* 拖到最右侧：最后一个标签的右半边已经给出 i+1，这里只补"空白区也能落" */}
        {dragTab && (
          <span className="tt-tab-tail"
            onDragOver={(e) => { if (!isTabDrag(e)) return; e.preventDefault(); setDropAt(tabs.length) }}
            onDrop={(e) => {
              if (!isTabDrag(e)) return
              e.preventDefault()
              const name = tabs[Number(e.dataTransfer.getData('application/x-tt-tab'))]
              if (name) onReorder?.(name, tabs.length)
              setDragTab(null); setDropAt(null)
            }} />
        )}
      </div>
      {fadeR && (
        <button type="button" className="tt-tabs-nav" aria-label={t('tabs.scrollRight')} title={t('tabs.scrollRight')}
          onClick={() => scrollTabs(1)}><ChevronRight size={15} /></button>
      )}
      {/* 开得多到一条装不下时，给一份清单：翻页钮是「往那边看看」，清单是「直接去那一个」。
          一屏 8–10 行，比横着翻快一个数量级——标签条本身再怎么滑，也只能同时露出两三枚。 */}
      {(fadeL || fadeR) && (
        <Dropdown trigger={['click']} placement="bottomRight" menu={{
          selectedKeys: [curFile ? 'file:' + curFile : 'term:' + active],
          items: [
            ...(tabs.length ? [{ type: 'group' as const, key: 'g-term', label: t('tabs.allSessions'),
              children: tabs.map((n) => ({
                key: 'term:' + n,
                icon: claudeMap[n]?.running ? <AgentLogo kind="claude" size={13} /> : codexMap[n]?.running ? <AgentLogo kind="codex" size={13} /> : <TerminalIcon size={13} />,
                // 行尾一枚 ×：在清单里就能收起标签，不用先切过去再找标签上的 ×。stopPropagation 让菜单项的 onClick 不跟着跑
                label: <span className="tt-tabmenu-row"><span className="nm">{sessionDisplay(n) || n}</span>
                  <button type="button" className="tt-x" aria-label={t('common.close')} title={t('common.close')} onClick={(e) => { e.stopPropagation(); closeTerm(n) }}>{TI.close}</button></span>,
                onClick: () => setActive(n),
              })) }] : []),
            ...((fileTabs || []).length ? [{ type: 'group' as const, key: 'g-file', label: t('tabs.allFiles'),
              children: (fileTabs || []).map((f) => ({
                key: 'file:' + f.path,
                icon: <FileTypeIcon name={f.path.split('/').pop() || f.path} />,
                label: <span className="tt-tabmenu-row" title={f.path}><span className="nm">{f.path.split('/').pop() || f.path}</span>
                  <button type="button" className="tt-x" aria-label={t('common.close')} title={t('common.close')} onClick={(e) => { e.stopPropagation(); closeFile(f.path) }}>{TI.close}</button></span>,
                onClick: () => onFileTab?.(f.path),
              })) }] : []),
          ],
        }}>
          <button type="button" className="tt-tabs-nav wide" aria-label={t('tabs.all')} title={t('tabs.all')}>
            <TabsIcon size={15} /><b>{tabs.length + (fileTabs || []).length}</b>
          </button>
        </Dropdown>
      )}
      {onNew && (
        <div className="tt-tabs-end">
          <Dropdown trigger={['click']} placement="bottomRight" menu={{ items: [{
            type: 'group' as const, label: onNew.taskLabel ? t('tabs.newInTask', { task: onNew.taskLabel }) : t('tabs.newHere'),
            children: [
              { key: 'terminal', icon: <TerminalIcon size={14} />, label: t('tabs.newTerminal'), onClick: onNew.terminal },
              { key: 'claude', icon: <AgentLogo kind="claude" size={14} />, label: t('tabs.newClaude'), onClick: onNew.claude },
              { key: 'codex', icon: <AgentLogo kind="codex" size={14} />, label: t('tabs.newCodex'), onClick: onNew.codex },
            ],
          }] }}>
            <button type="button" className="tt-tbtn" title={t('tabs.new')}>
              <PlusIcon size={13} /><span>{t('tabs.new')}</span>
              <span style={{ color: 'var(--text-dimmer)', display: 'inline-flex' }}><ChevronDown size={11} /></span>
            </button>
          </Dropdown>
          {inspector && (
            <button type="button" className={`tt-tbtn ico${inspector.open ? ' on' : ''}`} onClick={inspector.toggle}
              aria-label={t('inspector.toggle')} title={t('inspector.toggle')} aria-pressed={inspector.open}>
              <PanelRightIcon size={15} />
            </button>
          )}
        </div>
      )}
    </div>
  )
  // ── 手机会话页顶栏（13 §5.1）：一行 50，取代「标签条 + 工具条」两行 79 ──
  // 中间胶囊点开 = 会话切换 sheet（取代横滑标签条）；除 Agent 视图切换外，其余控件全进「⋯」。
  // **不能按 !inChat 收窄**：切到 Claude/Codex 对话视图后 phoneChrome 变 null，
  // 整块外壳就掉回桌面那套「标签条 + 工具条」——按一下渲染模式，页面样式全变了。
  // 对话只该换中间那块内容，顶栏（返回 / 会话胶囊 / Agent 切换 / 更多）自始至终是同一条。
  const phoneChrome = isPhone ? (
    <>
      <div className="tt-sesshead">
        <button type="button" className="ic" aria-label={t('common.collapse')} onClick={onCollapse}>
          {TI.back}
        </button>
        {/* 灵动岛：胶囊本身就是当前会话的状态显示器，不只是个「点我换会话」的按钮。
            名字吃掉所有余量、右侧那簇贴边——之前名字不 grow，一胶囊右半截是空的，
            看着像没画完。待确认时整颗岛变黄并浮出文字：那是唯一需要人立刻动手的状态，
            只把 8px 的点变黄在 50px 顶栏里根本注意不到。 */}
        <button type="button" className={`pill${activeNeedsInput ? ' wait' : ''}`} onClick={() => setSwitchOpen(true)}>
          <i className={`d${activeAgentLive && !activeNeedsInput ? ' live' : ''}`} style={{ background: dot }} />
          {active && <TabName name={active} project={false} />}
          {/* 右侧那簇裹成一个：名字要绝对居中，就得让流里只剩「左一个、右一个」，
              否则 space-between 会把计数也均分到中间去 */}
          <span className="ri">
            {activeNeedsInput && <span className="tag">{t('session.waiting')}</span>}
            {terms.length > 1 && <span className="n">{terms.length}</span>}
            <span className="ca">{TI.caret}</span>
          </span>
        </button>
        {active && claudeMap[active]?.running && (
          <button type="button" className={`ic${claudeView[active] ? ' on' : ''}`} aria-label="Claude"
            onClick={() => setClaudeView((v) => ({ ...v, [active!]: !v[active!] }))}>
            <AgentLogo kind="claude" size={16} />
          </button>
        )}
        {active && codexMap[active]?.running && (
          <button type="button" className={`ic${codexView[active] ? ' on' : ''}`} aria-label="Codex"
            onClick={() => setCodexView((v) => ({ ...v, [active!]: !v[active!] }))}>
            <AgentLogo kind="codex" size={16} />
          </button>
        )}
        <button type="button" className="ic" aria-label={t('common.more')} onClick={() => setMoreSheet(true)}>
          {TI.dots}
        </button>
      </div>
      <SessionSwitchSheet open={switchOpen} onClose={() => setSwitchOpen(false)}
        sessions={terms} active={active} needsInput={termNeedsInput}
        running={(n) => !!(claudeMap[n]?.running || codexMap[n]?.running)}
        onPick={setActive} onCloseSession={closeTerm} />
      <MobileSheet open={moreSheet} title={t('common.more')} onClose={() => setMoreSheet(false)}>
        <SheetSection>{t('mobile.groupSession')}</SheetSection>
        <SheetRow icon={TI.rename} title={t('session.rename')} onClick={() => { setMoreSheet(false); active && setRenameSession(active) }} />
        <SheetRow icon={TI.newTab} title={t('terminal.newTab')}
          onClick={() => { setMoreSheet(false); active && window.open(`/#/term/${encodeURIComponent(active)}`, '_blank') }} />
        {/* 「中断」得在这儿常驻：带 ^C 的快捷键条只在打字时才升起来，而 agent 跑飞了要停它的
            那一刻，手根本不在输入框上。danger 是给这一下的分量做的记号。 */}
        <SheetRow icon={<StopIcon size={20} />} danger title={t('terminal.interrupt')} desc={t('terminal.interruptDesc')}
          onClick={() => { setMoreSheet(false); void interruptActive() }} />
        <SheetSection>{t('mobile.groupPanels')}</SheetSection>
        <SheetRow icon={TI.folder} title={t('chat.files')} onClick={() => { setMoreSheet(false); toggleFiles() }} />
        <SheetRow icon={TI.git} title={t('git.title')} onClick={() => { setMoreSheet(false); toggleGit() }} />
        <SheetRow icon={TI.mic} title={t('voice.input')} onClick={() => { setMoreSheet(false); setShowVoice((v) => !v) }} />
        <SheetRow icon={promptOff ? TI.bellOff : TI.bellOn} title={t('prompt.popup')}
          desc={promptOff ? t('prompt.popupOff') : t('prompt.popupOn')} onClick={togglePromptOff} />
        <SheetRow icon={TI.dpad} title={t('mobile.dpadOn')} desc={ws.dpadOn ? t('common.on') : t('common.off')}
          onClick={() => saveWorkspace({ dpadOn: !ws.dpadOn })} />
        {ws.dpadOn && (
          <SheetRow icon={TI.dpad} title={t('mobile.dpadSide')} desc={ws.dpadSide === 'left' ? t('common.on') : t('common.off')}
            onClick={() => saveWorkspace({ dpadSide: ws.dpadSide === 'left' ? 'right' : 'left' })} />
        )}
        {/* 画面工具只对终端画布有意义：对话视图有自己的滚动与排版 */}
        {!inChat && <SheetSection>{t('mobile.groupScreen')}</SheetSection>}
        {!inChat && <div className="tt-sheet-grid">
          <button type="button" onClick={() => setFontSize(Math.max(10, fontSize - 1))}>A−</button>
          <button type="button" onClick={() => setFontSize(Math.min(22, fontSize + 1))}>A+</button>
          <button type="button" onClick={() => active && termRefs.current[active]?.scroll(-12)}>{TI.scrollUp}</button>
          <button type="button" onClick={() => active && termRefs.current[active]?.toBottom()}>{TI.toBottom}</button>
          <button type="button" onClick={() => active && termRefs.current[active]?.redraw()}>{TI.redraw}</button>
          <button type="button" onClick={() => active && termRefs.current[active]?.reconnect()}>{TI.reconnect}</button>
        </div>}
      </MobileSheet>
    </>
  ) : null

  // 工具条分三段：左=会话身份与动作，中=面板开关，右（分段组）=只读的画面控制
  const connLabel = activeNeedsInput ? t('session.waiting') : st === 'connected' ? t('terminal.status.connected') : st === 'connecting' ? t('terminal.status.connecting') : t('terminal.status.disconnected')
  // 连接状态 + Claude/Codex 视图开关：工具条左侧，终端视图和对话视图一样
  const sessionLead = (
    <>
      <span className="tt-status">{statusDot(dot, 7)}{connLabel}</span>
      {active && claudeMap[active]?.running && (
        <TBtn icon={<AgentLogo kind="claude" size={14} />} label="Claude" on={!!claudeView[active]}
          title={t('chat.switchToClaude')} onClick={() => setClaudeView((v) => ({ ...v, [active!]: !v[active!] }))} />
      )}
      {active && codexMap[active]?.running && (
        <TBtn icon={<AgentLogo kind="codex" size={14} />} label="Codex" tone="ok" on={!!codexView[active]}
          title={t('chat.switchToCodex')} onClick={() => setCodexView((v) => ({ ...v, [active!]: !v[active!] }))} />
      )}
    </>
  )
  const sessionToolbar = (
    <div className="tt-tbar tt-session-toolbar">
      {sessionLead}<span className="tt-sep" />
      <Dropdown trigger={['click']} menu={{ items: tmuxMenu(t) as any, onClick: ({ key }) => { if (key === PFX + 'x') openPaneCloseConfirm(); else sendKey(key) } }} placement="bottomLeft">
        <button type="button" className="tt-tbtn">{TI.tmux}<span>tmux</span><span style={{ color: 'var(--text-dimmer)', display: 'inline-flex' }}><ChevronDown size={11} /></span></button>
      </Dropdown>
      {/* 「新标签」进了标签右键菜单（标签条上已有「新建」）；文件 / Git 归右栏活动条；
          语音归 composer——22 设计 §3.3 去掉的四枚。独立页（左停靠）没有右栏，文件 / Git 仍在这 */}
      {active && <TBtn icon={TI.rename} label={t('session.rename')} title={t('session.renameTitle')} onClick={() => setRenameSession(active)} />}
      {/* 终端视图的话筒：识别结果填到命令行上，回车才发（同 /type 的约定）。对话视图的话筒在 composer 里，不重复。
          不看 showVoiceButton：那个开关管的是手机上的悬浮圆钮；工具条这枚和 composer 里那枚一样常在 */}
      {active && !inChat && !isPhone && (
        <VoiceInput toolbar hotkey accent="var(--accent)" onResult={(text) => { api('POST', `/sessions/${encodeURIComponent(active)}/type`, { text }).catch((e: any) => message.error(e.message)) }} />
      )}
      <span className="tt-sep" />
      <TBtn icon={promptOff ? TI.bellOff : TI.bellOn} label={t('prompt.popup')} on={!promptOff}
        title={promptOff ? t('prompt.popupOff') : t('prompt.popupOn')} onClick={togglePromptOff} />
      {fileDock === 'left' && <TBtn icon={TI.folder} label={t('chat.files')} on={showFiles} title={t('terminal.fileBrowserTitle')} onClick={toggleFiles} />}
      {fileDock === 'left' && <TBtn icon={TI.git} label={t('git.title')} on={showGit} title={t('terminal.gitPanelTitle')} onClick={toggleGit} />}
      <span className="tt-spacer" />
      <span className="tt-tgroup">
        <TBtn icon={TI.scrollUp} title={t('terminal.scrollHistory')} onClick={() => active && termRefs.current[active]?.scroll(-12)} />
        <TBtn icon={TI.toBottom} title={t('terminal.toBottom')} onClick={() => active && termRefs.current[active]?.toBottom()} />
      </span>
      <span className="tt-tgroup" style={{ marginLeft: 6 }}>
        <TBtn label={<span style={{ fontWeight: 600 }}>A−</span>} title={t('terminal.decreaseFont')} onClick={() => setFontSize(Math.max(10, fontSize - 1))} />
        <TBtn label={<span style={{ fontWeight: 600 }}>A+</span>} title={t('terminal.increaseFont')} onClick={() => setFontSize(Math.min(22, fontSize + 1))} />
      </span>
      <span className="tt-tgroup" style={{ marginLeft: 6 }}>
        <TBtn icon={TI.redraw} title={t('terminal.redraw')} onClick={() => active && termRefs.current[active]?.redraw()} />
        <TBtn icon={TI.reconnect} title={t('terminal.reconnect')} onClick={() => active && termRefs.current[active]?.reconnect()} />
      </span>
      {/* Focus 与「返回分栏」是同一枚按钮的两态（14 §7.2）：不额外插一条只在
          Focus 时出现的横条——那种横条会让 Focus 前后的工具条高度跳一下。 */}
      {focus && (
        <TBtn icon={focus.on ? TI.unfocus : TI.focus} label={focus.on ? t('workspace.exitFocus') : t('workspace.focusDock')}
          on={focus.on} title={`${focus.on ? t('workspace.exitFocus') : t('workspace.focusDock')} (${focus.hint})`}
          onClick={focus.toggle} />
      )}
    </div>
  )
  // 方向簇（13 §5.3）：贴在终端画布上，不吃终端高度。
  //
  // **只在 TUI 里出现**——Claude/Codex 在跑的时候。它存在的全部理由是「在选项列表里选一项
  // 时不必弹软键盘」；普通 shell 下你本来就要打字，键盘总要弹，一个没有标签的十字浮在那儿
  // 只会让人问「这是干嘛的」（用户原话）。对话视图有自己的输入框，同样不挂。
  const agentRunning = !!(active && (claudeMap[active]?.running || codexMap[active]?.running))
  const dpad = isPhone && !inChat && agentRunning && ws.dpadOn ? (
    <>
      <DPad side={ws.dpadSide} onSend={(seq) => tapKey(seq)} onHide={() => saveWorkspace({ dpadOn: false })} />
      {/* 一次性说明：一个没有标签的十字自己解释不了自己 */}
      {!ws.dpadHintSeen && (
        <div className="tt-dpad-hint">
          <span className="tx">
            <b>{t('mobile.dpadHintTitle')}</b>
            {t('mobile.dpadHintBody')}
          </span>
          <button type="button" onClick={() => saveWorkspace({ dpadHintSeen: true })}>{t('mobile.dpadHintOk')}</button>
        </div>
      )}
    </>
  ) : null

  const terminalArea = (
    <div className={dpad ? 'tt-has-dpad' : undefined}
      style={{ flex: 1, minHeight: 0, display: 'flex', position: 'relative' }}
      onDragOver={(e) => {
        // 会话拖到画面上 = 说给**当前**会话听。自定义 MIME 与路径拖拽
        // (application/x-ttmux-path) 天然分得开，两条路互不干扰
        if (isSessionDrag(e)) {
          e.preventDefault(); e.stopPropagation()
          e.dataTransfer.dropEffect = 'copy' // 见标签那处：none 会让 drop 根本不投递
          setDragOver(agentRunning)
          return
        }
        if (isFileDrag(e)) { e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = 'copy'; setDragOver(true); return } // 系统文件：允许放下并上传
        if (!isPathDrag(e)) return
        if (inTermSplitZone(e)) { setDragOver(false); return } // 右半区：让事件冒泡给 FileWorkspace 显示分栏提示
        e.stopPropagation(); allowPathDrop(e); setDragOver(true)
      }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false) }}
      onDrop={onTermDrop}>
      {dpad}
      {dragOver && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 5, pointerEvents: 'none',
          border: '2px dashed var(--accent)', borderRadius: 'var(--r-sm)', background: 'rgba(88,166,255,.08)',
          display: 'grid', placeItems: 'center', color: 'var(--accent)', fontSize: 14, fontWeight: 600,
        }}>{t('terminal.dropToMention')}</div>
      )}
      <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
        {!active && !curFile && onNew && (
          <div className="tt-tabs-empty">{t('tabs.empty')}<small>{t('tabs.emptyHint')}</small></div>
        )}
        {terms.map((termName) => (
          // 非当前终端不能用 display:none：xterm 会暂停渲染且容器尺寸归零，切换或关闭当前标签时
          // 下一张 WebGL 画布要经过“重新量尺寸 → 清画布 → 重画”，中间会露出 1~2 帧黑屏。
          // visibility:hidden 保留真实尺寸并让后台画布保持就绪；pointerEvents/zIndex 隔离交互与层叠。
          <div key={termName} style={{
            position: 'absolute', inset: 0, padding: 6,
            visibility: termName === active && !curFile ? 'visible' : 'hidden',
            pointerEvents: termName === active && !curFile ? 'auto' : 'none',
            zIndex: termName === active && !curFile ? 1 : 0,
          }}>
            <Term ref={(h) => { termRefs.current[termName] = h }} name={termName} fontSize={fontSize} active={termName === active} onStatus={(s) => setStatus(termName, s)} onRevived={onRename}
              onContextMenu={({ x, y, selection }) => { setActive(termName); setCtx({ x, y, session: termName, selection }) }}
              onSelectionMenu={({ selection }) => { setActive(termName); setCtx(null); if (selection.trim()) { copyText(selection); message.success(t('common.copied')) } }}
              onPaste={() => { setActive(termName); pasteClipboard(termName) }}
              onImagePaste={(files) => { setActive(termName); pasteImage(termName, files) }} />
            {claudeView[termName] && claudeMap[termName]?.running && (
              <div style={{ position: 'absolute', inset: 0 }}>
                <ClaudeChat name={termName} file={claudeMap[termName].file} onOpenFile={openFileFromChat} onOpenGit={openGitFromChat} active={termName === active && !curFile} />
              </div>
            )}
            {codexView[termName] && codexMap[termName]?.running && (
              <div style={{ position: 'absolute', inset: 0 }}>
                <CodexChat name={termName} file={codexMap[termName].file} onOpenFile={openFileFromChat} onOpenGit={openGitFromChat} active={termName === active && !curFile} />
              </div>
            )}
            {/* 悬浮话筒只留给手机：桌面的在工具条上（重命名旁边） */}
            {showVoice && isPhone && !claudeView[termName] && !codexView[termName] && (
              <VoiceInput accent="var(--accent)" onResult={(text) => { api('POST', `/sessions/${encodeURIComponent(termName)}/type`, { text }).catch((e: any) => message.error(e.message)) }} />
            )}
          </div>
        ))}
        {/* 文件层（22 设计 §3.3）：每个文件标签一层，只有当前那层显示；FileView 的 active 只给当前，
            其余的 Monaco 不渲染、draft 留着——二十个标签只有一个编辑器实例 */}
        {(fileTabs || []).map((f) => {
          const on = curFile === f.path
          return (
            <div key={'file:' + f.path} style={{ position: 'absolute', inset: 0, zIndex: on ? 7 : 0, display: on ? 'block' : 'none', background: 'var(--bg-base)' }}>
              {f.mode === 'changes'
                ? (on && <ChangesView path={f.path} root={taskDir || ''} />)
                : (
                  <FileView path={f.path} accent="var(--accent)" inline tabbed forcePreview={f.mode === 'preview'} active={on}
                    onClose={() => closeFile(f.path)} onOpenPath={(p) => onFileTab?.(p)}
                    onDirtyChange={(p, d) => { setFileDirty(p, d); if (d) onPinFile?.(p) }}
                    revealLine={reveal?.path === f.path ? { line: reveal.line, nonce: reveal.nonce } : undefined} />
                )}
            </div>
          )
        })}
      </div>
    </div>
  )
  const sessionBottom = (
    <>
      {isTouch && !inChat && (
        <div style={{ display: 'flex', gap: 'var(--sp-2)', padding: '8px 8px 0' }} onDragOver={allowPathDrop} onDrop={onInputDrop}>
          <Input ref={mobileInputRef} value={line}
            onFocus={() => { exitCopyMode(); setTyping(true) }}
            // 延后收起：点快捷键条上的键会先让输入框失焦，立刻收就把那一条抽走了
            onBlur={() => setTimeout(() => setTyping(false), 180)}
            onChange={(e) => setLine(e.target.value)}
            onPressEnter={(e) => { if ((e.nativeEvent as any).isComposing) return; submitLine() }}
            placeholder={t('terminal.mobileInputPlaceholder')} allowClear autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false} />
          <Button type="primary" onMouseDown={noBlur} onClick={submitLine}>{t('common.send')}</Button>
        </div>
      )}
      {/* 快捷键条只在输入态出现（13 §5.2）：它常驻 49px，而不打字时一个键也用不上——
          手机上这 49px 直接等于终端少 3 行。桌面不受影响。
          `tt-keyrow` 给两侧渐隐 + 滚轮横移：这一条 15 个按钮宽 913，窄栏里只露得出 605，
          而原来既没有渐隐也没有滚动条，右边缘正好把某个键切成一半——看着就是"没显示全"。 */}
      {!inChat && isTouch && (!isPhone || typing) && (
        <div className="tt-keyrow" ref={keyRowRef}
          onScroll={syncKeyFade}
          onWheel={(e) => {
            const el = keyRowRef.current
            if (!el || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return
            el.scrollLeft += e.deltaY
          }}
          data-l={keyFadeL ? '1' : undefined} data-r={keyFadeR ? '1' : undefined}
          style={{ display: 'flex', gap: 'var(--sp-2)', padding: 8, borderTop: '1px solid var(--border)', overflowX: 'auto' }}>
          <Button type="primary" onMouseDown={noBlur} style={{ flex: '0 0 auto' }}
            onClick={() => (isTouch ? submitLine() : sendKey('\r'))}>Enter</Button>
          {/* 触屏没有 Ctrl+Shift+V / 右键菜单在长按选词后也不再弹出，丝带上补一个直达粘贴 */}
          {isTouch && <Button onMouseDown={noBlur} onClick={() => active && pasteClipboard(active)} style={{ flex: '0 0 auto' }}>{t('terminal.pasteAction')}</Button>}
          {(prefsData.quickCommands || []).map((cmd) => (
            <Button key={cmd} onMouseDown={noBlur} onClick={() => { if (isTouch) { setLine(cmd); requestAnimationFrame(() => mobileInputRef.current?.focus()) } else { sendRaw(cmd) } }} style={{ flex: '0 0 auto' }}>{cmd}</Button>
          ))}
          {KEYS.map(([label, seq]) => (
            <Button key={label} onMouseDown={noBlur} onClick={() => tapKey(seq)} style={{ flex: '0 0 auto' }}>{label}</Button>
          ))}
          <Button onMouseDown={noBlur} style={{ flex: '0 0 auto', borderStyle: 'dashed' }} onClick={() => {
            let val = ''
            modal.confirm({
              title: t('settings.quickCommands'),
              content: <Input placeholder={t('settings.quickCommandPlaceholder')} onChange={(e) => (val = e.target.value)} autoFocus />,
              okText: t('quickCmd.addOk'),
              onOk: () => {
                const v = val.trim()
                if (!v) return
                if ((prefsData.quickCommands || []).includes(v)) return
                savePreferences({ quickCommands: [...(prefsData.quickCommands || []), v] })
              },
            })
          }}>{t('quickCmd.add')}</Button>
        </div>
      )}
    </>
  )

  return (
    // paddingBottom=env(keyboard-inset-height)：软键盘悬浮覆盖时(见 main.tsx/index.html)，
    // 把整块内容抬到键盘之上，让底部输入条/快捷键栏不被遮住。桌面无虚拟键盘 → 0，无影响。
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, paddingBottom: 'env(keyboard-inset-height, 0px)', transition: 'padding-bottom .15s ease-out' }}>
      {active && <PromptDialog name={active} accent={codexMap[active]?.running ? 'var(--ok)' : 'var(--accent)'} enabled={!inChat && !promptOff} />}
      <Modal
        open={pasteOpen}
        title={t('terminal.pasteTitle')}
        okText={t('terminal.pasteAction')}
        cancelText={t('common.cancel')}
        destroyOnClose
        onCancel={() => setPasteOpen(false)}
        onOk={() => {
          sendPaste(pasteSession, pasteText)
          setPasteOpen(false)
          message.success(t('terminal.pasted'))
        }}
      >
        <Input.TextArea
          autoFocus
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          autoSize={{ minRows: 6, maxRows: 12 }}
          placeholder={t('terminal.pastePlaceholder')}
        />
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 8 }}>
          {t('terminal.pasteHelp')}
        </div>
      </Modal>
      <RenameSessionModal session={renameSession} onClose={() => setRenameSession(null)} onDone={onRename} />
      <Dropdown
        open={!!ctx}
        trigger={[]}
        menu={{ items: ctxItems as any, onClick: onCtxClick }}
        onOpenChange={(open) => { if (!open) setCtx(null) }}
        placement="bottomLeft"
      >
        <span style={{ position: 'fixed', left: ctx?.x ?? -1000, top: ctx?.y ?? -1000, width: 1, height: 1, pointerEvents: 'none' }} />
      </Dropdown>
      {/* 独立全屏页（左侧文件停靠）：顶部细标题栏显示会话名，横跨左右；下面才是「左文件 / 右会话」 */}
      {fileDock === 'left' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 12px', borderBottom: '1px solid var(--border)', minHeight: 32 }}>
          <span style={{ color: 'var(--text-bright)', fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{active || ''}</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.5, background: 'var(--brand-grad)', WebkitBackgroundClip: 'text', backgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Roami</span>
        </div>
      )}
      {/* 内容主体：左侧走 <FileWorkspace>（文件树 + 编辑器多 tab）；右侧抽屉走原地布局。
          会话（终端）各部件用上面抽出的 sessionTab/sessionToolbar/terminalArea/sessionBottom 复用。 */}
      {fileDock === 'left' ? (
        <FileWorkspace
          dir={cwd} accent="var(--accent)"
          explorerOpen={showFiles} onExplorerClose={() => setShowFiles(false)} onExplorerOpen={() => setShowFiles(true)}
          leadingTitle={active || ''} leadingTab={sessionTab}
          leadingContent={terminalArea} chrome={sessionToolbar} footer={sessionBottom}
        />
      ) : (
        <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
          <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            {phoneChrome || <>{tabStrip}{curFile
              ? <FilePathBar path={curFile} root={taskDir || ''} mode={(fileTabs || []).find((f) => f.path === curFile)?.mode || 'source'} onMode={(m) => onFileMode?.(curFile, m)} />
              : sessionToolbar}</>}
            {terminalArea}
            {!curFile && sessionBottom}
          </div>
        </div>
      )}
      {/* 文件树也进 Inspector：它是最后一种「从右边出来一块」的浮层（420 fixed，
          同样盖住终端）。收进来之后 文件 / Git / Worktree 三者互斥——同一时刻只有一个
          Inspector，关掉栈顶自然露出下面那个（图纸 panels-desktop.html §二）。 */}
      {/* 右停靠的文件 / Git 抽屉没了：归右栏 InspectorPanels（22 设计 §3.4）。
          这里只剩左停靠（#/term 独立页）和手机上没有右栏时的文件 / Git 二级页。 */}
      {fileDock === 'right' && !onOpenFile && (
        <AdaptivePanel open={showFiles} layer="session" title={t('nav.files')}
          onClose={() => setShowFiles(false)}>
          <FileBrowser dir={cwd} accent="var(--accent)" layout="dock" onClose={() => setShowFiles(false)}
            openRequest={dockFileReq || undefined} />
        </AdaptivePanel>
      )}
      <AdaptivePanel open={showGit && !onOpenGit} layer="session" title={t('git.title')}
        onClose={() => setShowGit(false)}>
        <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}><Spin /></div>}>
          <GitPanel dir={cwd} accent="var(--accent)" onClose={() => setShowGit(false)} />
        </Suspense>
      </AdaptivePanel>
      {paneCloseTarget && (
        <PaneCloseConfirm
          target={paneCloseTarget} busy={paneCloseBusy} error={paneCloseError}
          onConfirm={confirmPaneClose} onCancel={() => setPaneCloseTarget(null)}
        />
      )}
    </div>
  )
}
