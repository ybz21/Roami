import { usePageEffect } from '../../page-activity'
// 镜像两页（浏览器 / 手机）共用的**页头语法层**（设计 17）。
//
// 这两页在做同一件事：把一块远端屏幕实时画到本地，外加一条工具条。可它们的页头长期是
// 「一堆控件排排坐」——五种 antd 控件五种圆角与高度、「前往」实心按钮比地址栏还抢戏、
// 四档清晰度常驻一整行、「外部打开」被挤成第五行的孤儿。没有主角。
//
// 这里给出唯一的一套语法，两页都塞进它：
//   主行  = [左钮] [主角（Omnibox / devbox）] [右钮…]   —— 永远只有四个左右的可点目标
//   芯片条 = 智能体 / 连接与画质 / 设备 …               —— 状态只读一眼，点开才是面板
// 主角是唯一被强调的东西：胶囊、撑满剩余宽度、左徽标（连接与画质）+ 右就地操作。
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Dropdown, Popover, Segmented } from 'antd'
import type { MenuProps } from 'antd'
import { useI18n } from '../../i18n'
import { ChevronDown } from '../../icons'

/** 清晰度档位：'auto' = 按带宽自适应，数字 = 固定 JPEG 质量。两页同一套档位与文案。 */
export type Quality = number | 'auto'
export const QUALITY_OPTS: { labelKey: string; value: Quality }[] = [
  { labelKey: 'browser.quality.auto', value: 'auto' },
  { labelKey: 'browser.quality.standard', value: 50 },
  { labelKey: 'browser.quality.high', value: 80 },
  { labelKey: 'browser.quality.ultra', value: 92 },
]

export function fmtRate(bytesPerSec: number): string {
  if (bytesPerSec >= 1 << 20) return (bytesPerSec / (1 << 20)).toFixed(1) + ' MB/s'
  return Math.round(bytesPerSec / 1024) + ' KB/s'
}

// ── 收纳档位 ────────────────────────────────────────────────────────────
// 按**容器**宽度收，不是窗口：这两页会被塞进分栏（会话页右栏、Focus 布局），
// 那时窗口很宽而容器只有 700，读 innerWidth 必然判错。
export type Shelf = 'wide' | 'mid' | 'narrow'

export function useShelf(): [Shelf, (el: HTMLElement | null) => void] {
  const [shelf, setShelf] = useState<Shelf>('wide')
  const obs = useRef<ResizeObserver | null>(null)
  const ref = useCallback((el: HTMLElement | null) => {
    obs.current?.disconnect()
    if (!el) return
    const read = (w: number) => setShelf(w >= 1100 ? 'wide' : w >= 900 ? 'mid' : 'narrow')
    read(el.getBoundingClientRect().width)
    if (typeof ResizeObserver === 'undefined') return
    obs.current = new ResizeObserver((es) => { for (const e of es) read(e.contentRect.width) })
    obs.current.observe(el)
  }, [])
  useEffect(() => () => obs.current?.disconnect(), [])
  return [shelf, ref]
}

// ── 壳 ──────────────────────────────────────────────────────────────────

/** 页头：主行 + 可选的状态芯片条。两页只有这一套壳。 */
export function MirrorChrome({ chromeRef, main, chips }: {
  chromeRef?: (el: HTMLElement | null) => void
  main: ReactNode
  chips?: ReactNode
}) {
  return (
    <div className="mc" ref={chromeRef as any}>
      <div className="mc-row">{main}</div>
      {chips && <div className="mc-chips">{chips}</div>}
    </div>
  )
}

/** 主行上的图标钮：正方形、无边框、hover 才有底。badge 用于「⧉ 标签数」。 */
export function IconBtn({ icon, label, onClick, dim, active, badge }: {
  icon: ReactNode
  label: string
  onClick?: () => void
  dim?: boolean
  active?: boolean
  badge?: number
}) {
  return (
    <button type="button" className={`mc-ib${dim ? ' is-dim' : ''}${active ? ' is-on' : ''}`}
      title={label} aria-label={label} onClick={onClick}>
      {icon}
      {badge != null && <b className="mc-ib-badge">{badge}</b>}
    </button>
  )
}

/** 状态芯片：只读一眼，点开才是面板。可横滑，永不换行。 */
export function StatusChip({ icon, text, strong, active, onClick, dot }: {
  icon?: ReactNode
  text?: string
  /** 加重的那半句（当前档位 / 模式名） */
  strong?: string
  active?: boolean
  onClick?: () => void
  /** 有值就画一颗状态点：true=绿，false=红 */
  dot?: boolean
}) {
  const cls = `mc-chip${active ? ' is-on' : ''}${onClick ? ' is-btn' : ''}`
  const inner = (
    <>
      {dot != null && <i className={`mc-dot${dot ? ' is-on' : ''}`} aria-hidden />}
      {icon}
      {text && <span>{text}</span>}
      {strong && <b>{strong}</b>}
    </>
  )
  if (!onClick) return <span className={cls}>{inner}</span>
  return <button type="button" className={cls} onClick={onClick}>{inner}</button>
}

