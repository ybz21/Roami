import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

type Drag = { key: string; target: string; pointer: number; startY: number; x: number; y: number; active: boolean; order: string }

export function useAggregationMemberDrag(list: RefObject<HTMLOListElement>, order: string, disabled: boolean, onMove: (key: string, target: string) => void) {
  const session = useRef<Drag | null>(null), frame = useRef<number | null>(null)
  const [drag, setDrag] = useState<{ key: string; target: string } | null>(null)
  const commit = useRef(onMove)
  commit.current = onMove
  const stop = () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current)
    frame.current = null; session.current = null; setDrag(null)
  }
  useEffect(() => {
    if (disabled || session.current && session.current.order !== order) stop()
  }, [disabled, order])
  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current)
    session.current = null
  }, [])

  const locate = () => {
    const current = session.current, root = list.current
    if (!current?.active || !root) return
    const scroll = root.closest<HTMLElement>('.tt-routing-editor, .tt-routing-main')
    if (!scroll) return
    const bounds = scroll.getBoundingClientRect(), listBounds = root.getBoundingClientRect()
    const inside = current.x >= Math.max(bounds.left, listBounds.left) && current.x <= Math.min(bounds.right, listBounds.right) && current.y >= Math.max(bounds.top, listBounds.top) && current.y <= Math.min(bounds.bottom, listBounds.bottom)
    let target = current.key
    if (inside) {
      const rows = [...root.querySelectorAll<HTMLElement>('[data-member-key]')]
      const nearest = rows.reduce<HTMLElement | null>((best, row) => {
        const distance = (node: HTMLElement) => { const r = node.getBoundingClientRect(); return Math.abs(current.y - (r.top + r.height / 2)) }
        return !best || distance(row) < distance(best) ? row : best
      }, null)
      target = nearest?.dataset.memberKey || target
    }
    if (target !== current.target) {
      current.target = target
      setDrag({ key: current.key, target })
    }
  }
  const scrollFrame = () => {
    const current = session.current, root = list.current
    if (!current?.active || !root) return
    const scroll = root.closest<HTMLElement>('.tt-routing-editor, .tt-routing-main')
    if (scroll) {
      const bounds = scroll.getBoundingClientRect(), edge = Number.parseFloat(getComputedStyle(root).getPropertyValue('--tap')) || 44
      if (current.x >= bounds.left && current.x <= bounds.right) {
        const distance = current.y < bounds.top + edge ? current.y - bounds.top - edge : current.y > bounds.bottom - edge ? current.y - bounds.bottom + edge : 0
        scroll.scrollTop += Math.max(-edge / 3, Math.min(edge / 3, distance / 4))
      }
    }
    locate()
    frame.current = requestAnimationFrame(scrollFrame)
  }
  const start = (event: ReactPointerEvent<HTMLButtonElement>, key: string) => {
    if (disabled || event.button !== 0 || event.isPrimary === false || session.current) return
    event.preventDefault()
    event.currentTarget.focus({ preventScroll: true })
    event.currentTarget.setPointerCapture(event.pointerId)
    session.current = { key, target: key, pointer: event.pointerId, startY: event.clientY, x: event.clientX, y: event.clientY, active: false, order }
  }
  const move = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const current = session.current
    if (!current || current.pointer !== event.pointerId) return
    current.x = event.clientX; current.y = event.clientY
    if (!current.active && Math.abs(event.clientY - current.startY) < 6) return
    event.preventDefault()
    if (!current.active) {
      current.active = true
      setDrag({ key: current.key, target: current.target })
      frame.current = requestAnimationFrame(scrollFrame)
    }
    locate()
  }
  const finish = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const current = session.current
    if (!current || current.pointer !== event.pointerId) return
    current.x = event.clientX; current.y = event.clientY; locate()
    const { key, target, active } = current
    stop()
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (active && key !== target && !disabled && current.order === order) commit.current(key, target)
  }
  return { drag, start, move, finish, cancel: stop }
}
