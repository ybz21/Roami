// 对话页外壳：滚动区 / 交互选择框 / 输入发送。
// 会话名、切回终端、文件面板都在上方的会话工具条里，这里不再重复一行头部。
// Claude、Codex 共用，差异只在 accent、占位文案与消息渲染(renderMessage)。
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { appendPaths, atPath } from '../../agent-paths'
import { Button, Input, App as AntApp } from 'antd'
import { api, upload, makeClipboardImageFile } from '../../api'
import { PromptPanel } from '../prompt'
import { useI18n } from '../../i18n'
import { VoiceInput } from './VoiceInput'
import type { Block, Msg } from './types'
import { groupRuns } from './runs'
import { ToolRun } from './ToolRun'
import { LiveTail } from './LiveTail'
import { useLayout } from '../../layout'
import { ArrowToBottom, ArrowUp, FileTextIcon, PaperclipIcon, StopIcon, TerminalIcon, AgentLogo } from '../../icons'
import { SESSION_MIME, buildIntro, canDrop, readDrag, type SessionDrag } from '../shell/session-drop'
import { currentNodeId } from '../cluster/node-url'
import { sessionDisplay } from '../sessions/session-label'
import { ChatActionsProvider } from './actions'
import type { TaskIndex } from './tasks'
import { ComposerPlus } from './ComposerPlus'
import { StatusBar, type StatusActions } from './StatusBar'
import type { AgentStatus } from './status'

// 排队中气泡的会话名 → 队列。模块级、不随组件卸载清空（见下方注释）。
// 数量很小（几条文本），且已发出的会话消息很快就会被转录对账掉，不会无限增长。
const outboxStore = new Map<string, { id: number; text: string }[]>()

