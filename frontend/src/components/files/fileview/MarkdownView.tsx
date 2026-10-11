// Markdown 渲染：react-markdown（懒加载）+ 本地图片/链接解析。
import { type KeyboardEvent, type MouseEvent, useRef } from 'react'
import Markdown from '../../markdown/Markdown'
import { useRememberedScroll } from './view-state-memory'

export function MarkdownView({ path, content, accent, height, pad, resolveHref, onLinkClick }: {
  /** 滚动位置按它记：切走再切回来还在原处 */
  path: string
  content: string
  accent: string
  height: string
  pad?: string
  resolveHref: (href: string, kind: 'link' | 'image') => string
  onLinkClick: (href: string, ev: MouseEvent<HTMLAnchorElement>) => void
}) {
  const scroll = useRememberedScroll('md:' + path)
  const contentRef = useRef<HTMLDivElement>(null)
  const selectAll = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'a' || !contentRef.current) return
    event.preventDefault()
    const range = document.createRange()
    range.selectNodeContents(contentRef.current)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
  }
  return (
    <div ref={scroll.ref} className="tt-markdown-preview" tabIndex={0} onKeyDown={selectAll} onScroll={scroll.onScroll}
      style={{ height, overflow: 'auto', padding: pad, userSelect: 'text', WebkitUserSelect: 'text' }}>
      <div ref={contentRef}><Markdown accent={accent} resolveHref={resolveHref} onLinkClick={onLinkClick}>{content}</Markdown></div>
    </div>
  )
}
