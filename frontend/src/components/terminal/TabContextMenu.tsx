import { cloneElement, useEffect, useRef, useState, type HTMLAttributes, type ReactElement } from 'react'
import { Dropdown, type MenuProps } from 'antd'

export function TabContextMenu({ children, menu }: {
  children: ReactElement<HTMLAttributes<HTMLElement>>
  menu: MenuProps
}) {
  const [open, setOpen] = useState(false)
  const [point, setPoint] = useState({ x: 0, y: 0 })
  const popupRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const closeOutside = (event: Event) => {
      if (event.target instanceof Node && popupRef.current?.contains(event.target)) return
      setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside, true)
    document.addEventListener('contextmenu', closeOutside, true)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside, true)
      document.removeEventListener('contextmenu', closeOutside, true)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])
  return <>
    {cloneElement(children, { onContextMenu: event => {
      event.preventDefault()
      event.stopPropagation()
      children.props.onContextMenu?.(event)
      const rect = event.currentTarget.getBoundingClientRect()
      setPoint(event.clientX || event.clientY ? { x: event.clientX, y: event.clientY } : { x: rect.left, y: rect.bottom })
      setOpen(true)
    } })}
    <Dropdown
      // Point-aligned context menus close on ancestor scroll, even while entering the menu.
      trigger={[]}
      open={open}
      onOpenChange={setOpen}
      popupRender={content => <div ref={popupRef}>{content}</div>}
      menu={{ ...menu, onClick: event => {
        event.domEvent.stopPropagation()
        setOpen(false)
        menu.onClick?.(event)
      } }}
    ><span aria-hidden style={{ position: 'fixed', left: point.x, top: point.y, width: 1, height: 1, pointerEvents: 'none' }} /></Dropdown>
  </>
}
