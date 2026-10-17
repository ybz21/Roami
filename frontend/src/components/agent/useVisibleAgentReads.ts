import { useEffect, type RefObject } from 'react'
import { api } from '../../api'

export function useVisibleAgentReads(cid: string, root: RefObject<HTMLDivElement>, messageEvents: string, onRead: () => void) {
  useEffect(() => {
    if (!cid || !root.current || !globalThis.IntersectionObserver) return
    let candidate = 0, acknowledged = 0, stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const flush = async () => {
      if (stopped || document.visibilityState !== 'visible' || candidate <= acknowledged) return
      const cursor = candidate
      try { await api('POST', `/agent/conversations/${encodeURIComponent(cid)}/read`, { eventId: cursor }); acknowledged = Math.max(acknowledged, cursor); if (!stopped) onRead() } catch { /* Retried on the next visible observation. */ }
    }
    const blockers = new MutationObserver(() => { if (document.visibilityState === 'visible') observe() })
    const observer = new IntersectionObserver((entries) => {
      if (document.visibilityState !== 'visible') return
      for (const entry of entries) if (entry.isIntersecting) {
        const r = entry.intersectionRect
        const hit = document.elementFromPoint?.(r.left + r.width / 2, r.top + r.height / 2)
        if (hit && (hit === entry.target || entry.target.contains(hit))) candidate = Math.max(candidate, Number((entry.target as HTMLElement).dataset.eventId) || 0)
        else if (hit) blockers.observe(hit.closest('.ant-modal-wrap, .ant-modal-mask') ?? hit, { attributes: true, attributeFilter: ['class', 'style'] })
      }
      clearTimeout(timer); timer = setTimeout(() => { void flush() }, 250)
    }, { root: root.current, threshold: 0.5 })
    const observe = () => { observer.disconnect(); root.current?.querySelectorAll('[data-event-id]').forEach((element) => observer.observe(element)) }
    const visibility = () => { if (document.visibilityState === 'visible') observe() }
    const mutation = new MutationObserver(() => { if (document.visibilityState === 'visible') observe() })
    mutation.observe(document.body, { attributes: true, attributeFilter: ['class'] })
    observe(); document.addEventListener('visibilitychange', visibility)
    return () => { stopped = true; clearTimeout(timer); observer.disconnect(); mutation.disconnect(); blockers.disconnect(); document.removeEventListener('visibilitychange', visibility) }
  }, [cid, root, messageEvents, onRead])
}
