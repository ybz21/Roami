// 文件标签的「看到哪儿」记忆：滚动位置 / Monaco 视图状态，按文件路径各记一份。
//
// 非当前标签的 FileView 会整个卸载（二十个标签只留一个 Monaco 实例），切回来是重新挂载，
// 读到一半的文档就弹回顶上。这里把位置记在内存里，重挂时对回去。只活在这一次页面里：
// 刷新后文件本身可能已经变了，硬对回旧位置反而莫名其妙。
import { useEffect, useRef, type UIEvent } from 'react'

const MAX = 200 // 超过按最久没用的淘汰——一次会话里翻二百个文件的人也不会记得第一个滚到哪
const scrolls = new Map<string, number>()
const editorViews = new Map<string, unknown>()

function touch<T>(m: Map<string, T>, key: string, v: T) {
  m.delete(key)
  m.set(key, v)
  if (m.size > MAX) m.delete(m.keys().next().value as string)
}

/** iframe 里那份文档的滚动：窗口本身 + 页面内部自己滚的容器（按 DOM 路径认） */
export type FrameScroll = { x: number; y: number; els: { sel: string; top: number; left: number }[] }
const frames = new Map<string, FrameScroll>()
export function rememberFrameScroll(key: string, s: FrameScroll) { touch(frames, key, s) }
export function recallFrameScroll(key: string): FrameScroll | undefined { return frames.get(key) }

export function rememberScroll(key: string, top: number) { touch(scrolls, key, top) }
export function recallScroll(key: string): number { return scrolls.get(key) || 0 }
export function rememberEditorView(key: string, state: unknown) { if (state) touch(editorViews, key, state) }
export function recallEditorView(key: string): unknown { return editorViews.get(key) }
export function forgetViewState(key: string) { scrolls.delete(key); editorViews.delete(key); frames.delete(key) }
/** 测试用 */
export function resetViewStateMemory() { scrolls.clear(); editorViews.clear(); frames.clear() }

/**
 * 给一个 overflow:auto 的滚动容器用：挂上时把记着的位置对回去，滚动时记下来。
 * 内容常常是迟到的（Markdown 组件懒加载、大表格分帧画），刚挂上时容器还没那么高，
 * 一次 scrollTop 赋值会被夹成 0——所以盯着内容长高，够高了再对，用户自己一滚就不再插手。
 */
export function useRememberedScroll(key: string) {
  const ref = useRef<HTMLDivElement>(null)
  const settled = useRef(false)
  useEffect(() => {
    const el = ref.current
    settled.current = false
    const want = recallScroll(key)
    if (!el || want <= 0) { settled.current = true; return }
    let stop = false
    const tryRestore = () => {
      if (stop || settled.current) return true
      if (el.scrollHeight - el.clientHeight >= want) {
        el.scrollTop = want
        settled.current = true
        return true
      }
      return false
    }
    if (tryRestore()) return
    const ro = new ResizeObserver(() => { if (tryRestore()) ro.disconnect() })
    for (const child of Array.from(el.children)) ro.observe(child)
    ro.observe(el)
    // 两秒还没长到那么高（文件变短了、加载失败），就别等了
    const t = setTimeout(() => { settled.current = true; ro.disconnect() }, 2000)
    return () => { stop = true; clearTimeout(t); ro.disconnect() }
  }, [key])
  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    // 还在等内容长高时的滚动是我们自己的（或夹到 0 的），不算用户意图
    if (!settled.current) { if (el.scrollTop > 0) settled.current = true; else return }
    rememberScroll(key, el.scrollTop)
  }
  return { ref, onScroll }
}
