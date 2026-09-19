// 微信式语音输入：会话页右下角悬浮麦克风按钮。
// 长按开始录音 → 松开识别 → 文本回填到输入框；录音中上滑可取消。
// 录音在浏览器内重采样成 16kHz 单声道 WAV(两家服务商都稳收)，再交后端识别。
import { useEffect, useRef, useState } from 'react'
import { App as AntApp } from 'antd'
import { api, transcribe } from '../../api'
import { useI18n } from '../../i18n'

type Phase = 'idle' | 'requesting' | 'recording' | 'transcribing'

// 上滑超过该像素判为「取消」。
const CANCEL_DY = 90
// 录音时长下限：太短的误触不送去识别。
const MIN_MS = 500

/**
 * 三种形态：悬浮（默认，右下角圆钮，手机用）/ inline（composer 控制条上的 pill）/
 * toolbar（会话工具条上的一枚扁平按钮，带「语音输入」字样——终端视图也能按住说话）。
 */
/** 快捷键：Mac ⌘⇧S，其它 Ctrl+Shift+S。S 取 speak；Ctrl+Shift+V 是终端粘贴，不能占 */
const HOTKEY_LABEL = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '') ? '⌘⇧S' : 'Ctrl+Shift+S'
/** 按住超过这么久再松开 = 对讲机式，松开即识别；更短 = 点一下，切换式 */
const HOLD_MS = 350
const isHotkey = (e: KeyboardEvent) => (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey && e.code === 'KeyS'

/**
 * hotkey：这一枚响应全局快捷键。同一时刻页面上可能挂着好几枚话筒（每份对话的 composer 都有一枚），
 * 只有当前视图的那枚传 true，不然一个键按下去几路一起录。
 * 键盘开的录音没有「松手」：再按一次识别，Esc 取消。
 */
export function VoiceInput({ accent, onResult, inline = false, toolbar = false, hotkey = false }: { accent: string; onResult: (text: string) => void; inline?: boolean; toolbar?: boolean; hotkey?: boolean }) {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  // 录音能力探测：getUserMedia/MediaRecorder 仅在安全上下文(HTTPS / localhost)可用。
  // 手机走 LAN 的 http:// 访问时 navigator.mediaDevices 为 undefined，按了也录不了，
  // 故按钮置灰并给出「需 HTTPS」的明确提示，而不是含糊的「麦克风被拒」。
  const micUsable = typeof navigator !== 'undefined'
    && !!navigator.mediaDevices?.getUserMedia
    && typeof window !== 'undefined' && typeof window.MediaRecorder !== 'undefined'
  const micHint = window.isSecureContext === false ? t('voice.insecureContext') : t('voice.unsupported')
  const [configured, setConfigured] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [secs, setSecs] = useState(0)
  const [cancelArmed, setCancelArmed] = useState(false)

  const recRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const pressedRef = useRef(false)   // 手指是否仍按住(应对授权异步期间的提前松手)
  const cancelRef = useRef(false)    // 松手时是否处于取消区
  const startYRef = useRef(0)
  const startTsRef = useRef(0)
  const byKeyRef = useRef(false)     // 这段录音是快捷键开的：覆盖层文案不同，结束靠再按一次
  const [byKey, setByKey] = useState(false)
  const timerRef = useRef<number | undefined>(undefined)

  // 探测后端是否已配置可用的 ASR 服务商，未配置则按钮置灰提示去设置。
  useEffect(() => {
    api('GET', '/speech/config').then((r) => {
      const c = r?.data || {}
      const ok = c.provider === 'openai'
        ? !!c.openai?.apiKey
        : c.provider === 'volcano'
          ? !!(c.volcano?.apiKey || (c.volcano?.appId && c.volcano?.accessToken))
          : false
      setConfigured(ok)
    }).catch(() => setConfigured(false))
  }, [])

  // 卸载时兜底释放麦克风。
  useEffect(() => () => { stopTracks(); if (timerRef.current) clearInterval(timerRef.current) }, [])

  const stopTracks = () => {
    streamRef.current?.getTracks().forEach((tk) => tk.stop())
    streamRef.current = null
  }

  const begin = async (clientY: number, viaKey = false) => {
    if (phase !== 'idle') return
    byKeyRef.current = viaKey
    setByKey(viaKey)
    if (!micUsable) { message.error(micHint); return }
    if (!configured) { message.info(t('voice.notConfigured')); return }
    pressedRef.current = true
    cancelRef.current = false
    setCancelArmed(false)
    startYRef.current = clientY
    setPhase('requesting')
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      pressedRef.current = false
      setPhase('idle')
      message.error(t('voice.micDenied'))
      return
    }
    if (!pressedRef.current) { stream.getTracks().forEach((tk) => tk.stop()); setPhase('idle'); return } // 授权期间已松手
    streamRef.current = stream
    chunksRef.current = []
    let rec: MediaRecorder
    try { rec = new MediaRecorder(stream) }
    catch { stopTracks(); pressedRef.current = false; setPhase('idle'); message.error(t('voice.unsupported')); return }
    rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data) }
    rec.onstop = () => { stopTracks(); finish() }
    recRef.current = rec
    rec.start()
    startTsRef.current = Date.now()
    setSecs(0)
    setPhase('recording')
    timerRef.current = window.setInterval(() => setSecs(Math.floor((Date.now() - startTsRef.current) / 1000)), 250)
  }

  const move = (clientY: number) => {
    if (phase !== 'recording') return
    const armed = startYRef.current - clientY > CANCEL_DY
    cancelRef.current = armed
    setCancelArmed(armed)
  }

  const end = () => {
    pressedRef.current = false
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = undefined }
    if (phase === 'requesting') { setPhase('idle'); return } // 还没真正开录
    if (phase !== 'recording') return
    try { recRef.current?.stop() } catch { stopTracks(); setPhase('idle') } // onstop 里走 finish()
  }

  // 全局快捷键：keydown 捕获阶段拦下，别让 xterm / 输入框先吃掉。用 ref 读最新的 phase，监听器只挂一次
  const phaseRef = useRef<Phase>('idle')
  phaseRef.current = phase
  const beginRef = useRef(begin); beginRef.current = begin
  const endRef = useRef(end); endRef.current = end
  // 两用：按住不放 = 对讲机（keydown 开录、keyup 识别）；快速点一下 = 切换式（再按一次识别）。
  // 判据是 keydown 到 keyup 的间隔：超过 HOLD_MS 才算「按住」。S 键先松、修饰键后松也算一次 keyup
  const downAt = useRef(0)
  const holding = useRef(false)
  useEffect(() => {
    if (!hotkey) return
    const onDown = (e: KeyboardEvent) => {
      if (e.repeat) return
      if (isHotkey(e)) {
        e.preventDefault(); e.stopPropagation()
        if (phaseRef.current === 'idle') { downAt.current = Date.now(); holding.current = true; void beginRef.current(0, true) }
        else if (phaseRef.current === 'recording' || phaseRef.current === 'requesting') { holding.current = false; endRef.current() }
        return
      }
      if (e.key === 'Escape' && byKeyRef.current && (phaseRef.current === 'recording' || phaseRef.current === 'requesting')) {
        e.preventDefault(); e.stopPropagation()
        cancelRef.current = true
        holding.current = false
        endRef.current()
      }
    }
    const onUp = (e: KeyboardEvent) => {
      if (!holding.current) return
      const isKey = e.code === 'KeyS' || e.key === 'Shift' || e.key === 'Control' || e.key === 'Meta'
      if (!isKey) return
      if (Date.now() - downAt.current < HOLD_MS) { holding.current = false; return } // 点一下：留给切换式
      holding.current = false
      if (phaseRef.current === 'recording' || phaseRef.current === 'requesting') endRef.current()
    }
    window.addEventListener('keydown', onDown, { capture: true })
    window.addEventListener('keyup', onUp, { capture: true })
    return () => {
      window.removeEventListener('keydown', onDown, { capture: true } as any)
      window.removeEventListener('keyup', onUp, { capture: true } as any)
    }
  }, [hotkey])

  // 录音停止后：取消 / 太短 / 正常识别。
  const finish = async () => {
    const dur = Date.now() - startTsRef.current
    const blob = new Blob(chunksRef.current, { type: chunksRef.current[0]?.type || 'audio/webm' })
    if (cancelRef.current) { setPhase('idle'); return }
    if (dur < MIN_MS || blob.size === 0) { setPhase('idle'); message.info(t('voice.tooShort')); return }
    setPhase('transcribing')
    try {
      const wav = await toWav16k(blob)
      const text = await transcribe(wav)
      if (text.trim()) { onResult(text.trim()); message.success(t('voice.recognized')) }
      else message.info(t('voice.empty'))
    } catch (e: any) {
      message.error(t('voice.failed', { message: e.message || String(e) }))
    } finally {
      setPhase('idle')
    }
  }

  const active = phase === 'recording' || phase === 'requesting'
  const mm = String(Math.floor(secs / 60)).padStart(2, '0')
  const ss = String(secs % 60).padStart(2, '0')

  return (
    <>
      {active && (
        <div style={{
          position: 'fixed', left: '50%', bottom: 130, transform: 'translateX(-50%)', zIndex: 60,
          minWidth: 220, padding: '16px 22px', borderRadius: 14, textAlign: 'center',
          background: cancelArmed ? 'rgba(180,40,40,0.95)' : 'rgba(30,30,30,0.92)',
          color: '#fff', boxShadow: '0 8px 32px rgba(0,0,0,0.45)', pointerEvents: 'none',
          transition: 'background .15s ease',
        }}>
          <div style={{ marginBottom: 6, display: 'flex', justifyContent: 'center' }}>
            <span className="cc-pulse" style={{ display: 'inline-flex', filter: cancelArmed ? 'grayscale(1) brightness(1.4)' : undefined }}>
              <MicIcon size={34} />
            </span>
          </div>
          <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 18, marginBottom: 6 }}>{mm}:{ss}</div>
          <div style={{ fontSize: 12, opacity: 0.85 }}>
            {phase === 'requesting' ? t('voice.starting') : byKey ? t('voice.hotkeyStop', { key: HOTKEY_LABEL }) : cancelArmed ? t('voice.releaseCancel') : t('voice.releaseSend')}
          </div>
        </div>
      )}
      <button
        type="button"
        className={toolbar ? `tt-tbtn tt-mic${active ? ' rec' : ''}` : inline ? `tt-pill ico tt-mic${active ? ' rec' : ''}` : undefined}
        title={!micUsable ? micHint : configured ? (hotkey ? `${t('voice.holdToTalk')} · ${t('voice.hotkeyHint', { key: HOTKEY_LABEL })}` : t('voice.holdToTalk')) : t('voice.notConfigured')}
        aria-label={t('voice.holdToTalk')}
        disabled={phase === 'transcribing'}
        onContextMenu={(e) => e.preventDefault()}
        onPointerDown={(e) => { e.preventDefault(); (e.target as HTMLElement).setPointerCapture?.(e.pointerId); begin(e.clientY) }}
        onPointerMove={(e) => move(e.clientY)}
        onPointerUp={(e) => { e.preventDefault(); end() }}
        onPointerCancel={() => { cancelRef.current = true; end() }}
        style={toolbar ? { touchAction: 'none' } : inline
          // 内联：控制条上的一枚 pill——静息时安静，按住说话才亮成强调色（.tt-mic.rec）。
          // 从前它静息就是一整块实心强调色，跟旁边那颗实心发送键抢，一条控制条两个"主动作"。
          ? { background: cancelArmed ? 'var(--danger)' : undefined, touchAction: 'none' }
          : {
            // 悬浮模式：右下角「微信式」麦克风。
            // bottom 用变量：手机上方向簇（13 §5.3）就落在这个角，不让开就会压住 ↓ / →
            position: 'absolute', right: 18, bottom: 'var(--fab-bottom, 54px)', zIndex: 25, width: 54, height: 54,
            borderRadius: '50%', cursor: 'pointer',
            border: 'none', touchAction: 'none', userSelect: 'none',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: cancelArmed ? '#d23' : accent,
            boxShadow: `0 4px 16px ${accent}66`,
            transform: active ? 'scale(1.12)' : 'scale(1)', transition: 'transform .12s ease, background .12s ease, box-shadow .12s ease',
            opacity: (configured && micUsable) ? 1 : 0.92,
          }}>
        <span className={(phase === 'recording' || phase === 'transcribing') ? 'cc-pulse' : undefined} style={{ display: 'inline-flex' }}>
          <MicIcon size={toolbar ? 14 : inline ? 15 : 26} silver={!(inline || toolbar) || active} />
        </span>
        {toolbar && <span>{t('voice.input')}</span>}
      </button>
    </>
  )
}

