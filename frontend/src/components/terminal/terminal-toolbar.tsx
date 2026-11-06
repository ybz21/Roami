// 会话导航栏（标签条 + 工具条）的图标与控件。
//
// 与左侧主导航同一套线性语言：24 viewBox、currentColor 描边、无 emoji（emoji 各平台字形不一，
// 在深色栏里显得廉价且无法跟随强调色）。样式在 index.css 的 .tt-tabs / .tt-tbar 段。
import { type ReactNode } from 'react'
import Projects from '../projects/Projects'
import { useLayout } from '../../layout'
import { Tooltip } from 'antd'

const tIcon = (paths: any, size = 15) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{paths}</svg>
)
export const TI = {
  collapse: tIcon(<><path d="M20 4.5v15" /><path d="M4.5 12h10" /><path d="m10 7 5 5-5 5" /></>),
  close: tIcon(<><path d="m7 7 10 10" /><path d="M17 7 7 17" /></>, 12),
  tmux: tIcon(<><rect x="3" y="4.5" width="18" height="15" rx="2.5" /><path d="m7.5 10 2.5 2-2.5 2" /><path d="M13 14.5h3.5" /></>),
  newTab: tIcon(<><path d="M13.5 4h6.5v6.5" /><path d="M20 4 12 12" /><path d="M18.5 14.5V18a2.5 2.5 0 0 1-2.5 2.5H6A2.5 2.5 0 0 1 3.5 18V8A2.5 2.5 0 0 1 6 5.5h3.5" /></>),
  rename: tIcon(<><path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z" /><path d="m14.5 6.5 3 3" /></>),
  bellOn: tIcon(<><path d="M18 9.5a6 6 0 1 0-12 0c0 4.5-2 6-2 6h16s-2-1.5-2-6" /><path d="M10.2 19.5a2.2 2.2 0 0 0 3.6 0" /></>),
  bellOff: tIcon(<><path d="M18 9.5a6 6 0 0 0-9.1-5.1" /><path d="M6 9.5c0 4.5-2 6-2 6h12.5" /><path d="M10.2 19.5a2.2 2.2 0 0 0 3.6 0" /><path d="m3.5 3.5 17 17" /></>),
  folder: tIcon(<><path d="M3 7.5A2 2 0 0 1 5 5.5h4l2 2h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></>),
  git: tIcon(<><circle cx="6" cy="6" r="2.3" /><circle cx="6" cy="18" r="2.3" /><circle cx="18" cy="8" r="2.3" /><path d="M6 8.3v7.4" /><path d="M18 10.3a6 6 0 0 1-6 6H8.3" /></>),
  mic: tIcon(<><rect x="9.2" y="3" width="5.6" height="11" rx="2.8" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" /><path d="M12 18v3" /></>),
  scrollUp: tIcon(<><path d="M4.5 4.5h15" /><path d="M12 20V9" /><path d="m7.5 13.5 4.5-4.5 4.5 4.5" /></>),
  toBottom: tIcon(<><path d="M4.5 19.5h15" /><path d="M12 4v11" /><path d="m7.5 10.5 4.5 4.5 4.5-4.5" /></>),
  // Focus = 四角向外扩，返回分栏 = 四角向内收
  focus: tIcon(<><path d="M4 9V4h5" /><path d="M20 9V4h-5" /><path d="M4 15v5h5" /><path d="M20 15v5h-5" /></>),
  unfocus: tIcon(<><path d="M9 4v5H4" /><path d="M15 4v5h5" /><path d="M9 20v-5H4" /><path d="M15 20v-5h5" /></>),
  dpad: tIcon(<><polyline points="12 5 12 19" /><polyline points="5 12 19 12" /></>),
  back: tIcon(<><line x1="20" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></>),
  caret: tIcon(<polyline points="6 9 12 15 18 9" />),
  dots: tIcon(<><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></>),
  redraw: tIcon(<><path d="M20 12a8 8 0 1 1-2.6-5.9" /><path d="M20.5 4v5h-5" /></>),
  reconnect: tIcon(<><path d="M10.4 13.6a4.2 4.2 0 0 0 6 0l2.4-2.4a4.2 4.2 0 0 0-6-6l-1.4 1.4" /><path d="M13.6 10.4a4.2 4.2 0 0 0-6 0l-2.4 2.4a4.2 4.2 0 0 0 6 6l1.4-1.4" /></>),
}
// 工具条按钮：默认安静（无框），开启态是「软色底 + 主色字」，样式全在 index.css 的 .tt-tbtn.on。
// tone 只选哪一支强调色（会话蓝 / Codex 绿），不再由行内 style 拼颜色——
// 原来写的是 `${tone}1f` / `${tone}59`，而 tone 传进来的是 `var(--accent)`：
// 拼出来是无效值，底色被整个丢掉，border-color 反倒落成满强度实线，
// 于是「开启」在界面上是一枚突兀的蓝色描边圈。
export function TBtn({ icon, label, on, tone = 'accent', title, pressed, className = '', onClick, onMouseDown }: {
  icon?: ReactNode; label?: ReactNode; on?: boolean; tone?: 'accent' | 'ok'; title?: ReactNode
  onClick?: () => void; onMouseDown?: (e: React.MouseEvent) => void
  pressed?: boolean
  className?: string
}) {
  const { coarse } = useLayout()
  const btn = (
    <button type="button" className={`tt-tbtn${on ? ' on' : ''}${tone === 'ok' ? ' ok' : ''}${label ? '' : ' tt-ico'} ${className}`}
      onClick={onClick} onMouseDown={onMouseDown}
      aria-pressed={pressed}
      aria-label={typeof title === 'string' ? title : undefined}
      title={coarse && typeof title === 'string' ? title : undefined}>
      {icon}{label != null && <span>{label}</span>}
    </button>
  )
  // 粗指针不挂 Tooltip：触屏没有 mouseleave，浮层收不掉，而 .ant-tooltip 是
  // pointer-events: auto，会把它盖住那片区域后续的点全吞掉（同 Projects 的 ActBtn）。
  return title && !coarse ? <Tooltip title={title} mouseEnterDelay={0.35}>{btn}</Tooltip> : btn
}
