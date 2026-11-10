// 一棵组件树，两种容器（13 §6 手机 / 14 panels-desktop.html 桌面）。
//
// Git 面板和 Worktree 的问题从来不在面板本体，全在**容器**：
//   · 手机上是桌面抽屉：420/520 的浮层压在底栏上、不吃安全区、返回键不认它；
//   · 桌面上是 fixed 浮层：不参与 Shell 的尺寸契约，只会「盖」不会「让」——
//     实测 1440 会话页开 Git，终端从 605 被盖到只剩 185。
//
// 所以这里只换壳：
//   手机 → MobileSubPage（整页 + ← + 物理返回键）
//   桌面 → Inspector 列（Shell 的第三列，可拖、可记忆、不带遮罩）
//
// 桌面不带遮罩是有意的：遮罩 = 模态 = 「先关掉才能干别的」，而 Git 面板恰恰要边看边干。
// 代价是「点外面不会关」，所以面板必须常驻一个关闭入口（GitPanel/WorktreePanel 都有）。
import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useLayout } from '../../layout'
import MobileSubPage from '../MobileSubPage'
import { claimInspector, releaseInspector, useInspectorSlot } from './inspector'

export default function AdaptivePanel({ open, title, onClose, layer, children, desktopHeader }: {
  open: boolean
  /** 手机二级页的页头标题；桌面由面板自己的头承担 */
  title: ReactNode
  onClose: () => void
  /** 'session' = 从会话全屏覆盖层里唤起，手机档要换更高的层 */
  layer?: 'page' | 'session'
  children: ReactNode
  desktopHeader?: ReactNode
}) {
  const { phone } = useLayout()

  // 登记槽位：只有栈顶那个可见。从 Git 面板里还能唤起 Worktree（WorktreePanel 就渲染在
  // GitPanel 的子树里），两个都 portal 进同一个槽会叠在一起——所以非栈顶的**藏起来**。
  //
  // 是藏不是卸载：卸载 Git 会连它子树里的 Worktree 一起卸掉 → Worktree 释放槽位 →
  // Git 又成栈顶重新挂载（wtOpen 已随卸载丢失）→ 看起来就是「点了 Worktree 没反应」。
  // 藏起来还顺带保住了滚动位置与展开态，**关掉栈顶自然露出下面那个**，
  // 「从 Git 跳 Worktree 再回来」因此是免费的。
  const [id, setId] = useState(0)
  useEffect(() => {
    if (!open || phone) return
    const claimed = claimInspector()
    setId(claimed)
    return () => { releaseInspector(claimed); setId(0) }
  }, [open, phone])
  const { slot, isTop } = useInspectorSlot(id)

  if (!open) return null
  // 没有槽位就退回全屏二级页。**「开着却什么都不画」永远不是一个可接受的状态**：
  // 槽位由 Shell 的 Inspector 列提供，而那一列只在有侧栏的档位里存在——档位切换、
  // 或者 Workspace 与无终端分支互换的那一帧，槽位可能还没登记回来，原来的
  // `return null` 就把面板画成了一片空白（按钮亮着、右边什么也没有）。
  if (phone || !slot) {
    return <MobileSubPage title={title} onBack={onClose} layer={layer}>{children}</MobileSubPage>
  }
  return createPortal(
    <div style={{
      flex: 1, minHeight: 0, minWidth: 0, flexDirection: 'column',
      display: isTop ? 'flex' : 'none',
    }}>
      {desktopHeader}
      {children}
    </div>,
    slot,
  )
}
