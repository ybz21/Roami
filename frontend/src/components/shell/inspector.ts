// Inspector 槽位（14 桌面面板稿 panels-desktop.html）。
//
// Git / Worktree 这些右侧面板此前是 `position:fixed` 浮层，**不参与 Shell 的尺寸契约**——
// 浮层只会「盖」，不会「让」。实测 1440 上会话页开 Git：终端从 605 被盖到只剩 185。
// 现在它们成为 Shell 的第三列，和 Dock 同级。
//
// 难点是「谁来渲染」：Git 面板挂在 TerminalPane 里（Dock 深处）、项目页那份挂在页面里，
// 而列要由 Workspace 画。与其把内容一路 prop 提上去，不如沿用本仓库已有的
// 模块级小表 + useSyncExternalStore 套路（session-label / session-project / intents）：
//   · Workspace 提供槽位 DOM，登记到这里；
//   · AdaptivePanel 在桌面档把自己 portal 进槽位；
//   · Workspace 订阅「有没有人占用」，决定列的宽度与那条 rail。
//
// 栈而不是单值：从 Git 面板里还能唤起 Worktree（GitPanel 内部就渲染着 WorktreePanel）。
// 只有栈顶那个真正渲染，**关掉栈顶会自然露出下面那个**——「从 Git 跳 Worktree 再回来」
// 因此是免费的，不需要额外做返回箭头。
import { useSyncExternalStore } from 'react'

let slot: HTMLElement | null = null
/** 登记顺序即栈序；只有最后一个渲染 */
let stack: number[] = []
let seq = 0
const listeners = new Set<() => void>()
export const INSPECTOR_REVEAL_EVENT = 'roami:reveal-inspector'
export function revealInspector() { window.dispatchEvent(new Event(INSPECTOR_REVEAL_EVENT)) }

function emit() { listeners.forEach((fn) => fn()) }
function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Workspace 挂载/卸载槽位 DOM */
export function setInspectorSlot(el: HTMLElement | null) {
  if (slot === el) return
  slot = el
  emit()
}

export function claimInspector(): number {
  const id = ++seq
  stack.push(id)
  emit()
  return id
}

export function releaseInspector(id: number) {
  const next = stack.filter((x) => x !== id)
  if (next.length === stack.length) return
  stack = next
  emit()
}

type Snapshot = { slot: HTMLElement | null; top: number }
let snap: Snapshot = { slot: null, top: 0 }
function read(): Snapshot {
  const top = stack.length ? stack[stack.length - 1] : 0
  if (snap.slot !== slot || snap.top !== top) snap = { slot, top }
  return snap
}

/** 面板侧：拿槽位 + 自己是不是栈顶 */
export function useInspectorSlot(id: number): { slot: HTMLElement | null; isTop: boolean } {
  const s = useSyncExternalStore(subscribe, read, read)
  return { slot: s.slot, isTop: s.top === id }
}

/** Shell 侧：有没有人占着 */
export function useInspectorOpen(): boolean {
  return useSyncExternalStore(subscribe, () => stack.length > 0, () => false)
}

/**
 * 面板内部要求「这一列至少这么宽」。
 *
 * 文件抽屉里点开一个文件会分成两栏，而 420 的默认列宽分完只剩两百出头的预览——
 * 读不了代码，等于这个分栏白做。面板自己知道要多宽，但列宽在 Shell 手里，
 * 于是走这条与槽位同样的模块级小道（别为这一个数把 setInspectorWidth 一路 prop 下去）。
 *
 * 只加宽不缩窄：用户拖出来的更宽值一直算数，收起预览也不把列缩回去——
 * 面板宽度是他的选择，不该被开合文件反复改。
 */
let wantWidth = 0
export function requestInspectorWidth(px: number) {
  const next = Math.max(0, Math.round(px))
  if (wantWidth === next) return
  wantWidth = next
  emit()
}

export function useInspectorWantWidth(): number {
  return useSyncExternalStore(subscribe, () => wantWidth, () => 0)
}

/**
 * Shell 反过来告诉面板：你要的宽度我给不了，只给到这么多。
 *
 * 面板判断「用户是不是拖了外把手」靠的是量自己的宽度和请求值对不上（见 InspectorLayers
 * 的 settle）。它分不清「用户拖窄的」和「Shell 钳窄的」——窗口缩小一次，钳出来的宽度
 * 就被当成用户的新偏好存下来，窗口再拉宽也回不去了。钳到多少报回来，那一档就别当拖动。
 * 0 = 没钳，要多少给多少。
 */
let cappedAt = 0
export function reportInspectorCap(px: number) { cappedAt = Math.round(px) }
export function inspectorCappedAt(): number { return cappedAt }

/** 仅供测试 */
export function resetInspector() {
  slot = null
  stack = []
  seq = 0
  wantWidth = 0
  cappedAt = 0
  snap = { slot: null, top: 0 }
}
