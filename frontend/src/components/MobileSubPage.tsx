// 移动端二级页：Android Fragment 式全屏覆盖层——列表页点某项后，详情在上层整页展开。
// 传 title 则带「← 返回 + 标题」顶栏；不传则无顶栏（内容自带返回入口，如 FileView 的 onBack）。
//
// 三件事是这一层的契约（13 §4.3 / §8.1）：
//   ① **portal 到 body**。开了容器查询的页面（`.tt-canvas[data-cq="on"]`）上，
//      `container-type` 会让 canvas 成为 fixed 后代的包含块——不 portal 的话，
//      从那种页面里唤起的二级页会被裁进 canvas 而不是铺满视口。
//   ② **四边吃安全区**，底部再与软键盘取大：`max(var(--kb), var(--safe-b))`。
//      iOS Safari 没有 VirtualKeyboard API，--kb 只能从 visualViewport 推，所以取大
//      而不是相加，键盘收起时至少还留安全区。
//   ③ **接管返回键**：安卓物理返回应该收掉这一层，而不是把整个路由退掉。
// 层级：--z-subpage(90) 盖过底栏(50)；从会话全屏(100)里唤起时传 layer="session"
// 换成 --z-session-sub(110)，否则 portal 之后不再嵌套在会话那个层叠上下文里，会被盖住。
import { type ReactNode, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import { useEdgeSwipe } from './shell/edge-swipe'
import { useBackDismiss } from './shell/useBackDismiss'
import { ChevronLeft } from '../icons'

export default function MobileSubPage({ title, onBack, action, manageHistory = true, layer = 'page', children }: {
  title?: ReactNode
  onBack: () => void
  action?: { label: string; icon: ReactNode; onClick: () => void }
  manageHistory?: boolean
  /** 'session' = 从会话全屏覆盖层里唤起（Git / 文件） */
  layer?: 'page' | 'session'
  children: ReactNode
}) {
  const { t } = useI18n()
  useBackDismiss(manageHistory, onBack)
  const rootRef = useRef<HTMLDivElement>(null)
  useEdgeSwipe(rootRef, { onBack })

  const node = (
    <div ref={rootRef} style={{
      position: 'fixed', inset: 0, background: 'var(--bg-base)',
      zIndex: `var(${layer === 'session' ? '--z-session-sub' : '--z-subpage'})` as unknown as number,
      display: 'flex', flexDirection: 'column',
      paddingTop: 'var(--safe-t)', paddingLeft: 'var(--safe-l)', paddingRight: 'var(--safe-r)',
      paddingBottom: 'max(var(--kb), var(--safe-b))',
    }}>
      {title !== undefined && (
        <div className="tt-mobile-subpage-head">
          <button type="button" onClick={onBack} aria-label={t('common.back')}>
            <ChevronLeft size={20} />
          </button>
          <strong>{title}</strong>
          {action && <button type="button" onClick={action.onClick} aria-label={action.label}>{action.icon}</button>}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {children}
      </div>
    </div>
  )
  return typeof document === 'undefined' ? node : createPortal(node, document.body)
}
