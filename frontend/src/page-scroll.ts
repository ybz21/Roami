import { useViewRef } from './view-state'
import { useLayoutEffect, useRef, type RefObject, type UIEvent } from 'react'

export function usePageScroll(root: RefObject<HTMLElement>, active: boolean) {
  const positions = useViewRef<Record<string, { top: number; left: number }>>('scroll.positions', {})
  const restoring = useRef(false), cancel = useRef(() => {})
  useLayoutEffect(() => {
    if (!active || !root.current || !Object.keys(positions.current).length) return
    const pending = new Map(Object.entries(positions.current))
    restoring.current = true
    const finish = () => { mutation.disconnect(); resize?.disconnect(); clearTimeout(timeout); pending.clear(); restoring.current = false }
    const apply = () => {
      for (const [path, position] of pending) {
        let element: Element | undefined = root.current || undefined
        for (const index of path ? path.split('/') : []) element = element?.children[Number(index)]
        if (!(element instanceof HTMLElement)) continue
        if (element.scrollHeight - element.clientHeight < position.top || element.scrollWidth - element.clientWidth < position.left) continue
        element.scrollTop = position.top; element.scrollLeft = position.left; pending.delete(path)
      }
      if (!pending.size) finish()
    }
    const mutation = new MutationObserver(apply)
    const resize = globalThis.ResizeObserver ? new ResizeObserver(apply) : null
    const timeout = setTimeout(finish, 2000)
    cancel.current = finish
    mutation.observe(root.current, { childList: true, subtree: true })
    resize?.observe(root.current)
    apply()
    return finish
  }, [active, root])
  const onScrollCapture = (event: UIEvent<HTMLElement>) => {
    if (!active || restoring.current || !root.current || !(event.target instanceof HTMLElement)) return
    const element = event.target
    if (!root.current.contains(element) || element.closest('.monaco-editor, .xterm')) return
    const path: number[] = []
    for (let node: Element = element; node !== root.current; node = node.parentElement!) {
      if (!node.parentElement) return
      path.unshift(Array.prototype.indexOf.call(node.parentElement.children, node))
    }
    const key = path.join('/')
    const next = { ...positions.current }
    if (element.scrollTop || element.scrollLeft) next[key] = { top: element.scrollTop, left: element.scrollLeft }
    else delete next[key]
    positions.current = next
  }
  return { onScrollCapture, onPointerDownCapture: () => cancel.current(), onWheelCapture: () => cancel.current(), onTouchStartCapture: () => cancel.current() }
}
