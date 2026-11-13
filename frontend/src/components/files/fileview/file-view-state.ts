// File locations use the same workspace store and its bounded cache.
import { useEffect, useRef, type UIEvent } from 'react'

import { useMemo } from 'react'
import { useViewScope } from '../../../view-state'
import type { ViewStateScope } from '../../../workspace-state'

export type FrameScroll = { x: number; y: number; els: { sel: string; top: number; left: number }[] }

export function createFileViewState(scope: ViewStateScope) {
  const positions = scope.child('positions')
  return {
    rememberScroll: (key: string, top: number) => positions.child(key).set('scroll', top, 'cache'),
    recallScroll: (key: string) => positions.child(key).get<number>('scroll') || 0,
    rememberEditorView: (key: string, value: unknown) => { if (value) positions.child(key).set('editor', JSON.parse(JSON.stringify(value)), 'cache') },
    recallEditorView: (key: string) => positions.child(key).get<unknown>('editor'),
    rememberFrameScroll: (key: string, value: FrameScroll) => positions.child(key).set('frame', value, 'cache'),
    recallFrameScroll: (key: string) => positions.child(key).get<FrameScroll>('frame'),
    forgetViewState: (key: string) => positions.child(key).clear(),
  }
}
export function useFileViewState() {
  const scope = useViewScope()
  return useMemo(() => createFileViewState(scope), [scope])
}

/**
 * 给一个 overflow:auto 的滚动容器用：挂上时把记着的位置对回去，滚动时记下来。
 * 内容常常是迟到的（Markdown 组件懒加载、大表格分帧画），刚挂上时容器还没那么高，
 * 一次 scrollTop 赋值会被夹成 0——所以盯着内容长高，够高了再对，用户自己一滚就不再插手。
 */
export function useRememberedScroll(key: string) {
  const { recallScroll, rememberScroll } = useFileViewState()
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
  }, [key, recallScroll])
  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    // 还在等内容长高时的滚动是我们自己的（或夹到 0 的），不算用户意图
    if (!settled.current) { if (el.scrollTop > 0) settled.current = true; else return }
    rememberScroll(key, el.scrollTop)
  }
  return { ref, onScroll }
}