// 纯银色话筒图标（单一银色，无高光/暗部渐变，非 emoji）。
function MicIcon({ size = 26, silver: bright = true }: { size?: number; silver?: boolean }) {
  // 悬浮那颗坐在实心强调色上，得用银色才看得清；控制条上那枚是安静 pill，跟着文字色走
  const silver = bright ? '#c4c8d0' : 'currentColor'
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      {/* 话筒头 */}
      <rect x="9" y="2" width="6" height="11" rx="3" fill={silver} />
      {/* 支架 + 底座 */}
      <path d="M6 11a6 6 0 0 0 12 0" fill="none" stroke={silver} strokeWidth="2" strokeLinecap="round" />
      <line x1="12" y1="17" x2="12" y2="21" stroke={silver} strokeWidth="2" strokeLinecap="round" />
      <line x1="8" y1="21.2" x2="16" y2="21.2" stroke={silver} strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

// 把任意录音容器(webm/mp4/ogg…)解码并重采样为 16kHz 单声道 16bit PCM WAV。
async function toWav16k(blob: Blob): Promise<Blob> {
  const buf = await blob.arrayBuffer()
  const Ctx: typeof AudioContext = (window.AudioContext || (window as any).webkitAudioContext)
  const ctx = new Ctx()
  let decoded: AudioBuffer
  try { decoded = await ctx.decodeAudioData(buf) } finally { ctx.close() }
  const rate = 16000
  const frames = Math.max(1, Math.ceil(decoded.duration * rate))
  const off = new OfflineAudioContext(1, frames, rate)
  const src = off.createBufferSource()
  src.buffer = decoded
  src.connect(off.destination)
  src.start()
  const rendered = await off.startRendering()
  return encodeWav(rendered.getChannelData(0), rate)
}

function encodeWav(samples: Float32Array, rate: number): Blob {
  const out = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(out)
  const str = (off: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE')
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  str(36, 'data'); v.setUint32(40, samples.length * 2, true)
  let off = 44
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    off += 2
  }
  return new Blob([out], { type: 'audio/wav' })
}

export default VoiceInput
