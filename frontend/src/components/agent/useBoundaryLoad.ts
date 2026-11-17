import { usePageEffect } from '../../page-activity'
import { useRef, type RefObject } from 'react'

export function useBoundaryLoad(container: RefObject<HTMLElement>, load: () => void, enabled: boolean, edge: 'start' | 'end' = 'end') {
  const action = useRef(load); action.current = load
  const available = useRef(enabled); available.current = enabled
  const consumed = useRef(false), touchPoint = useRef<{ x: number; y: number } | null>(null)
  usePageEffect(() => {
    let root = container.current
    if (!root) return
    while (root.parentElement && !['auto', 'scroll'].includes(getComputedStyle(root).overflowY)) root = root.parentElement
    if (root === document.body || root === document.documentElement) root = container.current!
    const element = root
    let frame = 0, armed = false
    const check = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const intent = armed
        armed = false
        if (!intent || !available.current || document.hidden) return
        const distance = edge === 'start' ? element.scrollTop : element.scrollHeight - element.clientHeight - element.scrollTop
        if (distance > 48) return
        consumed.current = true
        action.current()
      })
    }
    const wheel = (event: WheelEvent) => {
      if ((edge === 'start' && event.deltaY >= 0) || (edge === 'end' && event.deltaY <= 0)) return
      armed = true; check()
    }
    const touch = (event: TouchEvent) => { consumed.current = false; const point = event.touches[0]; touchPoint.current = point ? { x: point.clientX, y: point.clientY } : null }
    const move = (event: TouchEvent) => {
      const origin = touchPoint.current, point = event.touches[0]
      if (consumed.current || !origin || !point) return
      const dy = point.clientY - origin.y, dx = point.clientX - origin.x
      if (Math.abs(dy) < 8 || Math.abs(dx) > Math.abs(dy) || (edge === 'start' ? dy < 0 : dy > 0)) return
      armed = true; check()
    }
    const key = (event: KeyboardEvent) => {
      if ((event.target as Element)?.closest('input,textarea,select,[contenteditable="true"]')) return
      if (!(edge === 'start' ? ['ArrowUp', 'PageUp', 'Home'] : ['ArrowDown', 'PageDown', 'End', ' ']).includes(event.key)) return
      armed = true; check()
    }
    element.addEventListener('wheel', wheel, { passive: true })
    element.addEventListener('touchstart', touch, { passive: true })
    element.addEventListener('touchmove', move, { passive: true })
    element.addEventListener('keydown', key)
    element.addEventListener('scroll', check, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      element.removeEventListener('wheel', wheel)
      element.removeEventListener('touchstart', touch)
      element.removeEventListener('touchmove', move)
      element.removeEventListener('keydown', key)
      element.removeEventListener('scroll', check)
    }
  }, [container, edge])
}
