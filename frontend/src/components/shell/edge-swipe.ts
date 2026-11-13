import { usePageEffect } from '../../page-activity'
// 手机上的边缘横滑（24 稿 §3 #5）：左边缘右滑 = 返回，右边缘左滑 = 下一面（会话页的「改动」）。
// 安卓手势导航自己吃掉边缘、走的是物理返回（useBackDismiss 那条），这里管的是三键导航的机器
// 和 iOS 主屏 PWA（没有 Safari 的侧滑）。捕获阶段截住，起手在边缘的那根手指终端就不再当滚动处理。
import { type RefObject } from 'react'

const EDGE = 24
const THRESHOLD = 70
const SLOP = 40

export function useEdgeSwipe(ref: RefObject<HTMLElement | null>, opts: { onBack?: () => void; onForward?: () => void; enabled?: boolean }) {
  const { onBack, onForward, enabled = true } = opts
  usePageEffect(() => {
    const el = ref.current
    if (!el || !enabled || (!onBack && !onForward)) return
    let track: { x: number; y: number; side: 'l' | 'r' } | null = null
    const start = (e: TouchEvent) => {
      if (e.touches.length !== 1) { track = null; return }
      const t = e.touches[0]
      const w = window.innerWidth
      if (onBack && t.clientX <= EDGE) track = { x: t.clientX, y: t.clientY, side: 'l' }
      else if (onForward && t.clientX >= w - EDGE) track = { x: t.clientX, y: t.clientY, side: 'r' }
      else track = null
      if (track) e.stopPropagation()
    }
    const move = (e: TouchEvent) => {
      if (!track) return
      const t = e.touches[0]
      const dx = t.clientX - track.x, dy = t.clientY - track.y
      if (Math.abs(dy) > SLOP) { track = null; return }
      e.stopPropagation()
      if (e.cancelable) e.preventDefault()
      if (track.side === 'l' && dx > THRESHOLD) { track = null; onBack?.() }
      else if (track.side === 'r' && dx < -THRESHOLD) { track = null; onForward?.() }
    }
    const end = () => { track = null }
    const o = { capture: true, passive: false } as AddEventListenerOptions
    el.addEventListener('touchstart', start, o)
    el.addEventListener('touchmove', move, o)
    el.addEventListener('touchend', end, o)
    el.addEventListener('touchcancel', end, o)
    return () => {
      el.removeEventListener('touchstart', start, o)
      el.removeEventListener('touchmove', move, o)
      el.removeEventListener('touchend', end, o)
      el.removeEventListener('touchcancel', end, o)
    }
  }, [ref, onBack, onForward, enabled])
}