/** ⋯ 菜单：低频动作一律进这里，主行永远只有四个目标。 */
export function MirrorMenu({ items, label }: { items: MenuProps['items']; label: string }) {
  return (
    <Dropdown trigger={['click']} placement="bottomRight" menu={{ items }}>
      <button type="button" className="mc-ib" title={label} aria-label={label}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="5" cy="12" r="1.7" fill="currentColor" stroke="none" />
          <circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none" />
          <circle cx="19" cy="12" r="1.7" fill="currentColor" stroke="none" />
        </svg>
      </button>
    </Dropdown>
  )
}

// ── 全屏 ────────────────────────────────────────────────────────────────

/**
 * 元素级全屏：把镜像这一块（工具行 + 画面）铺满显示器。
 *
 * 用元素级而不是整页全屏，是因为远端视口固定之后，观看区的宽高比决定黑边有多厚——
 * 铺满一块 16:9 的显示器，黑边正好归零。iOS Safari 只允许 <video> 全屏，那里
 * supported=false，调用方直接不摆这个入口（摆了也点不动）。
 */
export function useFullscreen(ref: RefObject<HTMLElement | null>) {
  const [on, setOn] = useState(false)
  usePageEffect(() => {
    const sync = () => setOn(!!(document.fullscreenElement || (document as any).webkitFullscreenElement))
    document.addEventListener('fullscreenchange', sync)
    document.addEventListener('webkitfullscreenchange', sync)
    return () => {
      document.removeEventListener('fullscreenchange', sync)
      document.removeEventListener('webkitfullscreenchange', sync)
    }
  }, [])
  const root: any = typeof document === 'undefined' ? null : document.documentElement
  const supported = !!(root?.requestFullscreen || root?.webkitRequestFullscreen)
  const toggle = () => {
    const doc: any = document
    if (doc.fullscreenElement || doc.webkitFullscreenElement) {
      (doc.exitFullscreen || doc.webkitExitFullscreen)?.call(doc)
      return
    }
    const node: any = ref.current
    ;(node?.requestFullscreen || node?.webkitRequestFullscreen)?.call(node)
  }
  return { on, supported, toggle }
}

// ── 主角 ────────────────────────────────────────────────────────────────

/** 把 URL 拆成「域名」和「其余」：不聚焦时人只需要认出这是哪个站，协议和路径是噪音。 */
export function splitUrl(raw: string): { host: string; rest: string } {
  const s = String(raw || '')
  if (!s) return { host: '', rest: '' }
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]*)([\s\S]*)$/i.exec(s)
  if (m) return { host: m[1], rest: m[2] }
  const i = s.search(/[/?#]/)
  return i < 0 ? { host: s, rest: '' } : { host: s.slice(0, i), rest: s.slice(i) }
}

/**
 * 胶囊主角。
 * 浏览器页：可编辑地址（失焦＝域名亮/路径灰；聚焦＝全选整条 + ✕ 清空 + 「前往」）。
 * 手机页：`readOnly` ＝ 只读 devbox（设备名 + 系统/分辨率）——它是身份不是输入。
 */
export function Omnibox({ value, onChange, onSubmit, onFocusChange, lead, trailing, sub, identity, readOnly, placeholder, goLabel }: {
  value: string
  onChange?: (v: string) => void
  onSubmit?: () => void
  onFocusChange?: (focused: boolean) => void
  /** 左徽标：连接与画质（StreamControl variant="badge"） */
  lead?: ReactNode
  /** 右端：刷新钮 / 指标数字 */
  trailing?: ReactNode
  /** 只读态右侧的次要信息（系统、分辨率） */
  sub?: string
  /** 只读态的主体：给得出更多的（可点开换一台的设备身份）就用它，代替那行纯文本 */
  identity?: ReactNode
  readOnly?: boolean
  placeholder?: string
  goLabel?: string
}) {
  const [focused, setFocused] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)
  const before = useRef(value)

  useEffect(() => { if (!focused) setDraft(value) }, [value, focused])
  // 聚焦即全选：人点地址栏九成是要整条换掉
  useLayoutEffect(() => { if (focused) { inputRef.current?.focus(); inputRef.current?.select() } }, [focused])

  const { t } = useI18n()
  const open = (v: boolean) => { setFocused(v); onFocusChange?.(v) }
  const { host, rest } = splitUrl(value)

  if (readOnly) {
    return (
      <div className="mc-omni is-readonly">
        {lead}
        {identity || <span className="mc-omni-txt" title={value}><span className="host">{value}</span></span>}
        {sub && <span className="mc-omni-sub">{sub}</span>}
        {trailing}
      </div>
    )
  }

  if (!focused) {
    return (
      <div className="mc-omni">
        {lead}
        <button type="button" className="mc-omni-txt" title={value}
          onClick={() => { before.current = value; open(true) }}>
          {value
            ? <><span className="host">{host}</span><span className="path">{rest}</span></>
            : <span className="ph">{placeholder}</span>}
        </button>
        {trailing}
      </div>
    )
  }

  return (
    <div className="mc-omni is-focus">
      <input
        ref={inputRef}
        className="mc-omni-input"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => { setDraft(e.target.value); onChange?.(e.target.value) }}
        onBlur={() => open(false)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); onSubmit?.(); open(false); inputRef.current?.blur() }
          // 改了一半不想去了：还原原地址，不留半截脏值
          if (e.key === 'Escape') { e.preventDefault(); setDraft(before.current); onChange?.(before.current); open(false); inputRef.current?.blur() }
        }}
      />
      {!!draft && (
        <button type="button" className="mc-omni-x" aria-label={t('common.clear')}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => { setDraft(''); onChange?.(''); inputRef.current?.focus() }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      )}
      <button type="button" className="mc-omni-go" onMouseDown={(e) => e.preventDefault()}
        onClick={() => { onSubmit?.(); open(false) }}>{goLabel}</button>
    </div>
  )
}

