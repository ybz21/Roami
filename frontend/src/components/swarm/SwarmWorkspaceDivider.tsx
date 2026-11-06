import { useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { useI18n } from '../../i18n'
import { PointerResizeShield, usePointerResize } from '../mirror/PointerResize'

export function useSwarmWorkspaceWidth(host: RefObject<HTMLDivElement>, scope: string, active: boolean) {
  const storageKey = scope + ':width'
  const [choices, setChoices] = useState<Record<string, number>>({})
  const [measured, setMeasured] = useState({ scope, available: 0, minimum: 0 })
  let saved = .4
  try { const value = Number(localStorage.getItem(storageKey)); if (value > 0 && value < 1) saved = value } catch {}
  const fraction = choices[storageKey] ?? saved
  useLayoutEffect(() => {
    const element = host.current
    if (!active || !element) return
    const measure = () => {
      const directory = element.querySelector('.swarm-conversations')
      const rail = element.querySelector('.swarm-workspace-divider')
      const available = Math.max(0, element.getBoundingClientRect().width - (directory?.getBoundingClientRect().width || 0) - (rail?.getBoundingClientRect().width || 0))
      const minimum = parseFloat(getComputedStyle(element).getPropertyValue('--sp-5')) * 14 || available / 2
      setMeasured(previous => previous.scope === scope && previous.available === available && previous.minimum === minimum ? previous : { scope, available, minimum })
    }
    measure()
    const observer = new ResizeObserver(measure); observer.observe(element)
    return () => observer.disconnect()
  }, [host, scope, active])
  const available = measured.scope === scope ? measured.available : 0
  const min = Math.min(measured.minimum, available / 2), max = Math.max(min, available - min)
  const clamp = (width: number) => Math.round(Math.min(max, Math.max(min, width)))
  return {
    width: available ? clamp(available * fraction) : undefined,
    min, max,
    resize: (width: number) => {
      if (!available) return
      const next = clamp(width) / available
      localStorage.setItem(storageKey, String(next)); setChoices(previous => ({ ...previous, [storageKey]: next }))
    },
  }
}

export default function SwarmWorkspaceDivider({ width, min, max, onResize }: { width: number; min: number; max: number; onResize: (width: number) => void }) {
  const { t } = useI18n(), { active, start } = usePointerResize()
  const guide = useRef<HTMLDivElement>(null)
  const clamp = (value: number) => Math.round(Math.max(min, Math.min(max, value)))
  return <>
    <div className="tt-split-rail swarm-workspace-divider" role="separator" aria-orientation="vertical" tabIndex={0} aria-label={t('workspace.resizeInspector')} aria-valuemin={Math.round(min)} aria-valuemax={Math.round(max)} aria-valuenow={width}
      onPointerDown={event => {
        if (event.button !== 0) return
        const initial = event.clientX, center = event.currentTarget.getBoundingClientRect().left + event.currentTarget.offsetWidth / 2
        let next = width
        if (guide.current) { guide.current.style.display = 'block'; guide.current.style.left = `${center}px` }
        start(event, {
          onMove: movement => { next = clamp(width - (movement.clientX - initial)); if (guide.current) guide.current.style.left = `${center - (next - width)}px` },
          onEnd: () => { if (guide.current) guide.current.style.display = 'none'; onResize(next) },
        })
      }}
      onKeyDown={event => {
        const next = event.key === 'ArrowLeft' ? width + 16 : event.key === 'ArrowRight' ? width - 16 : event.key === 'Home' ? min : event.key === 'End' ? max : null
        if (next == null) return
        event.preventDefault(); onResize(clamp(next))
      }} />
    <div ref={guide} className="tt-dock-guide swarm-workspace-guide" aria-hidden="true" />
    <PointerResizeShield active={active} />
  </>
}
