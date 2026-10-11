import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useI18n } from '../../i18n'
import { RefreshIcon } from '../../icons'

type Pull = { x: number; y: number; root: Element; target: Element; active: boolean }

function atTop(target: Element, root: Element): boolean {
  for (let node: Element | null = target; node; node = node.parentElement) {
    if (node.scrollHeight > node.clientHeight + 1 && node.scrollTop > 1) return false
    if (node === root) break
  }
  return true
}

export default function MobilePullRefresh({ enabled }: { enabled: boolean }) {
  const { t } = useI18n()
  const pull = useRef<Pull | null>(null)
  const distance = useRef(0)
  const [shown, setShown] = useState(0)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    if (!enabled) return
    const start = (event: TouchEvent) => {
      if (event.touches.length !== 1) { pull.current = null; setShown(0); return }
      if (refreshing) return
      const target = event.target
      if (!(target instanceof Element) || target.closest('input, textarea, select, [contenteditable="true"], [role="slider"], .xterm')) return
      const root = target.closest('.tt-canvas, [data-mobile-refresh-root]')
      if (!root || !atTop(target, root)) return
      pull.current = { x: event.touches[0].clientX, y: event.touches[0].clientY, root, target, active: false }
    }
    const move = (event: TouchEvent) => {
      const p = pull.current
      if (!p || event.touches.length !== 1) return
      const dx = event.touches[0].clientX - p.x
      const dy = event.touches[0].clientY - p.y
      if (Math.abs(dx) > Math.max(12, dy * 1.2)) { pull.current = null; setShown(0); return }
      if (!p.active && (dy < 12 || Math.abs(dx) > dy)) {
        if (Math.abs(dx) > 12 || dy < -12) pull.current = null
        return
      }
      if (!atTop(p.target, p.root) || dy < 0) { pull.current = null; setShown(0); return }
      p.active = true
      distance.current = Math.min(96, dy * .48)
      setShown(distance.current)
    }
    const end = () => {
      const ready = pull.current?.active && distance.current >= 64
      pull.current = null
      distance.current = 0
      if (ready) {
        setRefreshing(true)
        setShown(64)
        window.setTimeout(() => location.reload(), 160)
      } else setShown(0)
    }
    const cancel = () => { pull.current = null; distance.current = 0; setShown(0) }
    document.addEventListener('touchstart', start, { passive: true })
    document.addEventListener('touchmove', move, { passive: true })
    document.addEventListener('touchend', end, { passive: true })
    document.addEventListener('touchcancel', cancel, { passive: true })
    return () => {
      document.removeEventListener('touchstart', start)
      document.removeEventListener('touchmove', move)
      document.removeEventListener('touchend', end)
      document.removeEventListener('touchcancel', cancel)
    }
  }, [enabled, refreshing])

  if (!enabled) return null
  const label = refreshing ? t('mobile.refresh.refreshing') : shown >= 64 ? t('mobile.refresh.release') : t('mobile.refresh.pull')
  return <div className={`tt-mobile-pull-refresh${refreshing ? ' refreshing' : ''}`} style={{ '--pull-distance': `${shown}px` } as CSSProperties}
    role="status" aria-live="polite" aria-hidden={!shown}>
    <RefreshIcon size={16} /><span>{label}</span>
  </div>
}
