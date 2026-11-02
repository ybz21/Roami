import { useEffect, useRef } from 'react'
import { useLayout } from '../../layout'

export function useOnboardingFieldFocus() {
  const { phone, keyboard } = useLayout(), ref = useRef<HTMLDivElement>(null)
  const reveal = () => {
    const field = document.activeElement
    if (!phone || !(field instanceof HTMLElement) || !ref.current?.contains(field)) return
    const pane = ref.current.closest('.onboarding-scroll')
    if (!pane) return
    const footer = field.closest('form')?.querySelector('.agent-settings-save')
    const bottom = Math.min(pane.getBoundingClientRect().bottom, footer?.getBoundingClientRect().top ?? Infinity)
    const gap = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--tap')) || 0
    const delta = field.getBoundingClientRect().bottom + gap - bottom
    if (delta > 0) pane.scrollTo({ top: pane.scrollTop + delta, behavior: 'instant' })
  }
  useEffect(() => { if (!phone || !keyboard) return; const frame = requestAnimationFrame(reveal); return () => cancelAnimationFrame(frame) }, [phone, keyboard])
  return { ref, onFocusCapture: () => { if (phone) requestAnimationFrame(reveal) } }
}
