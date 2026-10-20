// 手机镜像页：把后端手机（Linux→Android adb）的画面实时渲染到 <img>，并转发点按/滑动/输入。
// 协议见 backend/phone/screencast.go：
//   收 二进制帧 [w:u16][h:u16][seq:u16][jpeg...] | {type:'pong'|'error'|'level'}
//   发 {type:'ack',n} | {type:'ping',t} | {type:'tap'|'swipe'|'text'|'key'}
import { useEffect, useRef, useState } from 'react'
import { nodeWs } from '../cluster/node-url'
import { ConfigProvider, Dropdown, Input, App as AntApp } from 'antd'
import type { MenuProps } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { connect, type DuplexTransport } from '../../p2p/transport'
import { devKindText, devStateText, listPhoneDevices, selectPhoneDevice, type PhoneDevice } from '../../phone-devices'
import { AppsIcon, ChevronDown, DeviceIcon, ExitFullscreenIcon, FullscreenIcon, OpenInIcon, PhoneAssistIcon, PhoneBackIcon, PhoneHomeIcon, PhoneRecentsIcon, PowerIcon, RefreshIcon, SearchIcon } from '../../icons'
import { fmtRate, IconBtn, MirrorChrome, MirrorMenu, Omnibox, StreamControl, useFullscreen, useShelf, type Quality } from './mirror'

interface PhoneApp { id: string; name?: string }

// 清晰度档位与浏览器页共用（mirror.tsx 的 QUALITY_OPTS），这里只有存盘的 key 不同
const QKEY = 'ttmux.phone.quality'

