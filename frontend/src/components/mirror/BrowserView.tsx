// 浏览器镜像页：把后端全局 Chrome 的画面实时渲染到 <img>，可选「接管」转发输入。
// 协议见 backend/browser/screencast.go：
//   收 {type:'frame', data, w, h} | {type:'pong', t} | {type:'error', msg}
//   发 {type:'nav', url} | {type:'ping', t} | {type:'mouse'|'wheel'|'key', ...}（输入仅 control=1 生效）
import { useEffect, useRef, useState } from 'react'
import { nodeWs, nodeWsHostPath } from '../cluster/node-url'
import { ConfigProvider, Dropdown, App as AntApp } from 'antd'
import type { MenuProps } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { usePreferences, savePreferences } from '../../preferences'
import { connect, type DuplexTransport } from '../../p2p/transport'
import {
  BotIcon, ChevronLeft, ChevronRight, CodeIcon, DeviceIcon, ExitFullscreenIcon, FullscreenIcon,
  GlobeIcon, HomeIcon, OpenInIcon, PlusIcon, RefreshIcon, RotateScreenIcon, TabsIcon, UserIcon,
} from '../../icons'
import {
  fmtRate, IconBtn, MirrorChrome, MirrorMenu, Omnibox, StatusChip, StreamControl, useFullscreen, useShelf, type Quality,
} from './mirror'
import { TabSheet, TabStrip, type TabInfo } from './browser-tabs'

// 清晰度档位与手机页共用（mirror.tsx 的 QUALITY_OPTS），这里只有存盘的 key 不同
const QKEY = 'ttmux.browser.quality'
const RKEY = 'ttmux.browser.rotate' // 画面旋转角度（0/90/180/270），手机竖屏看横屏用

