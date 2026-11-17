import { usePageEffect } from '../../page-activity'
// 实时回显（会话还在生成时，从终端 capture 里扒出来的那截）。
//
// 从前是把 TUI 尾巴原样倒出来的一坨 pre：`└` 框线、`✔ □` 字符图标、会话名、
// 连用户自己刚发的那句都回显一遍，还跟上面的「正在生成」气泡重复说了两次。
// 现在收成一张卡，和运行组同一套语言：一条左脊 + 一个头 + 一段带终端底的身子，
// 行按类型画（命令 / 待办 / 正文），字符图标一律换成 SVG（图标硬规则）。
import { useMemo, useState, type ReactNode } from 'react'
import { api } from '../../api'
import { detectPrompt } from '../prompt'
import { useI18n } from '../../i18n'
import { CheckIcon, ChevronRight, CircleIcon } from '../../icons'
import { CopyBtn } from './tool-parts'
import { MONO } from './blocks'

// 方框线：TUI 用来画树枝和边框的字符，一律剥掉（`└⎿` 这两个此前漏了，于是原样漏进页面）
const LEAD_BOX = /^[\s│┃|╎┆┊╭╰├╞┝└┗╘╙⎿─━═>❯⏵]+/u
const TAIL_BOX = /[\s│┃|╎┆┊╮╯┤╡┥─━═]+$/u
const BOX_ONLY = /^[\s─━═│┃╭╮╰╯├┤┬┴┼╞╡╪.·]*$/u
const NOISE = /(^background\)$|(auto|plan) mode on|accept edits on|for agen|esc to interrupt|esc to cancel|enter to select|tab\/arrow|to navigate|\? for shortcuts|ctrl\+|shift\+tab|bypass permissions|↑↓|tokens?\b|⧉|auto-?accept|for newline)/i
const SPINNER = /^[\s]*[●○◯⏺✶✳✻∗*•·✢✦✧✺✷+✽][\s]*$/u

// 下面这些字符是**解析** TUI 输出用的，不是拿来显示的——显示一律换成 SVG。
const DONE = /^[✔✓☑]\s*/u
const TODO_MARK = /^[□☐○◻⬜]\s*/u
const CMD = /^\$\s+/
// 「Running 1 shell command…」这类状态行：TUI 自己的进度提示，收成一行淡字
const ACTION = /^(running|waiting|thinking|working|compacting|searching|reading|editing)\b/i

export type TailLine =
  | { kind: 'action' | 'text'; text: string }
  | { kind: 'cmd'; text: string }
  | { kind: 'todo'; text: string; done: boolean }

/** 把 capture 的尾巴清成结构化的几行。纯函数，好测。 */
export function parseTail(raw: string, opts: { session?: string; lastUser?: string } = {}): TailLine[] {
  const skip = new Set([opts.session, (opts.lastUser || '').trim()].filter(Boolean) as string[])
  const out: TailLine[] = []
  let inTip = false // 「Tip: …」会折成两三行，整段都是 TUI 的闲话，到空行为止一起跳过
  for (let l of String(raw).replace(/\r/g, '').split('\n')) {
    if (!l.trim()) inTip = false
    if (inTip) continue
    l = l.replace(LEAD_BOX, '').replace(TAIL_BOX, '').replace(/^[●○◯⏺✶✳✻∗•·]\s?/u, '')
    const v = l.trim()
    if (/^Tip:/i.test(v)) { inTip = true; continue }
    if (!v || BOX_ONLY.test(l) || SPINNER.test(l) || NOISE.test(l)) continue
    // 用户刚发的那句、会话名——TUI 会把它们回显在框里，重复一遍没有意义
    if (skip.has(v)) continue
    if (CMD.test(v)) { out.push({ kind: 'cmd', text: v.replace(CMD, '') }); continue }
    if (DONE.test(v)) { out.push({ kind: 'todo', text: v.replace(DONE, ''), done: true }); continue }
    if (TODO_MARK.test(v)) { out.push({ kind: 'todo', text: v.replace(TODO_MARK, ''), done: false }); continue }
    if (ACTION.test(v)) { out.push({ kind: 'action', text: v }); continue }
    out.push({ kind: 'text', text: v })
  }
  return out.slice(-10)
}

export function LiveTail({ name, accent, idle, lastUser }: {
  name: string
  accent: string
  /** 还没扒到任何东西时显示的东西（「正在生成」那颗省略号） */
  idle?: ReactNode
  /** 用户刚发的那句：TUI 会回显，去重用 */
  lastUser?: string
}) {
  const { t } = useI18n()
  const [raw, setRaw] = useState('')
  const [open, setOpen] = useState(true)
  usePageEffect(() => {
    let stop = false
    const poll = async () => {
      try {
        const r = await api('GET', `/sessions/${encodeURIComponent(name)}/capture?lines=40`)
        const data = r.data || ''
        // 交互式选择框交给 PromptPanel 专门渲染，这里不再重复显示（避免被截断/错乱）
        if (!stop) setRaw(detectPrompt(data) ? '' : data)
      } catch { /* 轮询失败就保持上一帧，别把卡片抖没 */ }
    }
    poll()
    const timer = setInterval(poll, 800)
    return () => { stop = true; clearInterval(timer) }
  }, [name])

  const lines = useMemo(() => parseTail(raw, { session: name, lastUser }), [raw, name, lastUser])
  if (!lines.length) return <>{idle}</>

  const copy = lines.map((l) => (l.kind === 'cmd' ? `$ ${l.text}` : l.text)).join('\n')
  const toggle = () => setOpen((v) => !v)
  return (
    <div className="cc-live" style={{ borderLeftColor: accent }}>
      <div className="cc-live-head" role="button" tabIndex={0} aria-expanded={open} onClick={toggle}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}>
        <span className="cc-cmd-chev" style={{ transform: open ? 'rotate(90deg)' : 'none' }}><ChevronRight size={12} /></span>
        <span className="cc-pulse" style={{ width: 6, height: 6, borderRadius: '50%', background: accent, display: 'inline-block', flex: '0 0 auto' }} />
        <span style={{ flex: '0 0 auto' }}>{t('chat.liveTerminalOutput')}</span>
        <span className="cc-run-last">{open ? '' : lines[lines.length - 1]?.text || ''}</span>
        <CopyBtn text={copy} />
      </div>
      {open && (
        <div className="cc-live-body">
          {lines.map((l, i) => {
            if (l.kind === 'cmd') {
              return (
                <div key={i} className="cc-live-line is-cmd">
                  <span style={{ flex: '0 0 auto', color: 'var(--ok)', fontFamily: MONO, fontWeight: 600 }}>$</span>
                  <span className="cc-live-text">{l.text}</span>
                </div>
              )
            }
            if (l.kind === 'todo') {
              return (
                <div key={i} className="cc-live-line">
                  <span style={{ flex: '0 0 auto', display: 'flex', marginTop: 3, color: l.done ? 'var(--ok)' : 'var(--text-dimmer)' }}>
                    {l.done ? <CheckIcon size={12} /> : <CircleIcon size={12} />}
                  </span>
                  <span className="cc-live-text" style={{ color: l.done ? 'var(--text-dimmer)' : 'var(--text-dim)' }}>{l.text}</span>
                </div>
              )
            }
            return (
              <div key={i} className={`cc-live-line${l.kind === 'action' ? ' is-action' : ''}`}>
                <span className="cc-live-text">{l.text}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
