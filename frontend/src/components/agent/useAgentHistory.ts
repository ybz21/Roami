import { useLayoutEffect, useRef, useState, type RefObject } from 'react'
import type { AgentTimelineGroup } from './agent-timeline'

const PAGE = 24

export function useAgentHistory(scope: string, entries: AgentTimelineGroup[], focus: string, root: RefObject<HTMLDivElement>) {
  const [range, setRange] = useState({ scope, first: '' })
  const anchor = useRef<{ element: Element; top: number } | null>(null)
  const remembered = range.scope === scope ? entries.findIndex(entry => entry.id === range.first) : -1
  let start = remembered >= 0 ? remembered : Math.max(0, entries.length - PAGE)
  const focused = focus ? entries.findIndex(entry => entry.id === focus) : -1
  if (focused >= 0) start = Math.min(start, Math.max(0, focused - 2))
  const expand = () => {
    const pane = root.current
    if (!pane || !start || anchor.current) return
    const element = pane.querySelector('.agent-thread')?.firstElementChild
    if (element) anchor.current = { element, top: element.getBoundingClientRect().top }
    setRange({ scope, first: entries[Math.max(0, start - PAGE)].id })
  }
  useLayoutEffect(() => {
    const pane = root.current, previous = anchor.current
    anchor.current = null
    if (pane && previous?.element.isConnected && range.scope === scope) pane.scrollTop += previous.element.getBoundingClientRect().top - previous.top
    if (remembered < 0 && entries[start]) setRange({ scope, first: entries[start].id })
    if (pane && start && pane.clientHeight > 0 && pane.scrollHeight <= pane.clientHeight) expand()
  }, [scope, start, entries, remembered])
  return { entries: entries.slice(start), expand: () => { if ((root.current?.scrollTop ?? Infinity) < 160) expand() } }
}
