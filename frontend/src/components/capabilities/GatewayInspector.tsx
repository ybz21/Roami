import { useEffect, useRef, type ReactNode } from 'react'
import { useLayout } from '../../layout'
import BackButton from '../BackButton'
import MobileSubPage from '../MobileSubPage'

export default function GatewayInspector({ title, onClose, busy, children }: { title: string; onClose: () => void; busy?: boolean; children: ReactNode }) {
  const { phone } = useLayout(), body = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!phone) body.current?.querySelector<HTMLElement>('input, textarea, button')?.focus({ preventScroll: true })
  }, [phone, title])
  const content = <div className="tt-gateway-editor" ref={body} onKeyDown={event => { if (event.key === 'Escape' && !event.defaultPrevented && !busy) { event.stopPropagation(); onClose() } }}>{children}</div>
  return phone ? <MobileSubPage title={title} onBack={() => { if (!busy) onClose() }} search={false}>{content}</MobileSubPage> : <aside className="tt-gateway-inspector" aria-label={title}><header><BackButton disabled={busy} onClick={onClose} /><h3>{title}</h3></header>{content}</aside>
}
