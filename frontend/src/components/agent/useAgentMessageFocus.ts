import { useEffect, useRef, type RefObject, type MutableRefObject } from 'react'

export function useAgentMessageFocus(root: RefObject<HTMLDivElement>, conversation: string, branch: string, message: string, messageIds: string, stick: MutableRefObject<boolean>) {
  const applied = useRef({ key: '', done: false })
  useEffect(() => {
    const key = [conversation, branch, message].join(':')
    if (applied.current.key !== key) applied.current = { key, done: false }
    if (!message || applied.current.done || !root.current) return
    const element = [...root.current.querySelectorAll<HTMLElement>('[data-message-id]')].find((item) => item.dataset.messageId === message)
    if (!element) return
    const pane = root.current
    const align = () => {
      const target = element.getBoundingClientRect(), viewport = pane.getBoundingClientRect()
      pane.scrollTop += target.top + target.height / 2 - viewport.top - viewport.height / 2
      stick.current = false
    }
    const observer = globalThis.ResizeObserver ? new ResizeObserver(align) : null
    const stop = () => { applied.current.done = true; observer?.disconnect() }
    align()
    observer?.observe(element)
    if (pane.firstElementChild) observer?.observe(pane.firstElementChild)
    pane.addEventListener('wheel', stop, { passive: true })
    pane.addEventListener('touchstart', stop, { passive: true })
    document.addEventListener('pointerdown', stop)
    document.addEventListener('keydown', stop)
    return () => {
      observer?.disconnect()
      pane.removeEventListener('wheel', stop)
      pane.removeEventListener('touchstart', stop)
      document.removeEventListener('pointerdown', stop)
      document.removeEventListener('keydown', stop)
    }
  }, [root, conversation, branch, message, messageIds, stick])
}