export function ChatShell({ name, accent, placeholder, messages, results, renderMessage, pending, busy, error, onOpenFile, tasks, status, onOpenGit, lastErrorId, hasEarlier, onLoadEarlier, agent, emptyHint, active }: {
  /** 这条 composer 发给谁：左端那枚亮着的 agent pill（22 设计 §3.3） */
  agent?: 'claude' | 'codex'
  /** 还没有对话文件（agent 刚起、一句没说）：显示这句而不是「加载中」 */
  emptyHint?: string
  name: string
  accent: string
  placeholder: string
  messages: Msg[]
  /** tool_use id → tool_result。给了就把相邻的同族工具并成运行组（设计 16） */
  results?: Record<string, Block>
  renderMessage: (m: Msg, i: number) => ReactNode
  pending?: ReactNode
  busy?: boolean
  error?: string
  onOpenFile?: (path: string, line?: number) => void
  tasks?: TaskIndex
  status?: AgentStatus
  onOpenGit?: () => void
  lastErrorId?: string
  /** 后端首屏截过头：还有更早的没取过来 */
  hasEarlier?: boolean
  /** 把首屏窗口放大一档重取（往回翻） */
  onLoadEarlier?: () => void
  /**
   * 是不是当前标签。所有跑着 agent 的会话对话都常驻挂着（切标签只翻 visibility），
   * 不在前台的那几份不渲染消息列表——否则点一下标签，N 份 × 200 条消息一起重建 DOM、
   * 各做一次同步回流，切换要卡好几秒。
   */
  active?: boolean
}) {
  const live = active !== false
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sendErr, setSendErr] = useState('')
  const [showJump, setShowJump] = useState(false)
  // 未读：上滚离底之后新来了几条。贴底时恒为 0（看得见就不叫未读）。
  const [unread, setUnread] = useState(0)
  const seenCount = useRef(0)
  const [limit, setLimit] = useState(200) // 只渲染最近 N 条，超长转录不卡
  const [dragOver, setDragOver] = useState(false)
  const [dropMode, setDropMode] = useState<'upload' | 'path' | 'session'>('upload')
  const [uploading, setUploading] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const atBottom = useRef(true)
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  // 手机窄屏：输入区换成「文本框独占一行 + 按钮行」竖排，避免挤成一坨
  const { phone: isMobile } = useLayout()
  // 语音按钮的显隐跟终端工具条那颗「语音输入」开关是同一个偏好：关了就整个页面都不出现麦克风。
  // 触屏上点按钮不夺走文本框焦点 → 软键盘不收起 → 布局不回弹，click 不会落空（同 App 的 noBlur）。
  const noBlur = (e: React.MouseEvent) => { if (isMobile) e.preventDefault() }

  // 把文本追加进输入框末尾（语音识别结果 / 路径插入共用）
  const appendText = (s: string) => setInput((v) => (v ? v.replace(/\s*$/, ' ') : '') + s + ' ')
  // 把路径以 @引用 插进输入框（文件侧栏「@」按钮 / 拖拽共用），与终端 toMention 一致
  const insertPath = (p: string) => appendText(atPath(p))
  // 对话视图里拖进来一个会话：和终端那边同一件事，同一段介绍词
  const introduce = async (drag: SessionDrag) => {
    const v = canDrop(drag, { id: name, node: currentNodeId() || '', hasAgent: true })
    if (!v.ok) {
      message.warning(t(v.why === 'cross' ? 'pair.crossNode' : 'pair.noAgent', { name: drag.label || drag.id }))
      return
    }
    try {
      await api('POST', '/tasks/_/send', { sess: name, msg: buildIntro(drag, name, t) })
      message.success(t('pair.sent', { name: sessionDisplay(name), peer: drag.label || drag.id }))
    } catch (e: any) { message.error(e.message) }
  }

  // 图片上传到 /tmp 并把完整路径插进输入框（等同桌面 Ctrl+V：不污染工作目录，模型按绝对路径读取）
  const uploadImagesToTmp = async (images: File[]) => {
    if (!images.length) return
    const res = await upload('/tmp', images)
    setInput((v) => appendPaths(v, res.saved))
    message.success(t('chat.uploadedFiles', { count: images.length, dir: '/tmp' }))
  }

  // 普通文件上传到会话工作目录并插入文件名，方便直接让模型处理
  const uploadFilesToCwd = async (files: File[]) => {
    if (!files.length) return
    const cwd = await api('GET', `/sessions/${encodeURIComponent(name)}/cwd`)
    const dir = cwd?.data?.dir
    if (!dir) { message.error(t('chat.cwdMissing')); return }
    const res = await upload(dir, files)
    // 插完整路径而不是文件名：@ 后面跟绝对路径，模型不必猜「相对谁」——
    // agent 的工作目录未必就是这个 dir（worktree、cd 过、子 agent 都可能不同）。
    setInput((v) => appendPaths(v, res.saved))
    message.success(t('chat.uploadedFiles', { count: res.saved.length, dir }))
  }

  // 拖拽/📎 选择：图片走 /tmp+绝对路径（同 Ctrl+V），其余文件走工作目录+文件名。
  // 注意入参可能是 <input> 的 FileList——调用方须在本函数返回前(await 前)就取好，
  // 因为重置 input.value 会清空该 FileList（手机端上传图片报 NO_FILE 的根因）。
  const doUpload = async (files: FileList | File[]) => {
    const all = Array.from(files)
    if (!all.length || uploading) return
    setUploading(true)
    try {
      await uploadImagesToTmp(all.filter((f) => f.type.startsWith('image/')))
      await uploadFilesToCwd(all.filter((f) => !f.type.startsWith('image/')))
    } catch (e: any) { message.error(t('chat.uploadFailed', { message: e.message })) }
    finally { setUploading(false) }
  }

  const onPaste = async (e: React.ClipboardEvent) => {
    if (!e.clipboardData?.items) return
    // 一次粘贴只取一张图：同一张截图常以多种 MIME 重复出现，全收会插入两次 @路径
    const imageFiles: File[] = []
    for (let i = 0; i < e.clipboardData.items.length; i++) {
      const item = e.clipboardData.items[i]
      if (item.type.startsWith('image/')) {
        const f = item.getAsFile()
        if (f) { imageFiles.push(makeClipboardImageFile(f, item.type, imageFiles.length)); break }
      }
    }
    if (imageFiles.length > 0) {
      e.preventDefault()
      if (uploading) return
      setUploading(true)
      try { await uploadImagesToTmp(imageFiles) }
      catch (err: any) { message.error(t('chat.uploadFailed', { message: err.message })) }
      finally { setUploading(false) }
    }
  }

  // TUI 会把用户刚发的那句回显在框里，实时回显要按它去重
  const lastUserText = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') return messages[i].blocks.map((b) => b.text || '').join('\n').trim()
    }
    return ''
  }, [messages])

  const hidden = Math.max(0, messages.length - limit)
  // 必须 memo：slice 每次都是新数组，下面的分组 useMemo 和 layout effect 全靠它的引用判「没变」
  const visible = useMemo(() => (hidden > 0 ? messages.slice(-limit) : messages), [messages, limit, hidden])
  // 连着的同族工具调用并成运行组（设计 16）。分组只能在这一层做：Claude 每次工具调用
  // 单独成一条消息，一串 5 条命令就是 5 条消息，消息内部的分段对它无能为力。
  const items = useMemo(() => (results ? groupRuns(visible, results) : null), [visible, results])

  // 贴底时自动跟随新消息；用户上滚后不打扰，改成累计未读。
  //
  // 离底时还要「锚住」：新消息一来，只渲染最近 N 条的窗口就往前滑，顶上那几条被摘掉，
  // 剩下的内容整体上移——你读着读着字自己往上跑，手感就是「滚不上去、老被拽回底部」。
  // 所以顶部身份一变就按高度差回补 scrollTop，让眼皮底下那段纹丝不动。
  // 必须是 useLayoutEffect：它在 paint 之前跑完，补位是「本来就没动过」；
  // 放在 useEffect 里补，用户会先看见跳一下再跳回来。
  const anchor = useRef({ height: 0, top: 0, firstId: '' })
  useLayoutEffect(() => {
    const el = boxRef.current
    if (!el || !live) return
    const firstId = visible[0]?.id || ''
    if (atBottom.current) {
      el.scrollTop = el.scrollHeight
      seenCount.current = messages.length
      setUnread(0)
    } else {
      if (anchor.current.firstId && firstId !== anchor.current.firstId) {
        el.scrollTop = anchor.current.top + (el.scrollHeight - anchor.current.height)
      }
      setUnread(Math.max(0, messages.length - seenCount.current))
    }
    anchor.current = { height: el.scrollHeight, top: el.scrollTop, firstId }
  }, [messages, pending, visible, live])

  const onScroll = () => {
    const el = boxRef.current
    if (!el) return
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    setShowJump(!atBottom.current)
    if (atBottom.current) { seenCount.current = messages.length; setUnread(0) }
  }

  const jump = () => {
    atBottom.current = true; setShowJump(false)
    seenCount.current = messages.length; setUnread(0)
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }

  /**
   * 发出去了、但还没出现在转录里的消息。
   *
   * Agent 正忙的时候，消息进的是 TUI 自己的排队区（「Press up to edit queued messages」），
   * 它不在转录文件里——而这一页画的就是转录。于是从用户视角看：打了一句、按了回车、
   * 输入框清空了，然后什么都没有，连自己刚说了什么都翻不到。这里本地留一份，画成
   * 「排队中」的气泡，等它真进转录（下面那个 effect 按原文对账）再撤掉。
   */
  // 存在组件外的模块级表，不是 useState 的初值：手机上切会话会把没在看的那个从 DOM 里摘掉
  //（同一时间只挂一个终端连接），ChatShell 跟着卸载，state 初始化一次就清零了——
  // 于是"切一下会话再切回来，排队中的气泡凭空消失"，其实消息已经发出去、真排在 TUI 队列里，
  // 消失的只是本地这个提示气泡。按会话名存到组件外面，卸载/重挂都读得到同一份。
  const [outbox, setOutboxState] = useState<{ id: number; text: string }[]>(() => outboxStore.get(name) || [])
  const setOutbox = (fn: (q: { id: number; text: string }[]) => { id: number; text: string }[]) => {
    setOutboxState((q) => {
      const next = fn(q)
      if (next.length) outboxStore.set(name, next)
      else outboxStore.delete(name)
      return next
    })
  }
  // 会话名变了（同一个 ChatShell 实例被换绑到另一个会话，理论上不会发生，防御一下）：重新挂载那份
  const lastName = useRef(name)
  useEffect(() => {
    if (lastName.current === name) return
    lastName.current = name
    setOutboxState(outboxStore.get(name) || [])
  }, [name])
  // 兜底：忙完了就把排队区清空。按原文对账是主路，但转录里的用户消息可能被加工过
  //（命令展开、系统提醒拼进同一条），万一对不上，这条保证气泡不会永远挂着——
  //  Agent 闲下来就说明队列已经消化完了。
  const wasBusy = useRef(busy)
  useEffect(() => {
    if (wasBusy.current && !busy) setOutbox(() => [])
    wasBusy.current = busy
  }, [busy])
  useEffect(() => {
    setOutbox((q) => {
      if (!q.length) return q
      // 不按原文逐字比：实测发出去的和转录里的会差一两个字（开头少一个「你」），
      // 逐字比就对不上，同一句话一条已发、一条「排队中」并排挂着。去掉空白后互相包含就算同一句
      const norm = (v: string) => v.replace(/\s+/g, '')
      const said = messages.filter((m) => m.role === 'user').slice(-8)
        .map((m) => norm(m.blocks.map((b) => b.text || '').join('\n')))
      const same = (x: string) => { const n = norm(x); return said.some((v) => v === n || (n.length >= 4 && (v.includes(n) || (v.length >= 4 && n.includes(v))))) }
      const next = q.filter((x) => !same(x.text))
      return next.length === q.length ? q : next
    })
  }, [messages])

  const send = async () => {
    const text = input.trim()
    if (!text || sending) return
    setSending(true); setSendErr('')
    try {
      await api('POST', '/tasks/_/send', { sess: name, msg: text })
      setInput(''); atBottom.current = true
      setOutbox((q) => [...q, { id: q.length ? q[q.length - 1].id + 1 : 1, text }])
    }
    catch (e: any) { setSendErr(e.message) }
    finally { setSending(false) }
  }

  /**
   * 回车发送——但输入法正在组合时那记回车是「上屏候选词」，不是「发送」。
   *
   * 不挡的话：打一句中文按回车上屏，消息当场就发出去了，而且缺了还没上屏的那半截；
   * send() 清的是 React 态，浏览器随后把组合前的值写回 DOM，于是刚粘贴的那段文件路径
   * 又冒回输入框里（看着像"又粘了一遍"）。keyCode 229 是 Chrome 组合态的老写法，
   * 跟 isComposing 一起判，两代浏览器都盖住。
   */
  const onEnter = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const ne = e.nativeEvent as KeyboardEvent
    if (e.shiftKey || ne.isComposing || ne.keyCode === 229) return
    e.preventDefault()
    send()
  }

  /**
   * 中断生成，两级。
   *
   * 第一下发 Esc——Claude / Codex 都按它打断当前回合，也是最温和的一档（TUI 回到输入行，
   * 上下文还在）。但 Esc 只是「一个按键」：agent 卡在工具里的时候（跑了十分钟的 bash、
   * 等不到响应的请求），底下那个子进程根本没收到信号，按钮看着按下去了、agent 照跑——
   * 这就是「终止键不生效」。
   *
   * 所以 Esc 发过之后按钮就改口成 Ctrl+C（`.force`，红），再点一下把 ^C 打进 pty：
   * 走的是终端真正的中断路径（SIGINT / TUI 的强制打断），停得下 Esc 停不下的东西。
   *
   * 发完 ^C 锁 2.5 秒：Claude Code 里短时间内连按两次 Ctrl+C 是「退出整个 TUI」，
   * 手快点两下就不是中断而是把 agent 关了。
   */
  const [forceStop, setForceStop] = useState(false)
  const [stopCooling, setStopCooling] = useState(false)
  const coolTimer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => () => clearTimeout(coolTimer.current), [])
  // 停下来了就把这枚钮收回「Esc」那一档，下一轮生成重新从温和的开始
  useEffect(() => { if (!busy) { setForceStop(false); setStopCooling(false); clearTimeout(coolTimer.current) } }, [busy])

  const sendKeys = (keys: string[]) =>
    api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys }).catch((e: any) => setSendErr(e.message))

  const stop = () => {
    if (stopCooling) return
    if (!forceStop) { sendKeys(['Escape']); setForceStop(true); return }
    sendKeys(['C-c'])
    setStopCooling(true)
    coolTimer.current = setTimeout(() => setStopCooling(false), 2500)
  }

  const errMsg = sendErr || error
  // 工具行里的路径要能点开：用 context 送到最里层，不然要一路穿过工具注册表
  const actions = useMemo(() => ({ openFile: onOpenFile, tasks }), [onOpenFile, tasks])
  const hasStatus = !!(status && (status.mode || status.context || status.tasks || status.quota != null || status.branch || status.errors))

  // 状态条上每一格自己那件事。三件都落在这一层：这里既有会话名（能注入按键、能发消息），
  // 又有滚动容器（能定位到某条消息），再往上传反而绕。
  // 发一条斜杠命令给 agent（/model /compact /review /goal /approvals）：
  // TUI 自己弹选择框，PromptPanel 在页面里接住。状态条和「+」面板共用这一份。
  const sendCommand = (cmd: string) => { api('POST', '/tasks/_/send', { sess: name, msg: cmd }).catch(() => {}) }

  const statusActions: StatusActions = useMemo(() => ({
    onOpenGit,
    onJumpError: lastErrorId ? () => {
      const el = boxRef.current?.querySelector<HTMLElement>(`[data-msg-id="${CSS.escape(lastErrorId)}"]`)
      if (!el) return
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      // 闪一下：一屏里可能有好几条红，得指明是「这一条」
      el.classList.add('cc-flash')
      setTimeout(() => el.classList.remove('cc-flash'), 1200)
    } : undefined,
    onCompact: () => sendCommand('/compact'),
    onPickModel: () => sendCommand('/model'),
  }), [name, onOpenGit, lastErrorId])

  // 「+」面板要用的两件事：Shift+Tab 换权限模式，以及上传（走隐藏的 file input）。
  // 换模型 / 压缩上下文与状态条同一份实现（statusActions），面板只是换一种问法。
  // Shift+Tab 在 tmux 里叫 BTab；Claude Code 与 Codex 都用它轮换模式（codex 自己的提示
  // 就写着 "shift+tab to cycle"），所以这一条不分端。
  const cycleMode = () => { api('POST', `/sessions/${encodeURIComponent(name)}/keys`, { keys: ['BTab'] }).catch(() => {}) }

  return (
    <ChatActionsProvider value={actions}>
    <div style={{ display: 'flex', height: '100%', background: 'var(--bg-term)' }}>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', position: 'relative' }}
        onDragEnter={(e) => { e.preventDefault() }}
        onDragOver={(e) => {
          e.preventDefault()
          e.stopPropagation() // 对话区自己接住,别冒泡到 FileWorkspace 分栏层(否则会显示「分栏」提示并抢走 drop)
          const types = Array.from(e.dataTransfer.types || [])
          const isPath = types.includes('application/x-ttmux-path')
          e.dataTransfer.dropEffect = 'copy'
          setDropMode(types.includes(SESSION_MIME) ? 'session' : isPath ? 'path' : 'upload')
          if (!dragOver) setDragOver(true)
        }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false) }}
        onDrop={(e) => {
          e.preventDefault(); e.stopPropagation(); setDragOver(false) // 阻断冒泡:否则分栏层还会再把文件当「开文件」打开一次
          // 会话拖进来 = 告诉这个会话怎么跟对面说话（21 设计）。**必须排在下面那条前面**：
          // 这个处理器无条件接住一切，而 text/plain 一有值就会被当成路径插成 @引用——
          // 于是拖会话进来只会得到一个莫名其妙的 @xxx
          const drag = readDrag(e.dataTransfer)
          if (drag) { void introduce(drag); return }
          const p = e.dataTransfer.getData('application/x-ttmux-path') || e.dataTransfer.getData('text/plain')
          if (p && !e.dataTransfer.files?.length) { insertPath(p); return } // 从文件侧栏拖来的：插入 @路径
          if (e.dataTransfer?.files?.length) doUpload(e.dataTransfer.files) // 从系统拖来的：上传
        }}>
        {dragOver && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 30, pointerEvents: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--sp-2)', background: 'rgba(0,0,0,0.45)', border: `2px dashed ${accent}`, borderRadius: 'var(--r-card)', color: accent, fontSize: 'var(--fs-lg)', fontWeight: 600 }}>
            {dropMode === 'session' ? <TerminalIcon size={16} /> : dropMode === 'path' ? <FileTextIcon size={16} /> : <PaperclipIcon size={16} />}
            {dropMode === 'session' ? t('pair.dropHint') : dropMode === 'path' ? t('chat.dropInsertPath') : t('chat.dropUpload')}
          </div>
        )}
        <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex' }}>
          <div ref={boxRef} onScroll={onScroll} style={{ flex: 1, minHeight: 0, overflowY: 'auto', overscrollBehavior: 'contain', WebkitOverflowScrolling: 'touch', padding: '8px 12px' }}>
            {messages.length === 0 && !pending && <div style={{ color: 'var(--text-dim)', textAlign: 'center', marginTop: 30 }}>{emptyHint || t('chat.loadingTranscript')}</div>}
            {(hidden > 0 || hasEarlier) && (
              <div style={{ textAlign: 'center', margin: '2px 0 8px' }}>
                {/* 先放本地渲染窗口(手里已有的)，手里这些都放完了再回后端要更早的 */}
                <button type="button" className="tt-act" onClick={() => (hidden > 0 ? setLimit((l) => l + 200) : onLoadEarlier?.())}>
                  <ArrowUp size={12} />{hidden > 0 ? t('chat.loadEarlier', { count: hidden }) : t('chat.loadEarlierMore')}
                </button>
              </div>
            )}
            {live && (items
              ? items.map((it, i) => (it.kind === 'run'
                ? <ToolRun key={it.run.key} run={it.run} isLast={i === items.length - 1} />
                : renderMessage(it.msg, it.index)))
              : visible.map(renderMessage))}
            {/* 实时回显自带「正在生成」那颗脉冲点，扒不到东西时才退回省略号气泡——
                两个都画等于同一件事说两遍（见截图里那块重复） */}
            {outbox.map((q) => (
              <div key={q.id} className="cc-msg cc-queued" style={{ display: 'flex', justifyContent: 'flex-end', margin: 'var(--sp-1) 0' }}>
                <div style={{ maxWidth: '86%', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
                  <div style={{ background: accent, borderRadius: 'var(--r-card)', padding: 'var(--sp-2) var(--sp-3)', color: '#fff', opacity: .55, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{q.text}</div>
                  <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-dimmer)' }}>{t('chat.queued')}</span>
                </div>
              </div>
            ))}
            {live && (busy ? <LiveTail name={name} accent={accent} idle={pending} lastUser={lastUserText} /> : pending)}
          </div>
          {/* 「回到底部」已并进下方状态条（带未读数）；状态条一个字段都没有时（刚进页面、
              转录还没扫出状态）才退回这颗悬浮钮，免得离底了没处点。 */}
          {showJump && !hasStatus && (
            <button onClick={jump} title={t('chat.jumpToBottom')}
              style={{ position: 'absolute', right: 14, bottom: 12, width: 34, height: 34, borderRadius: '50%', border: '1px solid var(--border)', background: 'var(--bg-container)', color: accent, cursor: 'pointer', boxShadow: 'var(--card-hover-shadow)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <ArrowToBottom size={16} />
            </button>
          )}
        </div>
        {/* 状态条在选择框之上：选择框要人立刻动手，得离输入框更近 */}
        {(hasStatus || unread > 0) && (
          <StatusBar status={status || {}} accent={accent} unread={unread} onJump={jump} actions={statusActions} />
        )}
        {/* 交互式选择框（权限确认/选项菜单）：检测到才显示，可点选 */}
        <PromptPanel name={name} accent={accent} />
        {errMsg && <div style={{ color: '#f85149', fontSize: 12, padding: '2px 12px' }}>{errMsg}</div>}
        {/* 输入卡：与项目页「下任务」同一套词汇（.tt-composer / .tt-cbar / .tt-pill / .tt-send）。
            手机和桌面是同一棵树，差的只有文本框最多长几行——两套 JSX 各写一遍的结果是
            改一处忘一处（回车不挡输入法那个 bug 就在两份里各躺了一份）。
            语音钮也收进这条控制条：桌面端原来是 bottom:54 的悬浮麦克风，输入框一涨到
            两行就压住发送键，点上去变成录音。 */}
        <div style={{ padding: 10, borderTop: '1px solid var(--border)' }}>
          <input ref={fileRef} type="file" multiple style={{ display: 'none' }}
            onChange={(e) => { const fs = e.target.files ? Array.from(e.target.files) : []; e.target.value = ''; if (fs.length) doUpload(fs) }} />
          <div className="tt-composer">
            <Input.TextArea
              value={input} onChange={(e) => setInput(e.target.value)}
              autoSize={{ minRows: 1, maxRows: isMobile ? 6 : 8 }} placeholder={placeholder}
              variant="borderless"
              onPressEnter={onEnter}
              onPaste={onPaste}
            />
            <div className="tt-cbar">
              <span className="tt-cgrp">
                {/* 「+」：带什么进去（文件）、这一轮怎么干（权限模式 / 模型 / 压缩上下文）。
                    输入行上只留最高频的两件事：说话和发送 */}
                <ComposerPlus name={name} agent={agent} status={status} uploading={uploading} onMouseDown={noBlur}
                  onFiles={() => fileRef.current?.click()} onCycleMode={cycleMode}
                  onCommand={sendCommand} onOpenGit={onOpenGit} />
                {agent && (
                  <span className="tt-pill on" aria-label={agent === 'claude' ? 'Claude' : 'Codex'}>
                    <AgentLogo kind={agent} size={12} />{agent === 'claude' ? 'Claude' : 'Codex'}
                  </span>
                )}
              </span>
              <span className="tt-cend">
                {/* 话筒贴着发送键：pill 是「带什么」，话筒是「怎么说」，分开放（22 设计 §3.3） */}
                <VoiceInput inline hotkey={live} accent={accent} onResult={appendText} />
                {/* agent 在跑、又没在打字：那枚圆钮就是「停止」；打了字它又是「发送」（可以边跑边排队）。
                    不另摆一枚「停止」pill——同一个位置一钮两用，和别的对话产品一个习惯 */}
                {busy && !input.trim() ? (
                  // 同一枚钮两档：Esc → Ctrl+C。图标不换（同一件事，AGENTS.md「同一动作同一图标」），
                  // 换的是颜色和名字，让人知道下一下按出去的分量不一样。
                  <button type="button" className={`tt-send stop${forceStop ? ' force' : ''}`}
                    aria-label={forceStop ? t('chat.forceStop') : t('chat.stop')}
                    title={forceStop ? t('chat.forceStopTitle') : t('chat.stopTitle')}
                    disabled={stopCooling}
                    onMouseDown={noBlur} onClick={stop}>
                    <StopIcon size={12} />
                  </button>
                ) : (
                  <button type="button" className="tt-send" aria-label={t('common.send')} title={t('common.send')}
                    disabled={sending || !input.trim()} onMouseDown={noBlur} onClick={send}>
                    <ArrowUp size={16} />
                  </button>
                )}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
    </ChatActionsProvider>
  )
}
