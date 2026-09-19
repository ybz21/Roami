// HTML 展示：不在前端拼 DOM，直接 iframe 后端服务代理(/api/file/serve/<绝对路径> 以
// text/html 直出)，脚本/样式按原样运行；绝对路径进 URL 路径 → 同目录相对引用(css/js/img)
// 能被浏览器解析到同目录资源。key 绑 mtime → 文件被外部(cc/codex)改动时 iframe 自动重载。
import { useCallback, useEffect, useRef } from 'react'
import { useThemeMode } from '../../../theme'
import { recallFrameScroll, rememberFrameScroll, type FrameScroll } from './view-state-memory'

const TRANSPARENT = new Set(['', 'transparent', 'rgba(0, 0, 0, 0)'])
// 标记这份文档的 color-scheme 是我们改的：'derived' 按页面自己的底色定，'canvas' 是页面
// 没底色、连底色一起由我们铺。换主题时据此重来，不会把自己铺的底当成页面自带的。
const MARK = 'ttmuxScheme'

// 画布底色的明暗——只需分两档，用感知亮度近似（0.5 为界）即可。
function isDarkColor(rgb: string) {
  const [r, g, b] = (rgb.match(/[\d.]+/g) || []).map(Number)
  if ([r, g, b].some((v) => !Number.isFinite(v))) return false
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5
}

export function HtmlView({ path, rawUrl, name, mtime, height }: {
  /** 滚动位置按它记：切走再切回来还在原处 */
  path: string
  rawUrl: string
  name: string
  mtime?: number
  height: string
}) {
  const { mode } = useThemeMode()
  const ref = useRef<HTMLIFrameElement>(null)

  // iframe 里是另一份文档：外面的 color-scheme 不跨帧传，给 iframe 元素铺的底也盖不住它的
  // 画布。于是深色页面在黑主题下右边挂一条白滚动条，只给卡片上色、body 不铺底的（设计稿
  // 最典型）更是每道 gutter 都漏白。serve 与前端同源 → 载入后进去按页面自己的底色定
  // color-scheme（滚动条/默认文字色跟着页面走），页面没底色时才铺主题底色、跟应用主题走。
  // 页面自己声明过 color-scheme 的，说明它已经想好了，一概不碰。
  const applyScheme = useCallback(() => {
    try {
      const doc = ref.current?.contentDocument
      const root = doc?.documentElement
      if (!root) return
      const mark = root.dataset[MARK]
      const style = getComputedStyle(root)
      if (!mark && style.colorScheme !== 'normal') return
      const own = mark === 'canvas' ? '' : [style.backgroundColor, doc.body && getComputedStyle(doc.body).backgroundColor]
        .find((c) => c && !TRANSPARENT.has(c)) || ''
      root.style.colorScheme = own ? (isDarkColor(own) ? 'dark' : 'light') : mode
      root.style.background = own ? '' : getComputedStyle(document.documentElement).getPropertyValue('--bg-base').trim()
      root.dataset[MARK] = own ? 'derived' : 'canvas'
    } catch {
      // 同源以外（不该发生）读不到 contentDocument，保持页面原样
    }
  }, [mode])

  useEffect(applyScheme, [applyScheme]) // 已经载入的 iframe 跟着主题切换重来一遍

  // 记住看到哪儿。iframe 是另一份文档，标签切走时整个销毁、切回来从头载，位置全丢。
  // serve 与前端同源，进得去：窗口滚动和页面自己滚的容器（设计稿常见 html 不滚、内层滚）
  // 都记，容器按 DOM 路径认——同一份文件重载出来的 DOM 一样，路径就对得上。
  const key = 'html:' + path
  const scrolledEls = useRef(new Set<Element>())
  const snapshot = useCallback((): FrameScroll | null => {
    try {
      const win = ref.current?.contentWindow
      const doc = ref.current?.contentDocument
      if (!win || !doc) return null
      const els = Array.from(scrolledEls.current)
        .filter((el) => el.isConnected && (el.scrollTop > 0 || el.scrollLeft > 0))
        .map((el) => ({ sel: domPath(el), top: el.scrollTop, left: el.scrollLeft }))
      return { x: win.scrollX, y: win.scrollY, els }
    } catch { return null }
  }, [])
  const save = useCallback(() => { const s = snapshot(); if (s && (s.y > 0 || s.x > 0 || s.els.length)) rememberFrameScroll(key, s) }, [key, snapshot])
  useEffect(() => () => save(), [save]) // 卸载（标签切走）时存最后一眼

  const restore = useCallback(() => {
    const want = recallFrameScroll(key)
    const win = ref.current?.contentWindow
    const doc = ref.current?.contentDocument
    if (!want || !win || !doc) return
    let done = false
    const apply = () => {
      if (done) return true
      const root = doc.documentElement
      const canY = root.scrollHeight - root.clientHeight >= want.y
      if (!canY) return false
      win.scrollTo(want.x, want.y)
      for (const e of want.els) {
        const el = doc.querySelector(e.sel)
        if (el) { el.scrollTop = e.top; el.scrollLeft = e.left; scrolledEls.current.add(el) }
      }
      done = true
      return true
    }
    if (apply()) return
    // 图片、字体、脚本还在把页面撑高：盯着长高再对，两秒不到就算了
    const ro = new ResizeObserver(() => { if (apply()) ro.disconnect() })
    if (doc.body) ro.observe(doc.body)
    ro.observe(doc.documentElement)
    setTimeout(() => { done = true; ro.disconnect() }, 2000)
  }, [key])

  const onLoad = useCallback(() => {
    applyScheme()
    try {
      const doc = ref.current?.contentDocument
      const win = ref.current?.contentWindow
      if (!doc || !win) return
      // scroll 不冒泡，捕获阶段在 document 上收：谁滚了就记谁
      doc.addEventListener('scroll', (ev) => {
        const t = ev.target
        if (t instanceof Element) scrolledEls.current.add(t)
        save()
      }, true)
      restore()
    } catch {
      // 非同源读不到，跳过
    }
  }, [applyScheme, restore, save])

  return (
    <iframe
      key={mtime}
      ref={ref}
      title={name}
      src={rawUrl}
      onLoad={onLoad}
      style={{ display: 'block', width: '100%', height, border: 0, background: 'var(--bg-base)' }}
    />
  )
}

// 元素到 body 的路径：`body > div:nth-child(2) > main:nth-child(1)`。同一份文件重载出来的 DOM 一样，路径稳定。
function domPath(el: Element): string {
  const parts: string[] = []
  let cur: Element | null = el
  while (cur && cur.tagName !== 'BODY' && cur.tagName !== 'HTML') {
    const parent: Element | null = cur.parentElement
    const idx = parent ? Array.from(parent.children).indexOf(cur) + 1 : 1
    parts.unshift(`${cur.tagName.toLowerCase()}:nth-child(${idx})`)
    cur = parent
  }
  return 'body > ' + parts.join(' > ')
}
