import { useEffect, useRef } from 'react'
import type { SpaceMode } from '../components/shell/useWorkspaceLayout'

export function useCanvasScroll(hasSider: boolean, mode: SpaceMode) {
  const canvasRef = useRef<HTMLDivElement>(null)
  // Reflow changes scroll height, so preserve a ratio rather than a pixel offset.
  const canvasRatio = useRef(0)
  useEffect(() => {
    if (!hasSider) return
    const el = canvasRef.current
    if (!el) return
    const on = () => {
      const room = el.scrollHeight - el.clientHeight
      if (room > 0) canvasRatio.current = el.scrollTop / room
    }
    el.addEventListener('scroll', on, { passive: true })
    return () => el.removeEventListener('scroll', on)
  }, [hasSider])
  useEffect(() => {
    const el = canvasRef.current
    if (!el || !canvasRatio.current) return
    const id = requestAnimationFrame(() => {
      const room = el.scrollHeight - el.clientHeight
      if (room > 0) el.scrollTop = Math.round(canvasRatio.current * room)
    })
    return () => cancelAnimationFrame(id)
  }, [mode])

  return canvasRef
}
