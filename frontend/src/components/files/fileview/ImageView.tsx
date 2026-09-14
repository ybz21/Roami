// 图片展示：适应窗口起步，能放大、能拖、能滚。
//
// 从前这里是一行 `<img maxWidth/maxHeight:100%>` 摆在 `display:grid; place-items:center` 里。
// 那个 100% 从来没生效过：栅格行不会低于 min-content，一张 900×1948 的长截图先把行撑到 1948，
// 百分比再拿这个撑开的行当基准——图按 1:1 画出来，上下各裁掉一截，而外层是 overflow:hidden，
// 于是「看着是整张，其实只看到中间那段」，既不能缩小看全貌，也没有滚动条能挪。
//
// 现在：容器 overflow:auto 自己滚，显示尺寸由 scale 算出来写死在 <img> 上（不再让浏览器
// 按百分比猜），缩放锚在指针/捏合中心上——放大时盯着的那一处不会跑掉。
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useI18n } from '../../../i18n'
import { FitIcon, ZoomInIcon, ZoomOutIcon } from '../../../icons'
import { clampScale, displaySize, fitScale, zoomBy, zoomByWheel } from './image-zoom'

type Pt = { x: number; y: number }

export function ImageView({ rawUrl, name, height = '100%' }: { rawUrl: string; name: string; height?: number | string }) {
  const { t } = useI18n()
  const boxRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const [nat, setNat] = useState({ w: 0, h: 0 })
  const [box, setBox] = useState({ w: 0, h: 0 })
  // null = 跟随窗口：分栏一拖、手机一转屏就重新收进去；一旦手动缩放过就钉在那个倍率上。
  const [scale, setScale] = useState<number | null>(null)

  useEffect(() => { setScale(null); setNat({ w: 0, h: 0 }) }, [rawUrl])
  const noteNat = useCallback((w: number, h: number) => {
    setNat((p) => (p.w === w && p.h === h ? p : { w, h }))
  }, [])

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    // 必须比对旧值再 setState：ResizeObserver 的回调里无条件写新对象，会和「滚动条出现→
    // 容器变窄→重新布局」互相触发，一路滚成 React #185（更新深度超限）。
    const measure = () => setBox((p) => (p.w === el.clientWidth && p.h === el.clientHeight ? p : { w: el.clientWidth, h: el.clientHeight }))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fit = fitScale(nat, box)
  const eff = scale ?? fit
  const { w: dispW, h: dispH } = displaySize(nat, eff)
  const overflowing = dispW > box.w + 1 || dispH > box.h + 1

  // 缩放后把滚动位置补回去，让锚点（指针所在的那个像素）停在原处。
  // 记的是「图内相对位置 + 屏幕坐标」，与居中方式无关——margin:auto 留的空白变了也照样对得上。
  const anchor = useRef<{ ix: number; iy: number } & Pt | null>(null)
  const effRef = useRef(eff)
  effRef.current = eff
  useLayoutEffect(() => {
    const a = anchor.current
    anchor.current = null
    const el = boxRef.current, img = imgRef.current
    if (!a || !el || !img) return
    const r = img.getBoundingClientRect()
    el.scrollLeft += r.left + a.ix * r.width - a.x
    el.scrollTop += r.top + a.iy * r.height - a.y
  }, [dispW, dispH])

  const zoomTo = useCallback((next: number, at?: Pt) => {
    const img = imgRef.current
    if (img && at) {
      const r = img.getBoundingClientRect()
      const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
      anchor.current = {
        ix: r.width ? clamp01((at.x - r.left) / r.width) : 0.5,
        iy: r.height ? clamp01((at.y - r.top) / r.height) : 0.5,
        ...at,
      }
    }
    setScale(next)
  }, [])

  const center = (): Pt => {
    const r = boxRef.current?.getBoundingClientRect()
    return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : { x: 0, y: 0 }
  }
  const step = (dir: 1 | -1, at?: Pt) => zoomTo(zoomBy(effRef.current, dir), at || center())
  // 适应 ⇄ 1:1 一键来回：看全貌和看像素是看图的两种模式，不该靠连点档位一档档凑过去。
  const atActual = Math.abs(eff - 1) < 0.001
  const toggleActual = (at?: Pt) => { if (atActual) setScale(null); else zoomTo(1, at || center()) }

  // 滚轮与捏合都要 preventDefault，React 的 onWheel/onTouchMove 是被动监听，改不了默认行为。
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return // 裸滚轮留给上下滚动
      e.preventDefault()
      zoomTo(zoomByWheel(effRef.current, e.deltaY), { x: e.clientX, y: e.clientY })
    }
    let base = 0, span = 0
    const spanOf = (ts: TouchList) => Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY)
    const midOf = (ts: TouchList): Pt => ({ x: (ts[0].clientX + ts[1].clientX) / 2, y: (ts[0].clientY + ts[1].clientY) / 2 })
    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 2) return
      span = spanOf(e.touches)
      base = effRef.current
    }
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length !== 2 || !span) return
      e.preventDefault() // 否则这一捏被浏览器当成整页缩放
      zoomTo(clampScale(base * spanOf(e.touches) / span), midOf(e.touches))
    }
    const onTouchEnd = (e: TouchEvent) => { if (e.touches.length < 2) span = 0 }
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
    }
  }, [zoomTo])

  // 鼠标按住拖着挪（手指有原生惯性滚动，不抢）
  const drag = useRef<{ id: number; x: number; y: number; l: number; tp: number } | null>(null)
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = boxRef.current
    if (!el || e.pointerType === 'touch' || e.button !== 0 || !overflowing) return
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, l: el.scrollLeft, tp: el.scrollTop }
    el.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current, el = boxRef.current
    if (!d || !el || d.id !== e.pointerId) return
    el.scrollLeft = d.l - (e.clientX - d.x)
    el.scrollTop = d.tp - (e.clientY - d.y)
  }
  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (drag.current?.id !== e.pointerId) return
    boxRef.current?.releasePointerCapture(e.pointerId)
    drag.current = null
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === '+' || e.key === '=') { e.preventDefault(); step(1) }
    else if (e.key === '-') { e.preventDefault(); step(-1) }
    else if (e.key === '0') { e.preventDefault(); setScale(null) }
  }

  // useCallback 不能省：ref 回调每次渲染换一个新函数，React 就会在每次渲染时先 null 再挂载，
  // 里面那次 setNat 于是变成「渲染 → setState → 渲染」的死循环。
  const measured = useCallback((el: HTMLImageElement | null) => {
    imgRef.current = el
    // 缓存命中时 onLoad 早在 React 绑上去之前就烧掉了，这里补读一次（同 MentionedImage）。
    if (el?.complete && el.naturalWidth) noteNat(el.naturalWidth, el.naturalHeight)
  }, [noteNat])

  const pct = `${Math.round(eff * 100)}%`
  return (
    <div className="tt-imgview" style={{ height }}>
      <div
        ref={boxRef}
        className={`tt-imgview-canvas${overflowing ? ' pan' : ''}`}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onDoubleClick={(e) => toggleActual({ x: e.clientX, y: e.clientY })}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <img
          ref={measured}
          src={rawUrl}
          alt={name}
          draggable={false}
          style={{ width: dispW, height: dispH }}
          onLoad={(e) => noteNat(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)}
        />
      </div>
      <div className="tt-imgview-bar">
        <button type="button" className="tt-act ico" aria-label={t('file.imgZoomOut')} title={t('file.imgZoomOut')} onClick={() => step(-1)}><ZoomOutIcon /></button>
        <button type="button" className="tt-act" aria-label={t('file.imgScale', { pct })} title={atActual ? t('file.imgFit') : t('file.imgActual')} onClick={() => toggleActual()}>{pct}</button>
        <button type="button" className="tt-act ico" aria-label={t('file.imgZoomIn')} title={t('file.imgZoomIn')} onClick={() => step(1)}><ZoomInIcon /></button>
        <button type="button" className="tt-act ico" aria-label={t('file.imgFit')} title={t('file.imgFit')} onClick={() => setScale(null)}><FitIcon /></button>
        <span className="dim">{nat.w ? `${nat.w}×${nat.h}` : ''}</span>
      </div>
    </div>
  )
}
