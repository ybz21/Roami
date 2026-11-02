import { useEffect, type RefObject } from 'react'

export function usePdfPinchZoom(container: RefObject<HTMLDivElement>, canvas: RefObject<HTMLCanvasElement>, scale: number, enabled: boolean, onScale: (scale: number) => void) {
  useEffect(() => {
    const element = container.current, paper = canvas.current
    if (!element || !paper || !enabled) return
    let gesture: { span: number; width: number; height: number; x: number; y: number; next: number; left: number; top: number } | undefined
    const span = (touches: TouchList) => Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY)
    const start = (event: TouchEvent) => {
      if (event.touches.length !== 2) { cancel(); return }
      if (gesture) return
      const distance = span(event.touches), rect = paper.getBoundingClientRect()
      if (!distance || !rect.width || !rect.height) return
      event.preventDefault()
      gesture = {
        span: distance, width: rect.width, height: rect.height, next: scale, left: element.scrollLeft, top: element.scrollTop,
        x: Math.min(1, Math.max(0, ((event.touches[0].clientX + event.touches[1].clientX) / 2 - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, ((event.touches[0].clientY + event.touches[1].clientY) / 2 - rect.top) / rect.height)),
      }
    }
    const move = (event: TouchEvent) => {
      if (!gesture || event.touches.length !== 2) return
      event.preventDefault()
      gesture.next = Math.min(4, Math.max(Math.min(0.25, scale), scale * span(event.touches) / gesture.span))
      // Stretch the existing bitmap during the gesture; render sharply once fingers lift.
      const width = gesture.width * gesture.next / scale, height = gesture.height * gesture.next / scale
      paper.style.width = `${width}px`; paper.style.height = `${height}px`
      const rect = paper.getBoundingClientRect()
      element.scrollLeft += rect.left + gesture.x * width - (event.touches[0].clientX + event.touches[1].clientX) / 2
      element.scrollTop += rect.top + gesture.y * height - (event.touches[0].clientY + event.touches[1].clientY) / 2
    }
    const cancel = () => {
      if (!gesture) return
      paper.style.width = `${gesture.width}px`; paper.style.height = `${gesture.height}px`
      element.scrollLeft = gesture.left; element.scrollTop = gesture.top
      gesture = undefined
    }
    const end = (event: TouchEvent) => {
      if (!gesture || event.touches.length >= 2) return
      const next = gesture.next
      if (Math.abs(next - scale) < 0.001) { cancel(); return }
      gesture = undefined
      onScale(next)
    }
    element.addEventListener('touchstart', start, { passive: false })
    element.addEventListener('touchmove', move, { passive: false })
    element.addEventListener('touchend', end, { passive: true })
    element.addEventListener('touchcancel', cancel, { passive: true })
    return () => {
      cancel()
      element.removeEventListener('touchstart', start)
      element.removeEventListener('touchmove', move)
      element.removeEventListener('touchend', end)
      element.removeEventListener('touchcancel', cancel)
    }
  }, [container, canvas, scale, enabled, onScale])
}
