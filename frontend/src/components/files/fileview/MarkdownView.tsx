// Markdown 渲染：react-markdown（懒加载）+ 本地图片/链接解析。
import { type MouseEvent } from 'react'
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
  return (
    <div ref={scroll.ref} onScroll={scroll.onScroll} style={{ height, overflow: 'auto', padding: pad }}>
      <Markdown accent={accent} resolveHref={resolveHref} onLinkClick={onLinkClick}>{content}</Markdown>
    </div>
  )
}
