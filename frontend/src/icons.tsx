// 全站通用图标（设计系统 §2「箭头等符号用 SVG 图标，不要 → ← ⌃ 这类文字符号」）。
//
// 之前按钮上散着三套东西：文字符号（✕ × ▾ ▸ ← ↑ ↓ ✓ ○ ◁ ▭ ■ ⚠）、emoji（🔄 📎 🤖 👤 📢）、
// 以及各文件自画的 SVG。前两类在手机字体上会跟标点混作一团、粗细跟不上线性图标，
// 而且同一个动作在不同页面长得不一样——关闭在 Dock 是 ✕、在浏览器标签是 ×、在文件页签又是另一个。
//
// 这里是唯一的出处：24×24 viewBox、stroke=currentColor、1.8 线宽、圆头圆角，
// 与 file-icons.tsx / git/parts.tsx 既有图标同款，颜色一律继承父级（不写死）。
import type { ReactNode } from 'react'

type P = { size?: number }

const line = (d: ReactNode, size: number, sw = 1.8) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" aria-hidden>{d}</svg>
)
const solid = (d: ReactNode, size: number) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden>{d}</svg>
)

// ── 基础动作 ──
export const CloseIcon = ({ size = 14 }: P) => line(<><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>, size, 2)
export const CheckIcon = ({ size = 14 }: P) => line(<path d="m5 12.5 4.5 4.5L19 7" />, size, 2.2)
export const PlusIcon = ({ size = 14 }: P) => line(<path d="M12 5v14M5 12h14" />, size, 2.2)
export const CopyIcon = ({ size = 13 }: P) => line(<><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M15 5.5A2.5 2.5 0 0 0 12.5 4H6a2 2 0 0 0-2 2v6.5A2.5 2.5 0 0 0 6.5 15" /></>, size)
export const RefreshIcon = ({ size = 14 }: P) => line(
  <><path d="M21 12a9 9 0 0 1-15 6.7" /><path d="M3 12A9 9 0 0 1 18 5.3" /><path d="M18 2v4h-4" /><path d="M6 22v-4h4" /></>, size)
export const MoreIcon = ({ size = 15 }: P) => solid(
  <><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></>, size)
export const PaperclipIcon = ({ size = 15 }: P) => line(
  <path d="M20 11.5 12.4 19a4.6 4.6 0 0 1-6.5-6.5l7.8-7.8a3 3 0 0 1 4.3 4.3l-7.7 7.7a1.5 1.5 0 0 1-2.1-2.1l7-7" />, size)
/** 继续 / 恢复：原来写作 ▶ */
export const PlayIcon = ({ size = 12 }: P) => solid(<path d="M8 5.5v13l11-6.5Z" />, size)
export const StopIcon = ({ size = 12 }: P) => solid(<rect x="6" y="6" width="12" height="12" rx="2" />, size)
/** 进全屏 / 退全屏：四角箭头向外、向内。原来在 App.tsx 里现画一对 */
export const FullscreenIcon = ({ size = 18 }: P) => line(
  <><polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><path d="M21 3l-7 7" /><path d="M3 21l7-7" /></>, size)
export const ExitFullscreenIcon = ({ size = 18 }: P) => line(
  <><polyline points="4 14 10 14 10 20" /><polyline points="20 10 14 10 14 4" /><path d="M14 10l6-6" /><path d="M4 20l6-6" /></>, size)
/** 退出登录：门 + 往外的箭头 */
export const LogoutIcon = ({ size = 18 }: P) => line(
  <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><path d="M21 12H9" /></>, size)

// ── 方向 ──
export const ChevronLeft = ({ size = 15 }: P) => line(<path d="m15 18-6-6 6-6" />, size, 2)
export const ChevronRight = ({ size = 15 }: P) => line(<path d="m9 18 6-6-6-6" />, size, 2)
export const ChevronDown = ({ size = 13 }: P) => line(<path d="m6 9 6 6 6-6" />, size, 2.2)
export const ChevronUp = ({ size = 13 }: P) => line(<path d="m6 15 6-6 6 6" />, size, 2.2)
/** 展开箭头：收起时朝右，展开时转 90°——同一枚图标转过去，比 ▸/▾ 两个字符稳定 */
export const Disclosure = ({ open, size = 12 }: P & { open: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden
    style={{ transition: 'transform .12s', transform: open ? 'rotate(90deg)' : 'none' }}><path d="m9 18 6-6-6-6" /></svg>
)
export const ArrowUp = ({ size = 12 }: P) => line(<><path d="M12 19V5" /><path d="m6 11 6-6 6 6" /></>, size, 2.2)
export const ArrowDown = ({ size = 12 }: P) => line(<><path d="M12 5v14" /><path d="m6 13 6 6 6-6" /></>, size, 2.2)
/** 回车键：原来写作 ⏎ */
export const EnterIcon = ({ size = 16 }: P) => line(<><path d="M20 5v6a3 3 0 0 1-3 3H4.5" /><path d="m9 9-5 5 5 5" /></>, size, 2)
export const ArrowToBottom = ({ size = 13 }: P) => line(<><path d="M12 4v10" /><path d="m7 11 5 5 5-5" /><path d="M5 20h14" /></>, size, 2)
// ── 任务行尾的动作（.tt-act 图标钮）──
// 这几枚是给「进入 / 对比 / 派生 / 收尾 / 清理」用的：一行里四五个动作写成汉字太吵，
// 图标要一眼能认出动作本身，所以各画各的寓意，不复用意思相近的旧件。
/** 对比 / diff：两支反向的箭头（git compare），别用 ⇄ 字符 */
export const DiffIcon = ({ size = 13 }: P) => line(
  <><path d="M4 8.5h13" /><path d="m14 5.5 3 3-3 3" /><path d="M20 15.5H7" /><path d="m10 12.5-3 3 3 3" /></>, size)
/** 派生：一条主线往下分出两条（区别于 BranchIcon —— 那个是「分支」这个名词的标识） */
export const ForkIcon = ({ size = 13 }: P) => line(
  <><circle cx="12" cy="4.8" r="2.2" /><circle cx="7" cy="19.2" r="2.2" /><circle cx="17" cy="19.2" r="2.2" />
    <path d="M12 7v2.6" /><path d="M12 9.6a4.4 4.4 0 0 0-5 4.4v3" /><path d="M12 9.6a4.4 4.4 0 0 1 5 4.4v3" /></>, size)
/** 收尾 / 归档：带盖的箱子——收尾可能是合并也可能是丢弃，别用带倾向的合并标 */
export const ArchiveIcon = ({ size = 13 }: P) => line(
  <><rect x="3" y="4" width="18" height="4.6" rx="1.4" /><path d="M5 8.6V19a1.6 1.6 0 0 0 1.6 1.6h10.8A1.6 1.6 0 0 0 19 19V8.6" /><path d="M9.8 12.4h4.4" /></>, size)
/** 清理 / 删除：垃圾桶 */
export const TrashIcon = ({ size = 13 }: P) => line(
  <><path d="M4 6.5h16" /><path d="M9.5 6.5V4.8A1.3 1.3 0 0 1 10.8 3.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
    <path d="M6.5 6.5 7.4 19a1.6 1.6 0 0 0 1.6 1.5h6a1.6 1.6 0 0 0 1.6-1.5l.9-12.5" /></>, size)

/** 外链 / 在别处打开：原来写作 ↗ */
export const OpenInIcon = ({ size = 13 }: P) => line(<><path d="M14 4h6v6" /><path d="M20 4 11 13" /><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></>, size)

// ── 状态 ──
/** 权限/审批模式：一枚盾。对话页「+」菜单里那一项（轮换 Claude/Codex 的权限档） */
export const ShieldIcon = ({ size = 13 }: P) => line(<path d="M12 3.5 19 6v6c0 4-3 7-7 8.5C8 19 5 16 5 12V6Z" />, size)

export const WarnIcon = ({ size = 14 }: P) => line(
  <><path d="M10.3 4.3 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0Z" /><path d="M12 9.5v4" /><path d="M12 17h.01" /></>, size)
export const InfoIcon = ({ size = 14 }: P) => line(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 8h.01" /></>, size)
export const QuestionIcon = ({ size = 14 }: P) => line(
  <><circle cx="12" cy="12" r="9" /><path d="M9.4 9.2A2.7 2.7 0 0 1 14.6 10c0 1.8-2.6 2.3-2.6 4" /><path d="M12 17.5h.01" /></>, size)
export const BlockIcon = ({ size = 14 }: P) => line(<><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5" /><path d="M12 16.5h.01" /></>, size)
export const TargetIcon = ({ size = 14 }: P) => line(<><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3.5" /></>, size)
export const MegaphoneIcon = ({ size = 14 }: P) => line(
  <><path d="M4 10v4a1 1 0 0 0 1 1h3l7 4V5L8 9H5a1 1 0 0 0-1 1Z" /><path d="M18.5 9a4 4 0 0 1 0 6" /></>, size)
export const FlagIcon = ({ size = 13 }: P) => line(<><path d="M5 21V4" /><path d="M5 4.5h11l-2 4 2 4H5" /></>, size)
export const StarIcon = ({ size = 14, filled }: P & { filled?: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor"
    strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="m12 3.6 2.6 5.4 5.9.8-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.8l5.9-.8Z" /></svg>
)
export const CloudIcon = ({ size = 13 }: P) => line(<path d="M6.5 18a4.5 4.5 0 0 1-.4-9 6 6 0 0 1 11.6 1.4A3.8 3.8 0 0 1 17.5 18Z" />, size)
export const LinkIcon = ({ size = 13 }: P) => line(
  <><path d="M10 13a4 4 0 0 0 6 .5l2.5-2.5a4 4 0 0 0-5.7-5.7L11.5 6.7" /><path d="M14 11a4 4 0 0 0-6-.5L5.5 13a4 4 0 0 0 5.7 5.7l1.3-1.3" /></>, size)

/** GitHub 品牌标：官方字形，实心填充——和 AgentLogo 一样属于「品牌标不改画法」的例外 */
export const GithubIcon = ({ size = 18 }: P) => solid(
  <path d="M12 2C6.48 2 2 6.58 2 12.26c0 4.5 2.87 8.32 6.84 9.67.5.1.68-.22.68-.49 0-.24-.01-.87-.01-1.71-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.89 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.36-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.27 2.75 1.05a9.36 9.36 0 0 1 2.5-.34c.85 0 1.71.12 2.5.34 1.91-1.32 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.81-4.57 5.06.36.32.68.94.68 1.9 0 1.37-.01 2.48-.01 2.82 0 .27.18.6.69.49A10.02 10.02 0 0 0 22 12.26C22 6.58 17.52 2 12 2z" />, size)

// ── 领域物件 ──
/** 蜂群：原来写作 ⬡（六边形字符），在多数字体里比正文小半档还带自己的边距 */
/** 外部 / 在别处占着：原来写作 ⧉ */
export const WindowsIcon = ({ size = 12 }: P) => line(<><rect x="3" y="6" width="12" height="12" rx="2" /><path d="M9 6V4.5a1.5 1.5 0 0 1 1.5-1.5H19.5A1.5 1.5 0 0 1 21 4.5V13.5a1.5 1.5 0 0 1-1.5 1.5H18" /></>, size)
/** 回复某条：原来写作 ⤷ */
export const ReplyIcon = ({ size = 12 }: P) => line(<><path d="M7 5v5a3 3 0 0 0 3 3h8" /><path d="m14 9 4 4-4 4" /></>, size)
export const SwarmIcon = ({ size = 13 }: P) => line(<path d="M12 3.2 20 7.6v8.8L12 20.8 4 16.4V7.6Z" />, size)
/** 合入 / 已并到主干：原来写作 ⇥ */
export const MergeIcon = ({ size = 13 }: P) => line(
  <><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="12" r="2.2" /><path d="M6 8.2v7.6" /><path d="M8.2 6h3.3a4 4 0 0 1 4 4v.3" /><path d="M8.2 18h3.3a4 4 0 0 0 4-4v-.3" /></>, size)
/** 已推送到远端：原来写作 ⇡ */
export const PushIcon = ({ size = 13 }: P) => line(<><path d="M12 20V8" /><path d="m7 13 5-5 5 5" /><path d="M6 4h12" /></>, size)
export const BotIcon = ({ size = 14 }: P) => line(
  <><rect x="4" y="8" width="16" height="11" rx="3" /><path d="M12 4.5V8" /><circle cx="12" cy="3.4" r="1.2" /><path d="M9 13h.01" /><path d="M15 13h.01" /></>, size)
export const UserIcon = ({ size = 14 }: P) => line(<><circle cx="12" cy="8" r="3.6" /><path d="M4.5 20a7.5 7.5 0 0 1 15 0" /></>, size)
export const ClockIcon = ({ size = 13 }: P) => line(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5.2l3.2 2" /></>, size)
export const CircleIcon = ({ size = 13 }: P) => line(<circle cx="12" cy="12" r="8" />, size)
export const DotIcon = ({ size = 13 }: P) => solid(<circle cx="12" cy="12" r="4.5" />, size)
/** 指挥/领队：原来写作 ◆ */
export const DiamondIcon = ({ size = 13 }: P) => solid(<path d="m12 3.5 8.5 8.5-8.5 8.5L3.5 12Z" />, size)

// ── Agent 工具调用的类型图标（原来一列 emoji：📖 ✏️ 📓 🔍 🤖 🌐 ❓ ⚙）──
/** 右栏活动条的 Git / Worktree 两格（22 设计 §3.4） */
export const GitIcon = ({ size = 17 }: P) => line(<><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="12" r="2.2" /><path d="M6 8.2v7.6" /><path d="M8.2 6h3.3a4 4 0 0 1 4 4v.3" /><path d="M8.2 18h3.3a4 4 0 0 0 4-4v-.3" /></>, size)
export const WorktreeIcon = ({ size = 17 }: P) => line(<><circle cx="12" cy="4.8" r="2.2" /><circle cx="7" cy="19.2" r="2.2" /><circle cx="17" cy="19.2" r="2.2" /><path d="M12 7v2.6" /><path d="M12 9.6a4.4 4.4 0 0 0-5 4.4v3" /><path d="M12 9.6a4.4 4.4 0 0 1 5 4.4v3" /></>, size)
/** 右栏开关：标签条右端，亮着 = 右栏开着（22 设计 §3.3） */
export const PanelRightIcon = ({ size = 15 }: P) => line(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></>, size, 1.7)
export const TerminalIcon = ({ size = 13 }: P) => line(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3" /><path d="M13 15h4" /></>, size)
export const ReadIcon = ({ size = 13 }: P) => line(
  <><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H5.5A1.5 1.5 0 0 1 4 15.5Z" /><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H14a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h4.5a1.5 1.5 0 0 0 1.5-1.5Z" /></>, size)
export const PencilIcon = ({ size = 13 }: P) => line(<><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7.5 18.5 3 20l1.5-4.5Z" /><path d="m14.5 5.5 3 3" /></>, size)
export const NotebookIcon = ({ size = 13 }: P) => line(<><rect x="5" y="3" width="15" height="18" rx="2" /><path d="M9 3v18" /><path d="M13 8h3" /><path d="M13 12h3" /></>, size)
export const SearchIcon = ({ size = 13 }: P) => line(<><circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" /></>, size)
// 放大 / 缩小：跟 SearchIcon 同一枚镜片，只是镜片里多一横（一竖）——工具条上三枚钮挨着，
// 形状不同源会立刻看出来是拼的。
export const ZoomInIcon = ({ size = 13 }: P) => line(
  <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" /><path d="M11 8.2v5.6" /><path d="M8.2 11h5.6" /></>, size)
export const ZoomOutIcon = ({ size = 13 }: P) => line(
  <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" /><path d="M8.2 11h5.6" /></>, size)
/** 适应窗口：四角向内收 */
export const FitIcon = ({ size = 13 }: P) => line(
  <><path d="M9 4.5H4.5V9" /><path d="M15 4.5h4.5V9" /><path d="M9 19.5H4.5V15" /><path d="M15 19.5h4.5V15" /></>, size)
// 搜索结果里区分「这是个文件夹/项目」还是「这是个文件」。按类型细分的文件图标在
// file-icons.tsx，那是文件列表的活；这里只要一个中性的通用件。
export const PlugIcon = ({ size = 13 }: P) => line(
  <><path d="M9 3v5" /><path d="M15 3v5" /><path d="M6.5 8h11v3.5a5.5 5.5 0 0 1-11 0Z" /><path d="M12 17v4" /></>, size)
export const FolderIcon = ({ size = 13 }: P) => line(
  <path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h3.6l1.8 2.2H19a1.5 1.5 0 0 1 1.5 1.5v8.8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5Z" />, size)
export const FileTextIcon = ({ size = 13 }: P) => line(
  <><path d="M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5Z" /><path d="M13.5 3.5v5h5" /><path d="M9 13h6" /><path d="M9 16.5h4" /></>, size)
export const ImageIcon = ({ size = 13 }: P) => line(<><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="8.5" cy="10" r="1.5" /><path d="m4 17 5-5 4 4 3-2.5 4 3.5" /></>, size)
export const GlobeIcon = ({ size = 13 }: P) => line(<><circle cx="12" cy="12" r="9" /><path d="M3.3 9h17.4" /><path d="M3.3 15h17.4" /><path d="M12 3a15 15 0 0 1 0 18" /><path d="M12 3a15 15 0 0 0 0 18" /></>, size)
export const GearIcon = ({ size = 13 }: P) => line(
  <><circle cx="12" cy="12" r="3" /><path d="M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1v.3a2 2 0 1 1-4 0v-.2a1.6 1.6 0 0 0-2.8-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7h-.3a2 2 0 1 1 0-4h.2a1.6 1.6 0 0 0 1.1-2.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 2.7-1.1v-.3a2 2 0 1 1 4 0v.2a1.6 1.6 0 0 0 2.8 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7h.3a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.4 1Z" /></>, size)
export const ChecklistIcon = ({ size = 13 }: P) => line(<><path d="m3 6 2 2 3-3" /><path d="m3 14 2 2 3-3" /><path d="M12 7h9" /><path d="M12 15h9" /></>, size)
export const KeyboardIcon = ({ size = 13 }: P) => line(
  <><rect x="2.5" y="6" width="19" height="12" rx="2" /><path d="M7 10h.01" /><path d="M11 10h.01" /><path d="M15 10h.01" /><path d="M8 14h8" /></>, size)
export const HomeIcon = ({ size = 13 }: P) => line(<><path d="M3.5 11.5 12 4.5l8.5 7" /><path d="M6 10v9.5h12V10" /></>, size)
export const MoonIcon = ({ size = 13 }: P) => line(<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />, size)
export const SunIcon = ({ size = 13 }: P) => line(
  <><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2" /><path d="M12 19.5v2" /><path d="M2.5 12h2" /><path d="M19.5 12h2" /><path d="m5.3 5.3 1.4 1.4" /><path d="m17.3 17.3 1.4 1.4" /><path d="m18.7 5.3-1.4 1.4" /><path d="m6.7 17.3-1.4 1.4" /></>, size)

// ── 手机遥控（PhoneView）：安卓/iOS 的系统键，原来用 ○ ◉ ◁ ▭ 四个字符凑 ──
// 镜像两页页头用（设计 17）：标签数字钮的方框、设备芯片的机身、应用启动器的九宫格
export const TabsIcon = ({ size = 18 }: P) => line(<rect x="3" y="3" width="18" height="18" rx="3" />, size, 1.7)
export const DeviceIcon = ({ size = 13 }: P) => line(
  <><rect x="7" y="3" width="10" height="18" rx="2" /><path d="M11 18.5h2" /></>, size)
export const AppsIcon = ({ size = 16 }: P) => line(
  <><rect x="3.5" y="3.5" width="7" height="7" rx="1.6" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.6" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.6" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.6" /></>, size, 1.7)

export const PhoneHomeIcon = ({ size = 16 }: P) => line(<circle cx="12" cy="12" r="8" />, size, 2)
export const PhoneBackIcon = ({ size = 16 }: P) => line(<path d="M15 5 7 12l8 7Z" />, size, 2)
export const PhoneRecentsIcon = ({ size = 16 }: P) => line(<rect x="5" y="6" width="14" height="12" rx="2" />, size, 2)
export const PhoneAssistIcon = ({ size = 16 }: P) => line(
  <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none" /></>, size, 2)
export const PowerIcon = ({ size = 16 }: P) => line(<><path d="M12 3.5v8" /><path d="M17.7 6.8a8 8 0 1 1-11.4 0" /></>, size, 2)

// ── 镜像页（BrowserView / PhoneView）的工具条 ──
// 这三枚原来是就地画在组件里的一次性 SVG（旋转那枚还是 Material 的实心件，
// 线宽/填充都跟旁边的线性图标对不上），按「新图标默认加在 icons.tsx」收进来。
/** 旋转画面 90°：设备框 + 绕角的回转箭头，明显区别于刷新的整环箭头 */
export const RotateScreenIcon = ({ size = 15 }: P) => line(
  <><rect x="3" y="7.5" width="11" height="13.5" rx="1.8" /><path d="M9.5 3.5h6.5A4.5 4.5 0 0 1 20.5 8v4" /><path d="m12 6 2.6-2.5L12 1" /></>, size)
/** 开发者工具：尖括号，取代文字按钮「调试」 */
export const CodeIcon = ({ size = 15 }: P) => line(<><path d="m8 8-4.5 4L8 16" /><path d="m16 8 4.5 4L16 16" /><path d="m13.5 5-3 14" /></>, size)
/** 启动应用：方框里一个向右的箭头 */
export const AppLaunchIcon = ({ size = 13 }: P) => line(
  <><rect x="3.5" y="3.5" width="17" height="17" rx="3" /><path d="M9 12h6" /><path d="m12.5 9 3 3-3 3" /></>, size)

// ── Agent 品牌标 ──
// Claude / Codex 的会话标记原来是手画的两枚几何件（三线星 + 同心圆），既不是品牌标
// 也认不出来；这里换成官方 mark 的官方路径（取自 simple-icons 的 claude / openai，
// 24×24 viewBox、实心）。品牌标是全站唯一不继承父级颜色的图标：画法和颜色都按人家的来，
// Claude 陶土橙、OpenAI 单色标随前景（--brand-claude / --brand-codex，见 index.css）。
const CLAUDE_MARK = 'm4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z'
const CODEX_MARK = 'M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z'
/** 会话跑的是哪个 agent：Claude Code / Codex 的官方 mark，官方色 */
export const AgentLogo = ({ kind, size = 13 }: { kind: 'claude' | 'codex'; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden focusable="false"
    fill={kind === 'claude' ? 'var(--brand-claude)' : 'var(--brand-codex)'}>
    <path d={kind === 'claude' ? CLAUDE_MARK : CODEX_MARK} />
  </svg>
)

/** 图例色块：原来写作 ■（实心方块字符），高度和基线跟着字体走 */
export const Swatch = ({ color, size = 9 }: { color: string; size?: number }) => (
  <span aria-hidden style={{
    display: 'inline-block', width: size, height: size, borderRadius: 2,
    background: color, flex: '0 0 auto',
  }} />
)
