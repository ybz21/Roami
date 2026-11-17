import { usePageEffect } from '../../page-activity'
// 手机覆盖层的返回键（13 §4.3）：二级页与 sheet 都应该被安卓物理返回键收掉，
// 而不是把整个路由退掉、覆盖层还留在屏幕上。
//
// 应用是 hash 路由（App.tsx 只听 hashchange），所以覆盖层压的那条 history 记录
// **必须是同一个 URL**：`pushState(state, '', location.href)` 不触发 hashchange，
// 路由完全看不见它。
//
// 三条容易漏的规则，缺一条就退化成「按一次返回没反应，再按一次直接退出」：
//   ① UI 关闭（← / × / 遮罩 / Esc）也要 history.back() 把那条记录退掉，否则留下死记录；
//   ② 一次 popstate 只退一帧——嵌套的 diff → Git → sheet 才能按一次退一层；
//   ③ 栈非空时若发生 hashchange（路由真的变了），所有存活帧一起关掉：
//      覆盖层在路由变化之后一定是过期的。
//
// **不要**把标记塞进 history.state 再读回来：App 的 setHashParams 每次开关终端标签
// 都会 replaceState 一次，标记会被抹掉。模块级 LIFO 栈是唯一事实来源。
//
// 「我们自己发的 back」用一个计数器记，不是每帧一个 closing 标志：计数器与具体是
// 哪一帧无关，帧被复用/换掉都不影响吞噬判定。
// 配套的是 scheduleRetire——退帧的 back() 延到微任务发，同一 tick 内又压帧就复用那条
// 记录。两者一起才扛得住 StrictMode 的 mount→unmount→mount（实测不做的话表现为
// 「按一次返回退了两页」）。
//
// 已知缺口：antd 的 Dropdown/Popover/Modal 门户不在这个栈里，返回键会越过它们、
// 关掉底下的二级页。影响最大的两处（GitPanel 的 diff 详情、WorktreePanel 的对比）
// 各自单独挂了本 hook；通用的「先关最上层 antd 弹层」桥接留待后续。
import { useEffect, useRef } from 'react'

export type Frame = { id: number; onDismiss: () => void }

// ── 纯栈逻辑（导出给测试；组件侧只用下面的 hook）─────────────────────
const stack: Frame[] = []
let seq = 0
/** 我们自己发出、还没回来的 history.back() 条数 */
let pendingSelfBack = 0

export function stackSize(): number { return stack.length }

/**
 * 退帧的 back() **延到微任务**再发，中间新压了帧就直接复用那条记录。
 *
 * 这是 StrictMode 的解药：开发态 mount→unmount→mount 是同步跑完的，
 * 立刻发 back() 的话它是异步落地的，而第二次 mount 已经又 push 了一条——
 * 两者交错会把当前位置挪到别人的记录上，表现成「按一次返回退了两页」。
 * 复用记录之后，双挂载净效果是 0 次 history 操作。
 */
let pendingRetire: (() => void) | null = null
let flushScheduled = false
function scheduleRetire(back: () => void) {
  pendingRetire = back
  if (flushScheduled) return
  flushScheduled = true
  queueMicrotask(() => {
    flushScheduled = false
    const run = pendingRetire
    pendingRetire = null
    if (!run) return // 被新帧复用了
    pendingSelfBack++
    run()
  })
}

/** 打开：压一帧并返回它的 id。`push` 由调用方注入，测试里可以替身。 */
export function pushFrame(onDismiss: () => void, push: () => void): number {
  const f: Frame = { id: ++seq, onDismiss }
  stack.push(f)
  if (pendingRetire) pendingRetire = null // 复用上一帧还没退掉的那条记录
  else push()
  return f.id
}

/**
 * UI 关闭 / 卸载：把这一帧退掉。
 * 帧立刻出栈；只有它在栈顶时才动 history——被埋在下面说明别的东西已经先导航过了，
 * 这时候 back() 退掉的会是别人的记录。
 */
export function retireFrame(id: number, back: () => void) {
  const i = stack.findIndex((f) => f.id === id)
  if (i < 0) return // 已经被 popstate 或 hashchange 收走了
  const top = i === stack.length - 1
  stack.splice(i, 1)
  if (!top) return
  scheduleRetire(back)
}

/** popstate：退一帧。返回被关掉的帧；是我们自己发的 back 则吞掉并返回 null。 */
export function handlePop(): Frame | null {
  if (pendingSelfBack > 0) { pendingSelfBack--; return null }
  const f = stack.pop()
  if (!f) return null
  f.onDismiss()
  return f
}

/** 路由变了：所有覆盖层一起关，栈清空（不碰 history——路由自己已经动过了） */
export function handleHashChange() {
  if (!stack.length) return
  const live = stack.splice(0, stack.length)
  for (const f of live) f.onDismiss()
}

/** 仅供测试：清干净模块级状态 */
export function resetStack() {
  stack.length = 0
  seq = 0
  pendingSelfBack = 0
  pendingRetire = null
}

// ── 全局监听：整个应用只挂一次 ────────────────────────────────────
let wired = false
function wire() {
  if (wired || typeof window === 'undefined') return
  wired = true
  window.addEventListener('popstate', () => { handlePop() })
  window.addEventListener('hashchange', () => { handleHashChange() })
}

/**
 * 覆盖层打开期间接管返回键。
 *
 * @param enabled 覆盖层是否处于打开态。传 false 时本 hook 什么都不做。
 * @param onDismiss 关闭回调，必须幂等——路由兜底会直接调它。
 */
export function useBackDismiss(enabled: boolean, onDismiss: () => void): void {
  // 回调放 ref：栈里存的是打开那一刻的闭包，不能让它拿到过期的 state
  const cb = useRef(onDismiss)
  cb.current = onDismiss

  useEffect(() => {
    if (!enabled) return
    wire()
    const id = pushFrame(() => cb.current(), () => {
      history.pushState(history.state, '', location.href)
    })
    return () => { retireFrame(id, () => history.back()) }
  }, [enabled])

  // Escape 与返回键同义：桌面没有物理返回键，但有 Esc
  usePageEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') cb.current() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}