export default function PhoneView() {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const imgRef = useRef<HTMLImageElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  // 镜像收发底层：p2p 时是 media PC 上的不可靠 DataChannel，回退时是 /api/phone/stream 的 WS。
  // 二进制帧解析/ack/ping/输入逻辑不感知底层（DuplexTransport ≈ WebSocket）。
  const tpRef = useRef<DuplexTransport | null>(null)
  const sizeRef = useRef({ w: 1080, h: 2400 }) // 画面内在尺寸（设备像素）

  const [connected, setConnected] = useState(false)
  const [healthMsg, setHealthMsg] = useState('')
  const [quality, setQuality] = useState<Quality>(() => {
    const s = localStorage.getItem(QKEY)
    if (s == null || s === 'auto') return 'auto'
    return Number(s) || 'auto'
  })
  const [levelName, setLevelName] = useState('') // 自适应当前档名（auto 时显示）
  const [apps, setApps] = useState<PhoneApp[]>([])
  const [appsOpen, setAppsOpen] = useState(false)
  const [appQuery, setAppQuery] = useState('')
  // 设备身份：型号 + 系统 + 分辨率。devbox 只显示，不可编辑——它是身份不是输入（设计 17 §6）
  const [devName, setDevName] = useState('')
  const [devOs, setDevOs] = useState('')
  const [shelf, shelfRef] = useShelf()
  const [reconnectKey, setReconnectKey] = useState(0)
  const [platform, setPlatform] = useState<'android' | 'ios'>('android')
  const fs = useFullscreen(rootRef)
  const [devices, setDevices] = useState<PhoneDevice[]>([])
  const [latency, setLatency] = useState<number | null>(null)
  const [bw, setBw] = useState(0)
  const [fps, setFps] = useState(0)
  const bytesRef = useRef(0)
  const framesRef = useRef(0)

  // 点击涟漪 + 拖动起点（用于区分 tap / swipe）
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([])
  const ripIdRef = useRef(0)
  const dragRef = useRef({ x: 0, y: 0, dx: 0, dy: 0, t: 0, active: false })

  const send = (o: any) => {
    // DuplexTransport.send 对 p2p 自带 open-before-send 排队、对 frp 内部判 readyState，
    // 这里直接发即可（未连时 frp 分支静默丢弃，与迁移前 ws.readyState 守卫等价）。
    tpRef.current?.send(JSON.stringify(o))
  }

  // 屏幕坐标 → 设备像素（<img> 用 object-fit:contain，居中留黑边，先扣黑边再按比例缩放）
  const mapXY = (clientX: number, clientY: number) => {
    const r = stageRef.current!.getBoundingClientRect()
    const nw = sizeRef.current.w, nh = sizeRef.current.h
    const scale = Math.min(r.width / nw, r.height / nh)
    const dispW = nw * scale, dispH = nh * scale
    const padX = (r.width - dispW) / 2, padY = (r.height - dispH) / 2
    const fx = Math.max(0, Math.min(1, (clientX - r.left - padX) / dispW))
    const fy = Math.max(0, Math.min(1, (clientY - r.top - padY) / dispH))
    return { x: Math.round(fx * nw), y: Math.round(fy * nh) }
  }

  const addRipple = (clientX: number, clientY: number) => {
    const st = stageRef.current
    if (!st) return
    const r = st.getBoundingClientRect()
    const id = ++ripIdRef.current
    setRipples((rs) => [...rs, { id, x: clientX - r.left, y: clientY - r.top }])
    setTimeout(() => setRipples((rs) => rs.filter((p) => p.id !== id)), 450)
  }

  // 按下记起点；松开按位移/时长判定 tap 还是 swipe
  const onDown = (clientX: number, clientY: number) => {
    stageRef.current?.focus()
    const p = mapXY(clientX, clientY)
    dragRef.current = { x: p.x, y: p.y, dx: clientX, dy: clientY, t: performance.now(), active: true }
  }
  const onUp = (clientX: number, clientY: number) => {
    const d = dragRef.current
    if (!d.active) return
    d.active = false
    const p = mapXY(clientX, clientY)
    const moved = Math.abs(clientX - d.dx) + Math.abs(clientY - d.dy)
    const dt = performance.now() - d.t
    if (moved < 12) {
      addRipple(clientX, clientY)
      send({ type: 'tap', x: p.x, y: p.y })
    } else {
      send({ type: 'swipe', x1: d.x, y1: d.y, x2: p.x, y2: p.y, ms: Math.max(50, Math.min(800, Math.round(dt))) })
    }
  }

  const onKey = (e: React.KeyboardEvent) => {
    // 可打印字符 → text；功能键 → keyevent
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault(); send({ type: 'text', text: e.key }); return
    }
    const map: Record<string, string> = { Enter: 'enter', Backspace: 'del', Escape: 'back' }
    const name = map[e.key]
    if (name) { e.preventDefault(); send({ type: 'key', name }) }
  }

  // 拉取 App 列表
  const loadApps = async () => {
    try {
      const r = await api('GET', '/phone/apps')
      if (r?.data) setApps(r.data)
    } catch {}
  }
  useEffect(() => { loadApps() }, [])

  // 平台（android/ios）→ 底部导航键自适应。取 health.platform；连不上回落看 config.mode。
  const loadIdentity = () => {
    api('GET', '/phone/health').then((r) => {
      const p = r?.data?.platform
      if (p === 'ios' || p === 'android') setPlatform(p)
      // 型号/系统后端给什么用什么，都没有就退回平台名——devbox 永远有话说
      setDevName(String(r?.data?.model || r?.data?.device || r?.data?.serial || ''))
      setDevOs(String(r?.data?.release ? `Android ${r.data.release}` : r?.data?.version || ''))
    }).catch(() => {})
  }
  useEffect(() => {
    loadIdentity()
    api('GET', '/phone/config').then((r) => {
      if (r?.data?.platform === 'ios') setPlatform('ios')
    }).catch(() => {})
  }, [])

  // 设备芯片＝切换器：一台机器上模拟器和真机常常同时挂着，换设备不该只能回设置页。
  const loadDevices = () => listPhoneDevices(platform).then(setDevices)
  useEffect(() => { loadDevices() }, [platform]) // 芯片上「这是哪一类设备」不能等到点开下拉才有
  const switchDevice = async (id: string) => {
    if (id === devices.find((d) => d.current)?.id) return
    setDevices((ds) => ds.map((d) => ({ ...d, current: d.id === id })))
    // 名字要一起传：模拟器停掉之后只有 AVD 名指得动它，光有 serial 会指空
    const avdName = devices.find((d) => d.id === id)?.name
    try { await selectPhoneDevice(platform, id, avdName) } catch (e: any) { message.error(e?.message || String(e)) }
    loadIdentity(); loadDevices() // 回读一遍：连不上的话「当前是哪台」得按后端的说法回正
    setReconnectKey((n) => n + 1) // 换了画面源：重连一遍，尺寸/健康都按新设备重来
  }

  const launch = (id: string) => { if (id) api('POST', `/phone/apps/${encodeURIComponent(id)}/launch`).catch(() => {}) }
  const pressKey = (name: string) => api('POST', '/phone/key', { name }).catch(() => {})

  // quality 变化才重建连接；断开(掉线/切设备/模拟器停起)自动重连，画面自愈无需刷新。
  useEffect(() => {
    let stopped = false
    let tp: DuplexTransport | null = null
    let objURL: string | null = null
    let retry: any = null
    // 通用传输 Phase 3：镜像走 media PC 的不可靠 DataChannel；media 未连/P2P 不可用 → 回退
    // 到原 /api/phone/stream WS（frpUrl），行为与迁移前逐字节一致。p2p 分支把 query 里的
    // params（control/auto|q）经 label 带给后端（原本靠 WS query 传）。
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const qParam = quality === 'auto' ? 'auto=1' : `q=${quality}`
    const frpUrl = nodeWs(`/phone/stream?control=1&${qParam}`)
    const initParams: Record<string, string> = { control: '1' }
    if (quality === 'auto') initParams.auto = '1'
    else initParams.q = String(quality)
    const openConn = () => {
      if (stopped) return
      const t = connect('phone', { frpUrl, initParams })
      tp = t; tpRef.current = t
      // 连上（frp=WS open / p2p=DataChannel open）语义等价迁移前 ws.onopen。
      t.onopen = () => { setConnected(true); setHealthMsg('') }
      t.onclose = () => {
        setConnected(false)
        if (stopped) return
        api('GET', '/phone/health').then((r) => { if (!r?.data?.ok) setHealthMsg(r?.data?.error || '') }).catch(() => {})
        retry = setTimeout(openConn, 1500) // 自动重连（设备/链路自愈）
      }
      t.onmessage = (data) => {
        if (typeof data !== 'string') {
          if (!imgRef.current) return
          const buf = data as ArrayBuffer
          const dv = new DataView(buf)
          const w = dv.getUint16(0, true), h = dv.getUint16(2, true), seq = dv.getUint16(4, true)
          sizeRef.current = { w: w || 1080, h: h || 2400 }
          bytesRef.current += buf.byteLength
          framesRef.current++
          if (objURL) URL.revokeObjectURL(objURL)
          objURL = URL.createObjectURL(new Blob([new Uint8Array(buf, 6)], { type: 'image/jpeg' }))
          imgRef.current.src = objURL
          t.send(JSON.stringify({ type: 'ack', n: seq }))
          return
        }
        const msg = JSON.parse(data)
        if (msg.type === 'error') { setHealthMsg(msg.msg); return }
        if (msg.type === 'pong') { setLatency(Math.round(performance.now() - msg.t)); return }
        if (msg.type === 'level') { setLevelName(msg.name || ''); return }
      }
    }
    openConn()
    const ping = setInterval(() => { tp?.send(JSON.stringify({ type: 'ping', t: performance.now() })) }, 1000)
    const meter = setInterval(() => {
      setBw(bytesRef.current); setFps(framesRef.current)
      bytesRef.current = 0; framesRef.current = 0
    }, 1000)
    return () => {
      stopped = true
      clearInterval(ping); clearInterval(meter); clearTimeout(retry)
      if (objURL) URL.revokeObjectURL(objURL)
      if (tp) { tp.onmessage = () => {}; tp.onclose = () => {} } // 卸载后忽略在途回调
      tp?.close()
      if (tpRef.current === tp) tpRef.current = null
    }
  }, [quality, reconnectKey])

  const changeQuality = (v: Quality) => { setQuality(v); try { localStorage.setItem(QKEY, String(v)) } catch {} }

  // ⋯ 菜单：低频动作。Android 的锁屏/唤醒不在三键里，收在这儿正好。
  const menuItems: MenuProps['items'] = [
    // 全屏摆在最前，跟浏览器页一致：铺满显示器时黑边最少
    ...(fs.supported ? [
      { key: 'fs', icon: fs.on ? <ExitFullscreenIcon size={14} /> : <FullscreenIcon size={14} />,
        label: fs.on ? t('common.exitFullscreen') : t('common.fullscreen'), onClick: fs.toggle },
      { type: 'divider' as const, key: 'd0' },
    ] : []),
    ...(platform === 'ios' ? [] : [
      { key: 'lock', icon: <PowerIcon size={14} />, label: t('phone.lock'), onClick: () => pressKey('lock') },
    ]),
    { key: 'reconnect', icon: <RefreshIcon size={14} />, label: t('phone.reconnect'), onClick: () => setReconnectKey((n) => n + 1) },
    // terms=none：新开的这页只有镜像，不继承当前的会话标签（见 route-hash）
    { key: 'newpage', icon: <OpenInIcon size={14} />, label: t('mirror.openInNewPage'),
      onClick: () => window.open('/#/phone?terms=none', '_blank') },
  ]

  // 设备身份：名字 + 它是什么（本机模拟器/真机/远程），点开换一台。
  // 名字和类型说的是同一台机器，所以是一枚可点的整体，不是并排两枚胶囊。
  const cur = devices.find((d) => d.current)
  const deviceIdentity = (
    <Dropdown trigger={['click']} placement="bottomRight"
      onOpenChange={(v) => { if (v) loadDevices() }}
      menu={{
        selectedKeys: cur ? [cur.id] : [],
        items: devices.length ? devices.map((d) => {
          const why = devStateText(d, t)
          return {
            key: d.id,
            icon: <DeviceIcon size={14} />,
            label: <span>{d.name}<span style={{ color: 'var(--text-dimmer)' }}>{` · ${devKindText(d, t)}${why ? ' · ' + why : ''}`}</span></span>,
            onClick: () => switchDevice(d.id),
          }
        }) : [{ key: 'none', disabled: true, label: t('phone.devNone') }],
      }}>
      <button type="button" className="mc-omni-txt mc-omni-id" title={`${devName || t('nav.phone')}${cur ? ' · ' + devKindText(cur, t) : ''}`}>
        <span className="host">{devName || t('nav.phone')}</span>
        {cur && <span className="kind"><DeviceIcon size={12} />{devKindText(cur, t)}</span>}
        <ChevronDown size={10} />
      </button>
    </Dropdown>
  )

  // 设备按键：Android=返回/主屏/多任务；iOS=主屏/锁屏/Siri（iOS 无系统返回键）。
  // 桌面浮在画面底部——竖屏画面两侧本来就是大片黑边，按键条不该再占一整条；
  // 窄档反过来贴底成实条，浮层会压住已经顶到边的画面。
  const deviceKeys = (
    <div className={`mc-keys${shelf === 'narrow' ? '' : ' is-float'}`}>
      {platform === 'ios' ? (
        <>
          <IconBtn icon={<PhoneHomeIcon />} label={t('phone.home')} onClick={() => pressKey('home')} />
          <IconBtn icon={<PowerIcon />} label={t('phone.lock')} onClick={() => pressKey('lock')} />
          <IconBtn icon={<PhoneAssistIcon />} label={t('phone.siri')} onClick={() => pressKey('siri')} />
        </>
      ) : (
        <>
          <IconBtn icon={<PhoneBackIcon />} label={t('phone.back')} onClick={() => pressKey('back')} />
          <IconBtn icon={<PhoneHomeIcon />} label={t('phone.home')} onClick={() => pressKey('home')} />
          <IconBtn icon={<PhoneRecentsIcon />} label={t('phone.recents')} onClick={() => pressKey('recents')} />
        </>
      )}
    </div>
  )

  return (
    // 背景色写在根上：全屏时这一块就是整块屏幕。position:relative 给 getPopupContainer 当基准。
    <div ref={rootRef} style={{ position: 'relative', display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-base)' }}>
      {/* 浮层挂进这一块而不是 document.body：全屏时只有全屏元素的子树会被画出来，
          挂 body 上的菜单在全屏下看不见也点不着（浏览器页那边踩过，见 BrowserView）。 */}
      <ConfigProvider getPopupContainer={() => rootRef.current || document.body}>
        {/* 页头（设计 17 §6）：与浏览器页同一套语法，只是主角从「地址」换成「设备」。
            devbox 只读——它是身份不是输入；换设备走状态芯片，不为了跟 omnibox 对称硬做成输入框。 */}
        <MirrorChrome
          chromeRef={shelfRef}
          main={<>
            <Omnibox
              readOnly
              value={devName || t('nav.phone')}
              identity={deviceIdentity}
              sub={[devOs, `${sizeRef.current.w}×${sizeRef.current.h}`].filter(Boolean).join(' · ')}
              lead={<StreamControl
                connected={connected} label={connected ? t('phone.connected') : t('phone.disconnected')}
                quality={quality} onQuality={changeQuality}
                level={quality === 'auto' ? levelName : undefined}
                latency={latency} bytesPerSec={bw} fps={fps}
                variant="badge" showLabel={shelf !== 'narrow'} />}
              trailing={shelf === 'wide'
                ? <span className="mc-omni-num">{`${latency == null ? '—' : latency + 'ms'} · ${fmtRate(bw)} · ${fps}fps`}</span>
                : undefined}
            />
            {/* 应用启动器：从前是个 160px 的 Select，窄屏上要独占一整行 */}
            <Dropdown trigger={['click']} placement="bottomRight" open={appsOpen} onOpenChange={(v) => { setAppsOpen(v); if (v) loadApps() }}
              popupRender={() => (
                <div className="mc-menu mc-applauncher">
                  <Input size="small" prefix={<SearchIcon size={12} />} placeholder={t('phone.searchApp')}
                    value={appQuery} onChange={(e) => setAppQuery(e.target.value)} allowClear />
                  <div className="mc-applist">
                    {apps
                      .filter((a) => !appQuery || `${a.name || ''} ${a.id}`.toLowerCase().includes(appQuery.toLowerCase()))
                      .slice(0, 60)
                      .map((a) => (
                        <button key={a.id} type="button" className="mc-appitem"
                          onClick={() => { launch(a.id); setAppsOpen(false) }}>
                          <span className="ic" aria-hidden>{(a.name || a.id).slice(0, 1).toUpperCase()}</span>
                          <span className="nm">{a.name || a.id}</span>
                        </button>
                      ))}
                  </div>
                  <div className="mc-appcount">{t('phone.appCount', { count: apps.length })}</div>
                </div>
              )}>
              <button type="button" className="mc-ib" title={t('phone.launchApp')} aria-label={t('phone.launchApp')}>
                <AppsIcon />
              </button>
            </Dropdown>
            <MirrorMenu label={t('common.more')} items={menuItems} />
          </>}
        />

        <style>{`
          .pv-ripple{position:absolute;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;
            border:2px solid var(--accent);pointer-events:none;animation:pvRip .45s ease-out forwards;}
          @keyframes pvRip{from{transform:scale(.3);opacity:.9}to{transform:scale(2.6);opacity:0}}
        `}</style>

        {/* 画面舞台 */}
        <div
          ref={stageRef}
          tabIndex={0}
          onKeyDown={onKey}
          onMouseDown={(e) => { e.preventDefault(); onDown(e.clientX, e.clientY) }}
          onMouseUp={(e) => onUp(e.clientX, e.clientY)}
          onTouchStart={(e) => { const t0 = e.touches[0]; if (t0) onDown(t0.clientX, t0.clientY) }}
          onTouchEnd={(e) => { const t0 = e.changedTouches[0]; if (t0) onUp(t0.clientX, t0.clientY) }}
          style={{
            flex: 1, minHeight: 0, background: 'var(--bg-base)', overflow: 'hidden', position: 'relative',
            display: 'flex', alignItems: 'center', justifyContent: 'center', outline: 'none', touchAction: 'none',
          }}
        >
          <img
            ref={imgRef}
            draggable={false}
            // 绝对填满舞台 + object-fit:contain：尺寸对着舞台的确定盒子解析，避免
            // maxHeight:100% 在 flex 列里初次布局拿不到确定高度→需 resize 才显示的 bug。
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', display: 'block', userSelect: 'none' }}
          />
          {ripples.map((p) => (<span key={p.id} className="pv-ripple" style={{ left: p.x, top: p.y }} />))}
          {!connected && healthMsg && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, pointerEvents: 'none' }}>
              <div style={{ maxWidth: 520, padding: 'var(--sp-3) var(--sp-4)', borderRadius: 'var(--r-sm)', background: 'rgba(0,0,0,.72)', border: '1px solid var(--danger-border)', color: 'var(--danger)', fontSize: 'var(--fs-sm)', lineHeight: 1.6, textAlign: 'center' }}>
                {t('phone.unavailable')}<br />{healthMsg}
              </div>
            </div>
          )}
          {shelf !== 'narrow' && deviceKeys}
        </div>
        {/* 窄档贴底成实条：392 的屏上画面已经顶到边，浮层会压住内容 */}
        {shelf === 'narrow' && deviceKeys}

      </ConfigProvider>
    </div>
  )
}