// ── 连接 + 画质：一个部件，两种密度 ──────────────────────────────────────
// 状态与档位从来是同一件事（现在多清楚 / 连没连上 / 能不能换），拆成两处必然出现
// 「超清」在屏幕上出现两次、谁也说不清哪个是状态哪个是开关。

export function StreamControl({ connected, label, quality, onQuality, level, latency, bytesPerSec, fps, size, variant = 'badge', showLabel }: {
  connected: boolean
  label: string
  quality: Quality
  onQuality: (v: Quality) => void
  level?: string          // 自适应档下后端选中的档位名，仅 auto 时有值
  latency: number | null
  bytesPerSec: number
  fps: number
  /** 画面分辨率（如 1280×720）：远端视口固定之后，「现在传的是多大一张图」是链路信息，和延迟/码率同属这里 */
  size?: string
  /** badge = omnibox 左徽标；chip = 状态芯片条上的一枚 */
  variant?: 'badge' | 'chip'
  /** 徽标里带不带「已连接」四个字（桌面带，手机只留档位名） */
  showLabel?: boolean
}) {
  const { t } = useI18n()
  const fixed = QUALITY_OPTS.find((o) => String(o.value) === String(quality))
  const now = quality === 'auto' ? (level || t('browser.quality.auto')) : t(fixed?.labelKey || 'browser.quality.auto')

  const panel = (
    <div className="mc-pop">
      <div className={`mc-pop-h${connected ? ' is-on' : ''}`}>
        <i className={`mc-dot${connected ? ' is-on' : ''}`} aria-hidden />
        <span>{label}</span>
        <span className="sp" />
        <span className="num">{latency == null ? '—' : latency + 'ms'}</span>
        <span className="num">{fmtRate(bytesPerSec)}</span>
        <span className="num">{fps}fps</span>
        {size && <span className="num">{size}</span>}
      </div>
      <Segmented
        size="small"
        className="mc-seg"
        value={String(quality)}
        onChange={(v) => onQuality(v === 'auto' ? 'auto' : Number(v))}
        options={QUALITY_OPTS.map((o) => ({ label: t(o.labelKey), value: String(o.value) }))}
      />
    </div>
  )

  const trigger = variant === 'chip'
    ? (
      <button type="button" className="mc-chip is-btn" aria-label={`${label} · ${now}`}>
        <i className={`mc-dot${connected ? ' is-on' : ''}`} aria-hidden />
        <span>{label}</span><b>{now}</b>
      </button>
    )
    : (
      <button type="button" className="mc-lead" aria-label={`${label} · ${now}`}>
        <i className={`mc-dot${connected ? ' is-on' : ''}`} aria-hidden />
        {showLabel && <span>{label} ·</span>}
        <b>{now}</b>
        <ChevronDown size={10} />
      </button>
    )

  return <Popover trigger="click" placement="bottomLeft" arrow={false} content={panel}>{trigger}</Popover>
}