// 手机模式设备档（栏目级配置，存 localStorage）。空 key = 桌面（不模拟）。
// 维度是 CSS 像素视口，dpr 决定渲染像素密度；ua 让做 UA 嗅探的站点切到移动版。
// 后端 screencast.go 按 ?mobile/mw/mh/dpr/ua 下发 CDP Emulation 覆盖。
type Device = { key: string; nameKey: string; w: number; h: number; dpr: number; ua: string }
const DKEY = 'ttmux.browser.device'
const IOS_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
const DEVICES: Device[] = [
  { key: 'iphone', nameKey: 'browser.device.iphone', w: 390, h: 844, dpr: 3, ua: IOS_UA },
  { key: 'pixel', nameKey: 'browser.device.pixel', w: 412, h: 915, dpr: 2.625,
    ua: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36' },
  { key: 'ipad', nameKey: 'browser.device.ipad', w: 820, h: 1180, dpr: 2,
    ua: 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' },
]

// 地址栏自适应 http/https：本机/内网地址默认 http，其余默认 https。
// 已带 scheme 的原样返回；避免内网 IP / localhost 被强转 https 连不上。
function smartUrl(input: string): string {
  const s = input.trim()
  if (/^[a-z]+:\/\//i.test(s)) return s            // 已有 http(s):// 等协议，尊重用户
  const host = s.split('/')[0].split(':')[0].toLowerCase()
  const local =
    host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0' || host === '::1' ||
    host.endsWith('.local') ||                       // .local 局域网域名（mDNS）
    /^10\./.test(host) ||                            // 10.0.0.0/8
    /^192\.168\./.test(host) ||                      // 192.168.0.0/16
    /^172\.(1[6-9]|2\d|3[01])\./.test(host)          // 172.16.0.0/12
  return (local ? 'http://' : 'https://') + s
}

// Chrome 的 /json(标签页)顺序不稳定：激活/聚焦/新开都会重排，直接用它每 3s 一刷新
// tab 就乱跳，新开的还常被排到最前(左侧冒出来)。这里维持一份稳定的客户端顺序：
// 已有 tab 保持原位(仅更新标题/url)，真正新开的追加到末尾(右侧)，消失的移除。
function mergeTabs(prev: TabInfo[], incoming: TabInfo[]): TabInfo[] {
  const byId = new Map(incoming.map((t) => [t.id, t]))
  const out: TabInfo[] = []
  for (const p of prev) {            // 1) 旧 tab 按原顺序保留，取最新标题/url
    const cur = byId.get(p.id)
    if (cur) { out.push(cur); byId.delete(p.id) }
  }
  for (const t of incoming) {        // 2) 新 tab 追加到右侧(按后端相对顺序)
    if (byId.has(t.id)) out.push(t)
  }
  return out
}

export default function BrowserView() {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  // 收纳档位按**容器**宽度算（不是窗口）：这一页会被塞进分栏，那时窗口很宽而容器很窄。
  // ≥1100 全平铺 / 900–1100 收指标 / <900 等同手机形态（设计 17 §5.5）
  const [shelf, shelfRef] = useShelf()
  const [tabsOpen, setTabsOpen] = useState(false)
  const [prefs] = usePreferences()
  const imgRef = useRef<HTMLImageElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  // 镜像收发底层：p2p 时是 media PC 上的不可靠 DataChannel，回退时是 /api/browser/stream 的 WS。
  // 二进制帧解析/ack/ping/自适应逻辑不感知底层（DuplexTransport ≈ WebSocket）。
  const tpRef = useRef<DuplexTransport | null>(null)
  const sizeRef = useRef({ w: 1280, h: 800 }) // 画面内在尺寸（CDP 设备像素）
  const control = true // 始终接管（鼠标/键盘转发给 Chrome）
  const controlRef = useRef(true)
  const [connected, setConnected] = useState(false)
  const [healthMsg, setHealthMsg] = useState('') // 连不上时的原因（后端 /browser/health 的 error）
  const [url, setUrl] = useState('')
  const addrFocused = useRef(false) // 地址栏聚焦时不被轮询回写覆盖
  // 标签页（复用同一台 Chrome）
  const [tabs, setTabs] = useState<TabInfo[]>([])
  const [pinnedTabs, setPinnedTabs] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem('roam.browser.pinnedTabs') || '[]')) } catch { return new Set() }
  })
  useEffect(() => {
    try { localStorage.setItem('roam.browser.pinnedTabs', JSON.stringify([...pinnedTabs])) } catch { /* 当前页仍可固定 */ }
  }, [pinnedTabs])
  const displayTabs = [...tabs.filter((tb) => pinnedTabs.has(tb.id)), ...tabs.filter((tb) => !pinnedTabs.has(tb.id))]
  const togglePin = (id: string) => setPinnedTabs((current) => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })
  const tabsRef = useRef<TabInfo[]>([]) // 供 ws.onmessage 等闭包读到最新标签集（识别新开的那个）
  const [target, setTarget] = useState('') // 当前镜像的标签页 id；空 = 第一个
  // 导航起始页地址（后端 /api/me 提供，形如 http://127.0.0.1:<port>/home）；
  // 新标签默认开它、可点「主页」回到它。默认值按当前端口兜底。
  const [home, setHome] = useState(`${location.protocol}//127.0.0.1:${location.port || '8080'}/home`)
  // 栏目级清晰度配置（持久化）；默认自适应
  const [quality, setQuality] = useState<Quality>(() => {
    const s = prefs.browserQuality || localStorage.getItem(QKEY)
    if (s == null || s === 'auto') return 'auto'
    return Number(s) || 'auto'
  })
  const [levelName, setLevelName] = useState('') // 服务端当前生效档位名（自适应时显示）
  // 手机模式：空 = 桌面；否则模拟对应机型视口（持久化）。切换不重连，发 emulate 消息现场切换
  const [device, setDevice] = useState<string>(() => prefs.browserDevice || localStorage.getItem(DKEY) || '')
  const deviceRef = useRef(device) // 供 ws.onopen 等回调读最新设备态
  // 画面旋转：0/90/180/270，持久化。手机竖屏看横屏浏览器时转 90°
  const [rotation, setRotation] = useState<number>(() => Number(prefs.browserRotate || localStorage.getItem(RKEY)) || 0)
  const [stage, setStage] = useState({ w: 0, h: 0 }) // 舞台尺寸，旋转时需据此对调 <img> 盒子宽高
  const [frame, setFrame] = useState({ w: 0, h: 0 }) // 远端画面尺寸（帧自带），只用于告诉用户「现在传的是多大一张图」
  // 桌面档的固定视口：设置页「浏览器 · 窗口大小」那一格。远端就按这个尺寸渲染，
  // 与观看区多宽无关。默认 1920×1080。
  const [deskVp, setDeskVp] = useState({ w: 1920, h: 1080 })
  const deskVpRef = useRef(deskVp)
  // 实时指标
  const [latency, setLatency] = useState<number | null>(null)
  const [bw, setBw] = useState(0)   // 字节/秒
  const [fps, setFps] = useState(0)
  const bytesRef = useRef(0)
  const framesRef = useRef(0)
  // 点击涟漪（乐观反馈，不等帧回来）+ 移动/滚轮节流
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([])
  const ripIdRef = useRef(0)
  const lastMoveRef = useRef(0)
  const dragRef = useRef({ x: 0, y: 0, active: false, moved: false }) // 拖动框选：起点(页面坐标)+是否真的移动过
  const wheelRef = useRef({ x: 0, y: 0, dx: 0, dy: 0, m: 0, timer: 0 as any })
  const touchRef = useRef({ x: 0, y: 0, t: 0, moved: false })
  const lastEmuRef = useRef('')       // 上次已发的 emulate 载荷（去重：载荷没变绝不重发 → 不重设视口 → 不跳）
  // 中文等输入法（IME）输入：普通 div 持焦时浏览器不会启动输入法组合，敲拼音只会落下
  // 原始字母。用一个视觉隐藏的 textarea 承接焦点与组合过程，组合结束后把整段文本经
  // 现有 char 消息发往远端（后端 Input.insertText 支持多字符）。textarea 定位在最近
  // 一次点击处，让候选词窗口出现在输入位置附近而不是面板角落。
  const imeRef = useRef<HTMLTextAreaElement>(null)
  const composingRef = useRef(false)
  const [imePos, setImePos] = useState({ x: 8, y: 8 })
  // 智能体模式 / 手动模式：两个持久状态，不是"暂停时才冒出来的临时按钮"。智能体模式下
  // 后端广播 {type:'active'} 会自动切到 agent 正在操作的标签；用户在画面里点击/打字
  // 视为接管，自动切到手动模式。切回智能体模式只能靠主动点按钮——不设空闲自动恢复，
  // 模式要长期保持，不能自己漂移回去（人正盯着一个 agent 没打算离开的页面时尤其如此）。
  const [followPaused, setFollowPaused] = useState(false)
  const followPausedRef = useRef(false)

  const fs = useFullscreen(rootRef)

  // control 开关用 ref 同步，供事件回调读取最新值
  useEffect(() => { controlRef.current = control }, [control])
  useEffect(() => { deviceRef.current = device }, [device])
  useEffect(() => { tabsRef.current = tabs }, [tabs])

  // 跟踪舞台尺寸：旋转 90/270 时 <img> 盒子宽高要对调，才能铺满竖屏
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const measure = () => setStage({ w: el.clientWidth, h: el.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // 旋转：每次 +90°，循环 0→90→180→270→0，持久化
  const rotate = () => setRotation((r) => { const n = (r + 90) % 360; savePreferences({ browserRotate: String(n) }); try { localStorage.setItem(RKEY, String(n)) } catch {}; return n })
  const rotated = rotation === 90 || rotation === 270

  // 取导航起始页地址（后端按 TTMUX_HOME_BIND 算出）
  useEffect(() => {
    api('GET', '/me').then((r) => { if (r?.data?.browserHome) setHome(r.data.browserHome) }).catch(() => {})
  }, [])

  // 桌面视口取自 Chrome 启动配置的「窗口大小」("1920,1080")：设置页改了那一格，这里跟着变。
  useEffect(() => {
    api('GET', '/browser/config').then((r) => {
      const m = /^\s*(\d{3,5})\s*[,x×]\s*(\d{3,5})\s*$/.exec(r?.data?.windowSize || '')
      if (!m) return
      const vp = { w: Number(m[1]), h: Number(m[2]) }
      deskVpRef.current = vp
      setDeskVp(vp)
      if (!deviceRef.current) sendEmulate() // 桌面档才需要现场改视口
    }).catch(() => {})
  }, [])

  // Chrome 有些「页」压根关不掉——它自己的界面（chrome://*.top-chrome/）就是这样：
  // /json/close 照收不误，那一行下一次轮询又回来。后端已经把认得出来的挡在外面，
  // 万一还是漏进来一条，用户按下关闭时就记在这里：关不掉，至少让它从这条标签条上消失。
  const dismissedRef = useRef<Set<string>>(new Set())
  const visibleTabs = (list: TabInfo[]) => list.filter((x) => !dismissedRef.current.has(x.id))

  // 拉取标签页列表（每 3s 刷新，反映 agent 自己开的标签页/标题变化）
  const loadTabs = async () => {
    try {
      const r = await api('GET', '/browser/tabs')
      const list: TabInfo[] = visibleTabs(r?.data || [])
      setTabs((prev) => mergeTabs(prev, list)) // 稳定顺序，避免后端重排导致 tab 乱跳
      // 当前 target 已不存在 → 切到第一个
      setTarget((t) => (list.some((x) => x.id === t) ? t : (list[0]?.id || '')))
    } catch {}
  }
  useEffect(() => {
    loadTabs()
    const t = setInterval(loadTabs, 3000)
    return () => clearInterval(t)
  }, [])

  const newTab = async () => {
    try {
      const known = new Set(tabs.map((t) => t.id)) // 记下创建前的 id，用于定位新开的那个
      await api('POST', '/browser/tabs', { url: home }) // 新标签默认开导航起始页
      const r = await api('GET', '/browser/tabs')
      const list: TabInfo[] = visibleTabs(r?.data || [])
      setTabs((prev) => mergeTabs(prev, list))
      const fresh = list.find((t) => !known.has(t.id)) // 真正新增的(在右侧)，而非后端顺序的末位
      setTarget(fresh?.id || list[list.length - 1]?.id || '')
    } catch (e: any) { message.error(e.message) }
  }
  const closeTabs = async (ids: string[]) => {
    await Promise.all(ids.map(async (id) => {
      try {
        await api('DELETE', `/browser/tabs/${id}`)
      } catch (e: any) {
        // Chrome 自身的页面拒绝关闭时，仅从镜像标签条隐藏。
        if (e?.apiError?.code !== 'not_closable') { message.error(e.message); return }
        dismissedRef.current.add(id)
        message.info(t('browser.tabHidden'))
      }
    }))
    await loadTabs()
  }
  const closeTab = (id: string) => closeTabs([id])

  // 地址栏跟随当前标签页真实 URL（聚焦编辑时不覆盖；about:blank 显示为空）
  useEffect(() => {
    if (addrFocused.current) return
    const t = tabs.find((x) => x.id === target)
    if (t) setUrl(t.url === 'about:blank' ? '' : t.url)
  }, [target, tabs])

  // 切到手动模式：人正在手动操作（切标签/点镜像页面），此时后端广播的 active 不该把
  // 面板拽走。只能靠主动点"智能体模式"按钮切回去，不会自己超时恢复。
  const pauseFollow = () => {
    followPausedRef.current = true
    setFollowPaused(true)
  }
  const resumeFollow = () => {
    followPausedRef.current = false
    setFollowPaused(false)
  }

  // 切换标签：镜像该 tab + 在 Chrome 里把它前置（让 agent 前台焦点一致）
  const switchTab = (id: string) => {
    pauseFollow() // 人手动选的，别被下一条 active 广播立刻拽回去
    setTarget(id)
    api('POST', `/browser/tabs/${id}/activate`).catch(() => {})
  }

  // 被镜像页打开了新窗口/标签（后端 windowOpen 事件触发）：找出新出现的那个并把镜像切过去。
  // 新 target 可能略晚于事件才出现在 /json 列表里，故短重试几次。
  const followNewTab = async () => {
    const known = new Set(tabsRef.current.map((t) => t.id))
    for (let i = 0; i < 8; i++) {
      try {
        const r = await api('GET', '/browser/tabs')
        const list: TabInfo[] = visibleTabs(r?.data || [])
        const fresh = list.find((t) => !known.has(t.id))
        if (fresh) {
          setTabs((prev) => mergeTabs(prev, list))
          switchTab(fresh.id) // 切镜像 + 前置，画面随之跳到新标签
          return
        }
        setTabs((prev) => mergeTabs(prev, list))
      } catch {}
      await new Promise((res) => setTimeout(res, 200))
    }
  }

  const send = (o: any) => {
    // DuplexTransport.send 对 p2p 自带 open-before-send 排队、对 frp 内部判 readyState，
    // 这里直接发即可（未连时 frp 分支静默丢弃，与迁移前 ws.readyState 守卫等价）。
    tpRef.current?.send(JSON.stringify(o))
  }

  // 作用于当前标签的导航控制
  const act = async (suffix: string, body?: any) => {
    if (!target) return
    try {
      await api('POST', `/browser/tabs/${target}/${suffix}`, body)
      send({ type: 'refresh' })
    }
    catch (e: any) { message.error(e.message) }
  }

  // 当前设备 → emulate 消息载荷。
  //
  // 桌面档是【固定视口】(设置页「浏览器 · 窗口大小」，默认 1920×1080)，与观看区多大无关。
  // 从前这里按观看区宽高比算视口下发，于是拖动分隔条 = 给远端换分辨率：页面当场重排，
  // 响应式站点的栏数、折行、菜单收纳全跟着变——想看的是同一个页面，看到的却是另一个版式。
  // 现在拖动只改本地怎么把这一帧塞进观看区（object-fit: contain，装不满的那一维留黑边）。
  //
  // 为什么不干脆不覆盖、用 Chrome 窗口自己的尺寸？实测这台无头 Chrome 的原生视口是
  // 1280×1775（竖的）——--force-device-scale-factor=2 叠上 --start-fullscreen 与 ozone
  // 的屏幕尺寸覆盖，一台「全屏浏览器」就长成了竖屏。所以显式钉一个横屏尺寸。
  // dpr 用 1：传输分辨率由画质档的 maxWidth/maxHeight 管（见后端 ladder），1920 的画面
  // 落到窄窗格里本身就是超采样，不必再让远端多渲一倍像素。
  const emulatePayload = () => {
    const dev = DEVICES.find((d) => d.key === deviceRef.current)
    if (dev) return { type: 'emulate', mobile: true, mw: dev.w, mh: dev.h, dpr: dev.dpr, ua: dev.ua }
    const { w, h } = deskVpRef.current
    return { type: 'emulate', mobile: false, mw: w, mh: h, dpr: 1 }
  }

  // 发 emulate 但【去重】：载荷和上次一样就不发。重设 device metrics 会让后端产一个「视口尚未稳」
  // 的畸形首帧(object-fit letterbox 后就是画面一跳)，所以观看区尺寸抖来抖去、只要 settle 回同一个
  // 值，就不该重设视口。移动端工具栏随滚动显隐、窄屏顶栏换行会让 stage 尺寸每秒抖动 → 不去重就连
  // 标清都持续跳。newSession=true 时强制发一次（新连接的后端会话还没视口覆盖）。
  const sendEmulate = (newSession = false) => {
    const p = emulatePayload()
    const key = JSON.stringify(p)
    if (!newSession && key === lastEmuRef.current) return
    lastEmuRef.current = key
    send(p)
  }

  // control / target 变化才重连；画质切换【不重连】(连上后发 quality 消息，见下面 changeQuality)，
  // 设备/尺寸切换也不重连(发 emulate 消息)。重连会重设 device metrics、首帧畸形 → 画面跳/页面忽大小。
  useEffect(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const params = new URLSearchParams()
    if (control) params.set('control', '1')
    if (quality === 'auto') params.set('auto', '1') // 仅首连/换 target 时用来定初始档；之后靠消息切
    else params.set('q', String(quality))
    if (target) params.set('target', target)
    // 通用传输 Phase 1b：镜像走 media PC 的不可靠 DataChannel；media 未连/P2P 不可用 → 回退
    // 到原 /api/browser/stream WS（frpUrl），行为与迁移前逐字节一致。p2p 分支把 query 里的
    // params 经 init 握手带给后端（原本靠 WS query 传）。
    const frpUrl = nodeWs(`/browser/stream?${params}`)
    const tp = connect('screencast', { frpUrl, initParams: Object.fromEntries(params) })
    tpRef.current = tp
    lastEmuRef.current = '' // 新连接：后端会话尚无视口覆盖，onopen 必须强制发一次 emulate
    let objURL: string | null = null
    // 连上（frp=WS open / p2p=DataChannel open）即同步当前设备/尺寸，语义等价迁移前 ws.onopen。
    tp.onopen = () => { setConnected(true); setHealthMsg(''); sendEmulate(true) }
    tp.onmessage = (data) => {
      // 二进制 = 一帧：[w:u16][h:u16][seq:u16][jpeg...]；显示后回 ack 归还信用
      if (typeof data !== 'string') {
        if (!imgRef.current) return
        const buf = data as ArrayBuffer
        const dv = new DataView(buf)
        const w = dv.getUint16(0, true), h = dv.getUint16(2, true), seq = dv.getUint16(4, true)
        sizeRef.current = { w: w || 1280, h: h || 800 }
        // 尺寸变了才 setState（每帧都设会把整棵树重渲染成一秒几十次）
        setFrame((f) => (f.w === sizeRef.current.w && f.h === sizeRef.current.h ? f : { ...sizeRef.current }))
        bytesRef.current += buf.byteLength
        framesRef.current++
        if (objURL) URL.revokeObjectURL(objURL)
        objURL = URL.createObjectURL(new Blob([new Uint8Array(buf, 6)], { type: 'image/jpeg' }))
        imgRef.current.src = objURL
        tp.send(JSON.stringify({ type: 'ack', n: seq }))
        return
      }
      const msg = JSON.parse(data)
      if (msg.type === 'error') { message.error(msg.msg); return }
      if (msg.type === 'pong') { setLatency(Math.round(performance.now() - msg.t)); return }
      if (msg.type === 'level') { setLevelName(msg.name || ''); return }
      // 被镜像页打开了新窗口/标签 → 镜像跟过去（点 target=_blank 链接、window.open 等）
      if (msg.type === 'newtab') { followNewTab(); return }
      // 后端广播的当前前台标签（agent 经 chrome-cli 操作、或别处经 REST 前置）：
      // 未暂停跟随时自动切过去；顺手拿它带的标签列表刷新标题/地址，比 3s 轮询更及时。
      if (msg.type === 'active') {
        if (Array.isArray(msg.tabs)) setTabs((prev) => mergeTabs(prev, visibleTabs(msg.tabs)))
        if (!followPausedRef.current && msg.id && msg.id !== target) setTarget(msg.id)
        return
      }
      // 复制选区回包：把远端页面当前选区文本写进本设备剪贴板（需安全上下文，HTTPS 默认已开）
      if (msg.type === 'copied') {
        const text: string = msg.text || ''
        if (!text) { message.info(t('browser.noSelection')); return }
        // 选区已存进后端「浏览器内部剪贴板」，Ctrl+V 必能用；这里顺手写本机剪贴板（成功则外部也能粘，失败忽略）
        navigator.clipboard?.writeText?.(text).catch(() => {})
        message.success(t('browser.copied'))
        return
      }
    }
    tp.onclose = () => {
      setConnected(false)
      // 连不上时问后端为什么（Chrome 启动失败原因），显示给用户而非干瞪黑屏
      api('GET', '/browser/health').then((r) => { if (!r?.data?.alive) setHealthMsg(r?.data?.error || '') }).catch(() => {})
    }
    // 每秒打一次 ping 测 RTT，并结算带宽/帧率
    const ping = setInterval(() => { tp.send(JSON.stringify({ type: 'ping', t: performance.now() })) }, 1000)
    const meter = setInterval(() => {
      setBw(bytesRef.current); setFps(framesRef.current)
      bytesRef.current = 0; framesRef.current = 0
    }, 1000)
    return () => {
      clearInterval(ping); clearInterval(meter)
      if (objURL) URL.revokeObjectURL(objURL)
      tp.onmessage = () => {}; tp.onclose = () => {} // 卸载后忽略在途回调
      tp.close()
      if (tpRef.current === tp) tpRef.current = null
    }
  }, [control, target]) // 画质/device 切换都不重连，靠 quality / emulate 消息现场切换

  // 设备切换：在现有连接上发 emulate（同一 CDP 会话 set/clear），不重连。
  // 观看区尺寸【不在依赖里】——远端视口不跟着窗格走，拖分隔条不该动远端一根汗毛。
  useEffect(() => { sendEmulate() }, [device])

  const navigate = () => {
    if (!url) return
    act('navigate', { url: smartUrl(url) })
  }

  // 切画质：持久化 + 在现有连接上发消息现场切档（不重连 → 不重设视口 → 不跳）
  const changeQuality = (v: Quality) => {
    setQuality(v); savePreferences({ browserQuality: String(v) }); try { localStorage.setItem(QKEY, String(v)) } catch {}
    send(v === 'auto' ? { type: 'quality', auto: true } : { type: 'quality', auto: false, q: v })
  }
  const changeDevice = (v: string) => { setDevice(v); savePreferences({ browserDevice: v }); try { localStorage.setItem(DKEY, v) } catch {} }

  // F12：打开 Chrome 自带 DevTools（经后端反代 /api/browser/cdp/*，直连该 tab 的 CDP）。
  // https 页面必须用 wss= 参数，否则 DevTools 起 ws:// 连接会被混合内容拦截。
  const openDevtools = () => {
    if (!target) { message.warning(t('browser.noDebuggableTab')); return }
    const wsParam = location.protocol === 'https:' ? 'wss' : 'ws'
    const u = `${location.origin}/api/browser/cdp/devtools/inspector.html`
      + `?${wsParam}=${nodeWsHostPath(`/browser/cdp/devtools/page/${target}`)}`
    window.open(u, `ttmux-devtools-${target}`, 'width=1100,height=720')
  }

  // 甩给宿主机真实浏览器打开当前地址：镜像 Chrome 终究是后端管的替身，
  // WSL 下后端会转去唤起 Windows 侧浏览器（见 backend/browser/external.go）。
  const openExternal = async () => {
    if (!url) { message.warning(t('browser.openExternalNoUrl')); return }
    try { await api('POST', '/browser/open-external', { url }) }
    catch (e: any) { message.error(e.message || t('browser.openExternalFailed')) }
  }

  // 把鼠标坐标换算成 CDP 期望的页面 CSS 像素坐标。
  // 关键：<img> 用 object-fit: contain（居中留黑边）且可能被旋转，
  // 所以先把屏幕点平移到舞台中心相对、再逆旋转回画面坐标系，最后扣黑边按真实显示区缩放。
  const mapClientXY = (clientX: number, clientY: number) => {
    const r = stageRef.current!.getBoundingClientRect()
    const img = imgRef.current
    const nw = sizeRef.current.w, nh = sizeRef.current.h
    // 必须使用 <img> 变换前的真实布局盒，而不是 stage 尺寸。移动端工具栏显隐后，stage 高会变，
    // 但图片为了保持缩放比仍按 vp 纵横比维持旧高度并居中裁切；继续拿 stage.h 换算会让点击、
    // 拖选和触摸坐标整体上下偏移。clientWidth/Height 不受 rotate transform 影响，正好用于先在
    // 屏幕中心逆旋转，再映射回图片内部坐标。
    const boxW = img?.clientWidth || (rotated ? r.height : r.width)
    const boxH = img?.clientHeight || (rotated ? r.width : r.height)
    const scale = Math.min(boxW / nw, boxH / nh) // contain 缩放比
    const dispW = nw * scale, dispH = nh * scale // 画面实际显示尺寸
    // 黑边：横向居中（左右各一半），纵向贴上沿（全在下面）——必须跟 <img> 的 object-position 一致，
    // 否则点击落点会整体偏上/偏下半条黑边。
    const padX = (boxW - dispW) / 2, padY = 0
    // 屏幕点 → 舞台中心相对
    const dx = clientX - (r.left + r.width / 2)
    const dy = clientY - (r.top + r.height / 2)
    // 逆旋转（R(-θ)）还原到未旋转的画面盒子坐标
    const rad = (rotation * Math.PI) / 180
    const cos = Math.cos(rad), sin = Math.sin(rad)
    const lx = dx * cos + dy * sin + boxW / 2
    const ly = -dx * sin + dy * cos + boxH / 2
    const fx = Math.max(0, Math.min(1, (lx - padX) / dispW))
    const fy = Math.max(0, Math.min(1, (ly - padY) / dispH))
    // 缩放到 CDP 页面坐标系（设备 CSS 像素）
    return { x: fx * nw, y: fy * nh }
  }
  const mapXY = (e: React.MouseEvent) => mapClientXY(e.clientX, e.clientY)

  // CDP 修饰键位掩码：Alt=1 Ctrl=2 Meta=4 Shift=8
  const mods = (e: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) =>
    (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0)

  // 乐观点击反馈：在点击处画一圈扩散涟漪，不等画面回来 → 主观"秒响应"
  const addRipple = (e: React.MouseEvent) => {
    const st = stageRef.current
    if (!st) return
    const r = st.getBoundingClientRect()
    const id = ++ripIdRef.current
    setRipples((rs) => [...rs, { id, x: e.clientX - r.left, y: e.clientY - r.top }])
    setTimeout(() => setRipples((rs) => rs.filter((p) => p.id !== id)), 450)
  }
  const onMouse = (sub: string) => (e: React.MouseEvent) => {
    if (!controlRef.current) return
    e.preventDefault()
    if (sub === 'down') pauseFollow() // 人在直接操作镜像页面，别被 agent 的 active 广播拽走
    const pt = mapXY(e)
    if (sub === 'down') {
      const st = stageRef.current
      if (st) {
        const r = st.getBoundingClientRect()
        setImePos({ x: e.clientX - r.left, y: e.clientY - r.top })
      }
      imeRef.current?.focus({ preventScroll: true }) // 焦点落在隐藏 textarea 上，输入法才会启动组合
      addRipple(e)
      dragRef.current = { x: pt.x, y: pt.y, active: true, moved: false } // 记拖动起点
    } // 拿焦点 + 涟漪 + 记拖动起点
    send({ type: 'mouse', sub, x: pt.x, y: pt.y, button: 'left', buttons: sub === 'down' ? 1 : 0, modifiers: mods(e) })
    if (sub === 'up') {
      const d = dragRef.current
      if (d.active && d.moved) send({ type: 'select', x1: d.x, y1: d.y, x2: pt.x, y2: pt.y }) // 拖动结束 → 定稿选区
      d.active = false
    }
  }
  // 兜底：在 <img> 范围外松开鼠标时，浏览器把 mouseup 派给鼠标当前所在的元素而不是 <img>
  // 本身，导致 onMouse('up') 收不到事件 —— 拖拽框选/远端滑块会一直卡在"按下"态。用 window
  // 级监听兜底；靠 dragRef.active 去重（同一次释放若已被 <img> 自身的 onMouseUp 处理过，
  // active 会先被置 false，这里直接跳过，不会重复发送)。
  useEffect(() => {
    const onWindowMouseUp = (e: MouseEvent) => {
      const d = dragRef.current
      if (!d.active) return
      d.active = false
      if (!controlRef.current) return
      const pt = mapClientXY(e.clientX, e.clientY)
      send({ type: 'mouse', sub: 'up', x: pt.x, y: pt.y, button: 'left', buttons: 0, modifiers: mods(e) })
      if (d.moved) send({ type: 'select', x1: d.x, y1: d.y, x2: pt.x, y2: pt.y })
    }
    window.addEventListener('mouseup', onWindowMouseUp)
    return () => window.removeEventListener('mouseup', onWindowMouseUp)
  }, [rotation])

  // 移动节流：低带宽下高频 move 会挤占上行，限到 ~45ms 一发
  const onMove = (e: React.MouseEvent) => {
    if (!controlRef.current) return
    const now = performance.now()
    if (now - lastMoveRef.current < 45) return
    lastMoveRef.current = now
    const pt = mapXY(e)
    // buttons 透传：移动时带住左键 Chrome 才认作拖动（拖滑块/画布/框选都靠它）
    send({ type: 'mouse', sub: 'move', x: pt.x, y: pt.y, buttons: e.buttons, modifiers: mods(e) })
    // 按住左键拖动 → 实时框选（headless 合成拖选无效，发起止坐标让远端用 caretRangeFromPoint 建 Range）
    const d = dragRef.current
    if (d.active && (e.buttons & 1) && Math.abs(pt.x - d.x) + Math.abs(pt.y - d.y) > 3) {
      d.moved = true
      send({ type: 'select', x1: d.x, y1: d.y, x2: pt.x, y2: pt.y })
    }
  }
  const queueWheel = (x: number, y: number, deltaX: number, deltaY: number, modifiers = 0) => {
    // 画面旋转后，屏幕滚动方向也要逆旋转回页面坐标系，手势才跟视觉一致
    const rad = (rotation * Math.PI) / 180
    const cos = Math.cos(rad), sin = Math.sin(rad)
    const ddx = deltaX * cos + deltaY * sin
    const ddy = -deltaX * sin + deltaY * cos
    const w = wheelRef.current
    w.x = x; w.y = y; w.dx += ddx; w.dy += ddy; w.m = modifiers
    if (!w.timer) {
      w.timer = setTimeout(() => {
        send({ type: 'wheel', x: w.x, y: w.y, deltaX: w.dx, deltaY: w.dy, modifiers: w.m })
        w.dx = 0; w.dy = 0; w.timer = 0
      }, 40)
    }
  }
  // 滚轮合并：40ms 窗口内累加 delta 后一次性发，避免滚动时刷爆上行
  const onWheel = (e: React.WheelEvent) => {
    if (!controlRef.current) return
    pauseFollow()
    const { x, y } = mapXY(e as any)
    queueWheel(x, y, e.deltaX, e.deltaY, mods(e))
  }
  const onTouchStart = (e: React.TouchEvent) => {
    if (!controlRef.current || e.touches.length !== 1) return
    pauseFollow()
    const t = e.touches[0]
    touchRef.current = { x: t.clientX, y: t.clientY, t: performance.now(), moved: false }
    stageRef.current?.focus()
  }
  const onTouchMove = (e: React.TouchEvent) => {
    if (!controlRef.current || e.touches.length !== 1) return
    const t = e.touches[0]
    const last = touchRef.current
    const dx = t.clientX - last.x
    const dy = t.clientY - last.y
    if (Math.abs(dx) + Math.abs(dy) > 3) {
      e.preventDefault()
      last.moved = true
      const { x, y } = mapClientXY(t.clientX, t.clientY)
      // 手指上滑(dy<0) = 页面向下滚(deltaY>0)，保持移动端自然滚动方向。
      queueWheel(x, y, -dx, -dy, 0)
      last.x = t.clientX
      last.y = t.clientY
    }
  }
  const onTouchEnd = (e: React.TouchEvent) => {
    if (!controlRef.current) return
    const t = e.changedTouches[0]
    if (!t) return
    const last = touchRef.current
    const tap = !last.moved && performance.now() - last.t < 420
    if (!tap) return
    const { x, y } = mapClientXY(t.clientX, t.clientY)
    const st = stageRef.current
    if (st) {
      const r = st.getBoundingClientRect()
      const id = ++ripIdRef.current
      setRipples((rs) => [...rs, { id, x: t.clientX - r.left, y: t.clientY - r.top }])
      setTimeout(() => setRipples((rs) => rs.filter((p) => p.id !== id)), 450)
    }
    send({ type: 'mouse', sub: 'down', x, y, button: 'left', modifiers: 0 })
    send({ type: 'mouse', sub: 'up', x, y, button: 'left', modifiers: 0 })
  }
  // 复制选区：让后端取远端页面 window.getSelection()，回包后写进本设备剪贴板（见 onmessage 'copied'）
  const copySelection = () => send({ type: 'copy' })
  // 粘贴：读本机剪贴板发到远端焦点框。注意——画面是普通 <div>（非可编辑），浏览器不会给它派发
  // paste 事件，所以不能靠 onPaste；keydown 本身是用户手势，安全上下文下可直接 readText。
  const pasteFromClipboard = () => {
    // 先试本机剪贴板（外部复制的内容）；读不到/无权限/非安全上下文 → 发空 paste，
    // 后端用「浏览器内部剪贴板」兜底（内部 Ctrl+C 存的），所以内部复制粘贴永远能跑。
    const p = navigator.clipboard?.readText?.()
    if (!p) { send({ type: 'paste' }); return }
    p.then(
      (text) => send(text ? { type: 'paste', text } : { type: 'paste' }),
      () => send({ type: 'paste' }),
    )
  }
  // 组合结束（或非组合的文本插入，如 macOS 长按选音标）后，把 textarea 里攒出的整段
  // 文本一次发往远端。组合中的退格/选词等按键都由输入法在本地消费，不会到这里。
  const flushIme = () => {
    const ta = imeRef.current
    if (!ta || !ta.value) return
    send({ type: 'key', sub: 'char', text: ta.value })
    ta.value = ''
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (!controlRef.current) return
    pauseFollow()
    // 输入法组合中：按键属于输入法（key 为 "Process"/keyCode 229），不转发也不
    // preventDefault，否则组合被打断；组合结果统一由 flushIme 发送。
    if (composingRef.current || e.nativeEvent.isComposing || e.keyCode === 229) return
    const mod = e.ctrlKey || e.metaKey
    // 复制/粘贴走「跨屏」桥，不把组合键转发给远端：用本机剪贴板，不碰远端那台机器的剪贴板
    if (mod && (e.key === 'v' || e.key === 'V')) { e.preventDefault(); pasteFromClipboard(); return }
    if (mod && (e.key === 'c' || e.key === 'C')) { e.preventDefault(); copySelection(); return }
    e.preventDefault()
    // 可打印字符（无 Ctrl/Meta 组合）→ insertText；其余 → 特殊键事件
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      send({ type: 'key', sub: 'char', text: e.key })
      return
    }
    send({ type: 'key', sub: 'down', key: e.key, modifiers: mods(e) })
    send({ type: 'key', sub: 'up', key: e.key, modifiers: mods(e) })
  }

  // ⋯ 菜单：低频动作一律进这里，主行永远只有四个目标（设计 17 §3）。
  // 窄档下把「前进 / 主页」也收进来——它们是次高频，后退才是必须留在外面的那一枚。
  const menuItems: MenuProps['items'] = [
    // 全屏摆在最前：远端视口固定之后，「黑边多厚」只取决于观看区多大，铺满显示器就是把黑边挤没
    ...(fs.supported ? [
      { key: 'fs', icon: fs.on ? <ExitFullscreenIcon size={15} /> : <FullscreenIcon size={15} />,
        label: fs.on ? t('common.exitFullscreen') : t('common.fullscreen'), onClick: fs.toggle },
      { type: 'divider' as const, key: 'd0' },
    ] : []),
    ...(shelf === 'narrow' ? [
      { key: 'forward', icon: <ChevronRight />, label: t('file.forward'), onClick: () => act('forward') },
      { key: 'home', icon: <HomeIcon size={15} />, label: t('browser.home'), onClick: () => act('navigate', { url: home }) },
      { type: 'divider' as const, key: 'd1' },
    ] : []),
    { key: 'rotate', icon: <RotateScreenIcon />, label: rotation ? `${t('browser.rotateTitle')} ${rotation}°` : t('browser.rotateTitle'), onClick: rotate },
    { key: 'devtools', icon: <CodeIcon />, label: t('browser.devtoolsTitle'), onClick: openDevtools },
    { key: 'external', icon: <GlobeIcon size={15} />, label: t('browser.openExternalTitle'), onClick: openExternal },
    // terms=none：新开的这页只有镜像，不把当前开着的会话标签一并拽过去（见 route-hash）
    { key: 'newpage', icon: <OpenInIcon size={15} />, label: t('mirror.openInNewPage'),
      onClick: () => window.open('/#/browser?terms=none', '_blank') },
    { type: 'divider' as const, key: 'd2' },
    { key: 'newtab', icon: <PlusIcon />, label: t('browser.newTab'), onClick: newTab },
  ]

  const deviceName = device ? t(DEVICES.find((d) => d.key === device)?.nameKey || 'browser.device.desktop') : t('browser.device.desktop')

  // 连接与画质：omnibox 的左徽标。真浏览器的锁图标就在这个位置——它天然是
  // 「这条连接怎么样」的位置，不该另做一枚按钮排在旁边。
  const streamBadge = (
    <StreamControl
      connected={connected} label={connected ? t('browser.connected') : t('browser.disconnected')}
      quality={quality} onQuality={changeQuality}
      level={quality === 'auto' ? levelName : undefined}
      latency={latency} bytesPerSec={bw} fps={fps}
      size={frame.w ? `${frame.w}×${frame.h}` : undefined}
      variant="badge" showLabel={shelf !== 'narrow'} />
  )

  const deviceChip = (
    <Dropdown trigger={['click']} placement="bottomRight" menu={{
      selectedKeys: [device],
      items: [
        { key: '', onClick: () => changeDevice(''),
          label: <span>{t('browser.device.desktop')}<span style={{ color: 'var(--text-dimmer)' }}>{` · ${deskVp.w}×${deskVp.h}`}</span></span> },
        ...DEVICES.map((d) => ({ key: d.key, label: t(d.nameKey), onClick: () => changeDevice(d.key) })),
      ],
    }}>
      <span><StatusChip icon={<DeviceIcon />} text={deviceName} active={!!device} onClick={() => {}} /></span>
    </Dropdown>
  )

  return (
    // 背景色写在根上：全屏时这一块就是整块屏幕，缺省背景会在工具行外露出一圈白。
    // position: relative 给下面 getPopupContainer 当定位基准。
    <div ref={rootRef} style={{ position: 'relative', display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg)' }}>
      {/* 浮层（⋯ 菜单/标签/设备下拉/画质气泡）挂进这一块，而不是 document.body：全屏时只有
          全屏元素的子树会被画出来，挂 body 上的浮层在全屏下**看不见也点不着**——实测点了
          「全屏」再开 ⋯ 菜单，菜单在 DOM 里、屏幕上没有，连「退出全屏」都够不着。 */}
      <ConfigProvider getPopupContainer={() => rootRef.current || document.body}>
        {/* 页头（设计 17）：桌面＝标签条 + 工具行；窄档＝一条主行 + 状态芯片条。
            从前是五行散装控件——「前往」实心按钮比地址栏还抢戏、四档清晰度常驻一整行、
            「外部打开」被挤成第五行的孤儿。现在只有一个主角：omnibox。 */}
        {shelf !== 'narrow' && (
          <TabStrip tabs={displayTabs} active={target} pinned={pinnedTabs} onPin={togglePin}
            onSelect={switchTab} onClose={closeTab} onCloseMany={closeTabs} onAdd={newTab}
            extra={<StatusChip icon={followPaused ? <UserIcon size={12} /> : <BotIcon size={12} />}
              strong={followPaused ? t('browser.followModeHuman') : t('browser.followModeAgent')}
              active={!followPaused} onClick={() => (followPaused ? resumeFollow() : pauseFollow())} />} />
        )}
        <MirrorChrome
          chromeRef={shelfRef}
          main={<>
            <IconBtn icon={<ChevronLeft size={17} />} label={t('file.back')} onClick={() => act('back')} />
            {shelf !== 'narrow' && <>
              <IconBtn icon={<ChevronRight size={17} />} label={t('file.forward')} onClick={() => act('forward')} />
              <IconBtn icon={<RefreshIcon size={16} />} label={t('common.refresh')} onClick={() => act('reload')} />
              <IconBtn icon={<HomeIcon size={16} />} label={t('browser.home')} onClick={() => act('navigate', { url: home })} />
            </>}
            <Omnibox
              value={url}
              onChange={setUrl}
              onSubmit={navigate}
              onFocusChange={(f) => { addrFocused.current = f }}
              placeholder={t('browser.urlPlaceholder')}
              goLabel={t('browser.go')}
              lead={streamBadge}
              trailing={shelf === 'narrow'
                ? <IconBtn icon={<RefreshIcon size={15} />} label={t('common.refresh')} onClick={() => act('reload')} />
                : shelf === 'wide'
                  ? <span className="mc-omni-num">{`${latency == null ? '—' : latency + 'ms'} · ${fmtRate(bw)} · ${fps}fps`}</span>
                  : undefined}
            />
            {shelf === 'narrow' && (
              <IconBtn icon={<TabsIcon />} label={t('browser.tabs')} badge={tabs.length} onClick={() => setTabsOpen(true)} />
            )}
            {shelf !== 'narrow' && deviceChip}
            <MirrorMenu items={menuItems} label={t('common.more')} />
          </>}
          chips={shelf === 'narrow' ? <>
            <StatusChip icon={followPaused ? <UserIcon size={12} /> : <BotIcon size={12} />}
              strong={followPaused ? t('browser.followModeHuman') : t('browser.followModeAgent')}
              active={!followPaused} onClick={() => (followPaused ? resumeFollow() : pauseFollow())} />
            {deviceChip}
          </> : undefined}
        />
        {/* 手机标签：横条在 360 上放不下第三枚，换成「⧉N + 抽屉」（设计 17 §4） */}
        <TabSheet open={tabsOpen} tabs={displayTabs} active={target} pinned={pinnedTabs}
          onPin={togglePin} onCloseMany={closeTabs} onClose={() => setTabsOpen(false)}
          onSelect={(id) => { switchTab(id); setTabsOpen(false) }}
          onCloseTab={closeTab} onAdd={() => { newTab(); setTabsOpen(false) }} />
        <style>{`
          .bv-ripple{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
            border:2px solid var(--accent);pointer-events:none;animation:bvRip .45s ease-out forwards;}
          @keyframes bvRip{from{transform:scale(.3);opacity:.9}to{transform:scale(2.6);opacity:0}}
        `}</style>
        <div
          ref={stageRef}
          tabIndex={0}
          onKeyDown={onKey}
          onWheel={onWheel}
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          style={{
            flex: 1, minHeight: 0, background: '#000', overflow: 'hidden', position: 'relative',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: control ? 'default' : 'not-allowed', outline: 'none', touchAction: 'none',
          }}
        >
          <img
            ref={imgRef}
            draggable={false}
            onMouseDown={onMouse('down')}
            onMouseUp={onMouse('up')}
            onMouseMove={onMove}
            style={{
              // 显示盒 = 整个舞台（旋转 90/270 时宽高对调），画面按 object-fit: contain 等比塞进去：
              // 装不满的那一维留黑边。远端视口是固定的，所以拖窗格只改这一步的缩放比，画面内容不动。
              position: 'absolute', left: '50%', top: '50%',
              width: rotated ? stage.h : stage.w,
              height: rotated ? stage.w : stage.h,
              objectFit: 'contain',
              // 贴着上沿放，不是居中：黑边全留在下面。居中的话，拖窄一点画面就往中间缩一次，
              // 页面顶边跟着往下走——手上在拖分隔条，眼睛看到的却是「它自己滚了一下」。
              // 贴上沿之后，缩放只让下面那条黑边变厚，页面顶边一直钉在原处。
              objectPosition: '50% 0%',
              transform: `translate(-50%, -50%) rotate(${rotation}deg)`,
            }}
          />
          <textarea
            ref={imeRef}
            aria-label={t('browser.imeProxyLabel')}
            tabIndex={-1}
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            onCompositionStart={() => { composingRef.current = true }}
            onCompositionEnd={() => { composingRef.current = false; flushIme() }}
            onInput={() => {
              // 组合中的中间态（isComposing 的 input 事件）不发；只有非组合插入
              //（如 macOS 长按选音标）才在这里落地。
              if (!composingRef.current) flushIme()
            }}
            onBlur={() => {
              // 失焦时丢弃半截组合，避免残留拼音在下次聚焦时被误发到远端。
              composingRef.current = false
              if (imeRef.current) imeRef.current.value = ''
            }}
            style={{
              position: 'absolute', left: imePos.x, top: imePos.y, width: 2, height: 2,
              opacity: 0, padding: 0, border: 'none', outline: 'none', resize: 'none',
              overflow: 'hidden', background: 'transparent', caretColor: 'transparent',
              pointerEvents: 'none',
            }}
          />
          {ripples.map((p) => (
            <span key={p.id} className="bv-ripple" style={{ left: p.x, top: p.y }} />
          ))}
          {/* 连不上且后端报了原因：覆盖一层提示，省得用户对着黑屏猜 */}
          {!connected && healthMsg && (
            <div style={{
              position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: 24, pointerEvents: 'none',
            }}>
              <div style={{
                maxWidth: 520, padding: 'var(--sp-3) var(--sp-4)', borderRadius: 'var(--r-sm)', background: 'rgba(0,0,0,.72)',
                border: '1px solid var(--danger-border)', color: 'var(--danger)', fontSize: 'var(--fs-sm)', lineHeight: 1.6, textAlign: 'center',
              }}>
                {t('browser.launchFailed')}<br />{healthMsg}
              </div>
            </div>
          )}
        </div>
      </ConfigProvider>
    </div>
  )
}
