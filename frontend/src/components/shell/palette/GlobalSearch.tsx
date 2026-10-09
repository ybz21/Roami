// 全局搜索的挂载点：快捷键 + 开合状态 + 面板本体。
//
// 独立成一个组件是因为搜索**必须处处都能唤起**。第一版把这套逻辑塞在顶栏里，于是：
// 手机没有顶栏 → 搜不了；新标签打开的单终端页（#/term/xxx）也没有顶栏 → 同样搜不了，
// 按 ⌘K 毫无反应。现在三处都挂这一个组件，入口各自给（顶栏那枚框、手机「更多」里
// 那一行、纯快捷键）。
//
// 键盘监听走**捕获阶段**：xterm 自己在 textarea 上挂了 keydown 并且会 stopPropagation，
// 冒泡阶段的监听在终端聚焦时根本收不到 ⌘K——这正是「在终端页按不出搜索」的原因。
import { useEffect, useState, useRef } from 'react'
import { matchHotkey, useKeybindings } from '../keybindings'
import { CommandPalette } from './CommandPalette'
import type { PaletteActions, PaletteItem } from './types'

/** 任何地方都能发这个事件来开面板（顶栏按钮、手机「更多」、导航轨的放大镜） */
export const OPEN_PALETTE_EVENT = 'tt-open-palette'

export const openPalette = () => window.dispatchEvent(new Event(OPEN_PALETTE_EVENT))

export function GlobalSearch({ items, actions, dir }: {
  items: PaletteItem[]
  actions: PaletteActions
  dir?: string
}) {
  const [open, setOpen] = useState(false)
  const searchKey = useKeybindings().search.key
  const keyRef = useRef(searchKey); keyRef.current = searchKey

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null
      const typing = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
      const inTerm = !!el?.closest?.('.xterm')
      if (matchHotkey(e, keyRef.current)) {
        e.preventDefault()
        // 终端聚焦时还要拦住冒泡，否则 xterm 会把 ⌃K 当作 readline 的「删到行尾」发下去，
        // 面板开着的同时命令行被截断了半截
        e.stopPropagation()
        setOpen(true)
        return
      }
      // `/` 是无修饰键：正在打字或在终端里时绝不能抢
      if (e.key === '/' && !typing && !inTerm && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault()
        setOpen(true)
      }
    }
    const onOpen = () => setOpen(true)
    // 捕获阶段：要赶在 xterm 的 keydown 之前（见文件头注释）
    window.addEventListener('keydown', onKey, true)
    window.addEventListener(OPEN_PALETTE_EVENT, onOpen)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      window.removeEventListener(OPEN_PALETTE_EVENT, onOpen)
    }
  }, [])

  if (!open) return null
  return <CommandPalette items={items} actions={actions} dir={dir} onClose={() => setOpen(false)} />
}
