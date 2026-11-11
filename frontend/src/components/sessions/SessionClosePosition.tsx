import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import './session-close-position.css'

export function SessionClosePosition({ children }: { children: ReactNode }) {
  const element = useRef<HTMLDivElement>(null)
  const initialHeight = useRef<number | null>(null)
  const [position, setPosition] = useState({ height: 0, offset: 0 })
  useLayoutEffect(() => {
    const node = element.current
    if (!node) return
    const measure = () => {
      const height = node.offsetHeight
      if (!height) return
      initialHeight.current ??= height
      const offset = (initialHeight.current - height) / 2
      setPosition(previous => previous.height === initialHeight.current && previous.offset === offset ? previous : { height: initialHeight.current!, offset })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [children])
  // Keep the footer where it first appeared as the centered dialog grows upward.
  return <div ref={element} className="tt-session-close-position" style={{ transform: `translateY(${position.offset}px)`, maxHeight: position.height ? `calc(50dvh + ${position.height / 2}px - var(--sp-5))` : 'calc(100dvh - var(--sp-5) * 2)' }}>{children}</div>
}
