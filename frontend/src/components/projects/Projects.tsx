import { agentName, useAgentKinds, type AgentKind } from '../../agent-kind'
import { agentCommand } from '../../agent-command'
// 项目页（08 设计）——「项目 = 目录（git 可选），任务驱动」：
//   #/projects        P1 工作台：问候+行动队列（原概览页，18 设计）+ 项目卡栅格 + 散会话 + 活动轨
//   #/projects/<key>  P2 主页：composer（描述任务 ⏎ 开干）+ 任务流（会话 ∪ 孤儿 worktree）
//                     + Worktree / 编队 / 活动 tab（仅 git 项目开启）
// 项目是后台存储对象（POST/DELETE /projects）；开 session、建 feature 是项目内的动作。
//
// 视觉基调：终端工业风的克制精修——居中 880px 阅读列、composer 是全页唯一 hero
// （渐变卡面 + focus 辉光环）、git 数据一律等宽字、行 hover 左导轨渐显、
// 分区头沿用设计图纸体例、入场一次性 stagger。全部颜色走 index.css token。
import {Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { MemBar } from '../sessions/session-memory'
import type { ReactNode } from 'react'
import { App as AntApp, AutoComplete, Button, Dropdown, Input, Modal, Popconfirm, Segmented, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import type { InputRef, MenuProps } from 'antd'
import { sessionLabel, sessionDisplay } from '../sessions/session-label'
import { SESSION_MIME, buildIntro, canDrop } from '../shell/session-drop'
import { currentNodeId } from '../cluster/node-url'
import { dirTailName } from '../files/dir-name'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { usePreferences } from '../../preferences'
import { MobileSheet, SheetRow } from '../shell/MobileSheet'
import AdaptivePanel from '../shell/AdaptivePanel'
import { useLayout } from '../../layout'
import { detectPrompt } from '../prompt'
import { relTime } from '../../time-format'
import { NewSessionModal } from '../sessions/NewSessionModal'
import { TaskComposer, type TaskComposerHandle } from '../sessions/TaskComposer'
import { CloseWorktreeModal } from '../sessions/CloseWorktreeModal'
import { DirPicker, recentDirs, pushRecentDir } from '../sessions/DirPicker'
import { projNeeds, runningCount, waitingCount } from './project-list/project-model'
import type { Proj, ProjSession } from './project-list/project-model'
import { NeedsQueue, WorkbenchHead, buildNeedCards, NEEDS_CSS } from './project-list/needs-queue'
import { ActivityRail, useRecentActivity, RAIL_CSS } from './project-list/activity-rail'
import { ProjectCard, CARD_CSS } from './project-list/project-card'
import { useSwarmProjection, normDir } from './project-list/swarm-projection'
import FileBrowser from '../files/FileBrowser'
import { AgentLogo, ArchiveIcon, ArrowDown, ArrowUp, CheckIcon, ChevronDown, CloseIcon, DiffIcon, ForkIcon, MergeIcon, PlayIcon, PlusIcon, PushIcon, SwarmIcon, TerminalIcon, TrashIcon, WarnIcon, WindowsIcon } from '../../icons'
import { BranchIcon } from '../git/parts'
import { lazyRetry } from '../lazy-retry'

const WorktreePanel = lazyRetry(() => import('../git/WorktreePanel'))
const GitPanel = lazyRetry(() => import('../git/GitPanel'))
const RaceCreateModal = lazyRetry(() => import('../swarm/Race').then((m) => ({ default: m.RaceCreateModal })))
const RaceComparePanel = lazyRetry(() => import('../swarm/Race').then((m) => ({ default: m.RaceComparePanel })))
const NewSwarmModal = lazyRetry(() => import('../swarm/Swarm').then((m) => ({ default: m.NewSwarmModal })))

// 项目列表排序模式（置顶恒在最前；选择持久化）。
// 「需要你」是默认档——概览并进来之后，首屏第一问是「该做什么」，不是「按名字排一排」。
type ProjSort = 'needs' | 'name' | 'created' | 'active'
type ProjFilter = 'needs' | 'active' | 'unfinished' | 'all'
const SORT_KEY = 'roam.projects.sort'
const SORTS = ['needs', 'name', 'created', 'active'] as const
// 设计系统 §2：箭头/符号一律 SVG。⌕ ⇅ ✓ 这类文字符号在手机字体上画得又细又歪
const ico = (d: React.ReactNode) => (
  <svg viewBox="0 0 24 24" width={17} height={17} fill="none" stroke="currentColor"
    strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">{d}</svg>
)
const ICON_SEARCH = ico(<><circle cx="11" cy="11" r="7" /><line x1="16.5" y1="16.5" x2="21" y2="21" /></>)
const ICON_SORT = ico(<><path d="M7 4v16" /><path d="M4 8l3-4 3 4" /><path d="M17 20V4" /><path d="M14 16l3 4 3-4" /></>)
const ICON_CHECK = ico(<polyline points="4 12 9 17 20 6" />)
const ICON_CHEVRON = (
  <svg viewBox="0 0 24 24" width={12} height={12} fill="none" stroke="currentColor" aria-hidden="true"
    strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><polyline points="5 9 12 16 19 9" /></svg>
)

// ── 页面级样式（一次注入；产品 token 之上只做布局/微交互）──
const PRJ_CSS = `
/* 左对齐不居中：全站页面统一从 tt-page 的 (16,16) 起笔，限宽只管可读性 */
.prj-wrap{max-width:880px;margin:0;padding:0 0 32px}
/* 概览并进来之后这一页带右轨：1180 是没有右轨时定的，减掉 320 只剩一列半 */
.prj-wrap-wide{max-width:var(--content-overview);margin:0;padding:0 0 32px;
  display:flex;flex-direction:column;gap:var(--sp-3)}
/* 栅格与右轨。阈值一律看 Canvas 容器，不看 viewport——终端坞开合只改 Canvas 宽度 */
.prj-layout{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--sp-4);align-items:start;
  padding-inline:var(--pad-page)}
.prj-feed{min-width:0;display:flex;flex-direction:column}
@container canvas (min-width: 1180px){
  .prj-layout{grid-template-columns:minmax(0,1fr) var(--activity-rail)}
  .prj-rail{position:sticky;top:0;align-self:start}
  /* 右轨吃掉 320，剩下的宽度按 .prj-grid 的 auto-fill(320) 自然落成 2 列；
     ≥1560 才够 3 列——1320 减去右轨只剩 980，三列会挤破 320 的下限 */
}
.prj-mono{font-family:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace}
.prj-in{animation:prjIn .38s cubic-bezier(.2,.85,.3,1) backwards}
@keyframes prjIn{from{opacity:0;transform:translateY(6px)}}
@keyframes projLifecPulse{0%,100%{opacity:1}50%{opacity:.35}}

/* 「开干」是这张卡的主动作，但它得带着字——「发送一句话」看箭头就懂，
   「按这些选项建一个会话」不写字没人知道按下去会发生什么。 */
.prj-go{height:26px !important;border-radius:var(--r-pill) !important;padding:0 16px !important;font-weight:600}
@media (pointer:coarse){ .prj-go{height:36px !important;padding:0 20px !important} }

/* 项目头 64 / Tabs 40，两者 sticky（14 §6.2）：往下翻任务流时「我在哪个项目、
   要新建什么、在看哪个 tab」始终在手边 */
/* 页面容器不再给 16px 外框（见 index.css .tt-page-projects），留白改由这几段自己带：
   sticky 头和它那条分割线因此能一路铺到边，跟文件/插件页的竖线是同一种做法。 */
.prj-head{position:sticky;top:0;z-index:calc(var(--z-sticky) + 1);min-height:64px;
  padding:var(--sp-3) var(--pad-page) 0;
  background:var(--bg-base);border-bottom:1px solid var(--border-subtle);margin-bottom:12px}
.prj-tabs{position:sticky;top:64px;z-index:var(--z-sticky);
  display:flex;gap:2px;margin:20px 0 2px;min-height:40px;padding-inline:var(--pad-page);
  background:var(--bg-base);border-bottom:1px solid var(--border-subtle)}
.prj-tab{padding:8px 13px 9px;font-size:13px;color:var(--text-dim);cursor:pointer;user-select:none;
  display:inline-flex;align-items:center;gap:6px;border-bottom:2px solid transparent;margin-bottom:-1px;
  transition:color .15s}
:where(html[data-pointer="fine"]) .prj-tab:hover{color:var(--text-bright)}
.prj-tab.on{color:var(--text-bright);border-bottom-color:var(--accent);font-weight:600}
.prj-tab .n{font-size:10.5px;font-family:ui-monospace,monospace;color:var(--text-dimmer);
  background:rgba(177,186,196,.08);border-radius:999px;padding:1px 6px}

.prj-sect{display:flex;align-items:center;gap:var(--sp-2);margin:var(--sp-4) 0 var(--sp-2);
  font-size:var(--fs-sm);color:var(--text-bright);font-weight:600}
.prj-sect .n{font-family:ui-monospace,monospace;font-size:var(--fs-micro);color:var(--text-dim);font-weight:400}
.prj-sect .ln{flex:1}
.prj-sect .hint{color:var(--text-dimmer);font-weight:400;font-size:var(--fs-meta)}
.prj-sect.warn{color:var(--warn)}
.prj-sect.ok{color:var(--ok)}

.prj-row{position:relative;display:flex;align-items:flex-start;gap:9px;padding:10px 12px;
  border-radius:10px;cursor:pointer;transition:background .15s}
.prj-row::before{content:'';position:absolute;left:0;top:9px;bottom:9px;width:2px;border-radius:2px;
  background:transparent;transition:background .15s}
:where(html[data-pointer="fine"]) .prj-row:hover{background:var(--list-hover)}
:where(html[data-pointer="fine"]) .prj-row:hover::before{background:rgba(88,166,255,.5)}
/* 选中行：细蓝边 + 淡底，和 hover 区分得开（14 §6.3.1） */
.prj-row.on{background:var(--accent-soft);box-shadow:inset 0 0 0 1px var(--accent-border)}
.prj-row.on::before{background:var(--accent)}
/* 动作区（.tt-act 幽灵按钮见 index.css）：按钮自带边框和命中区，不再靠
   「平时半透明、hover 才显形」——那对手指档等于不存在，键盘用户也摸不着。 */
.prj-row .acts{display:flex;gap:6px;flex:0 0 auto;margin-top:2px;flex-wrap:wrap;justify-content:flex-end}
/* 换行时行距给到 10：按钮视觉 36、命中区 44，行距不到 8 两行的命中区就会叠在一起 */
html[data-pointer="coarse"] .prj-row .acts{row-gap:10px}
.prj-row.warn{background:rgba(210,153,34,.05);border:1px solid rgba(210,153,34,.18);margin-bottom:4px}
:where(html[data-pointer="fine"]) .prj-row.warn:hover{background:rgba(210,153,34,.09)}
.prj-row.warn::before{display:none}

/* sticky subheader（14 §6.1）：筛选与排序不该跟着列表滚走 */
.prj-subbar{position:sticky;top:0;z-index:var(--z-sticky);display:flex;align-items:center;gap:var(--sp-3);
  flex-wrap:wrap;margin-bottom:12px;padding:8px 0;background:var(--bg-base)}
.prj-filters{display:flex;align-items:center;gap:var(--sp-2);min-width:0;flex:1 1 auto}
.prj-filters .sp{flex:1 1 auto}
/* 手机：整条 chrome 压成一行 44 —— 筛选带自己就说明了「项目列表、共 12 个」，
   页名不必再写一遍（底栏已经高亮着「项目」）。搜索与排序收成右侧两枚图标，
   钉住不随横滑跑掉；筛选带右缘渐隐，否则 chip 会从图标底下钻出来。 */
html[data-size="compact"] .prj-subbar{flex-wrap:nowrap;gap:var(--sp-2);min-height:44px;padding:0;margin-bottom:var(--sp-2)}
html[data-size="compact"] .prj-filters{overflow-x:auto;scrollbar-width:none;flex:1 1 auto;
  mask-image:linear-gradient(90deg,#000 calc(100% - 18px),transparent 100%)}
html[data-size="compact"] .prj-filters::-webkit-scrollbar{height:0}
html[data-size="compact"] .prj-filters>*{flex:0 0 auto}
html[data-size="compact"] .prj-filters .prj-chip{position:relative;height:calc(var(--tap) - var(--sp-2))}
html[data-size="compact"] .prj-filters .prj-chip::after{content:"";position:absolute;left:calc(-1 * var(--sp-1));right:calc(-1 * var(--sp-1));
  top:50%;height:var(--tap);transform:translateY(-50%)}
html[data-size="compact"] .prj-filters .sp,
/* 手机：排序走右侧钉住的 ⇅ 图标 + 底部 sheet，筛选带里那枚排序控件是重复的 */
html[data-size="compact"] .prj-filters .ant-segmented,
html[data-size="compact"] .prj-subbar .prj-sortpill{display:none}
/* 图标按钮：不描边——右边两个方框和左边的圆角 chip 不是一套语言。命中区靠伪元素撑到 44 */
.prj-iconbtn{position:relative;flex:0 0 auto;width:32px;height:32px;display:none;place-items:center;
  border:0;border-radius:var(--r-sm);background:transparent;color:var(--text-dim);cursor:pointer}
.prj-iconbtn::after{content:"";position:absolute;left:50%;top:50%;width:44px;height:44px;transform:translate(-50%,-50%)}
.prj-iconbtn:active{background:var(--list-hover)}
html[data-size="compact"] .prj-iconbtn{display:grid}
/* 搜索：桌面常驻，手机点图标后原地展开（不新增一行） */
html[data-size="compact"] .prj-subbar .prj-search{display:none}
html[data-size="compact"] .prj-subbar.searching .prj-search{display:block;flex:1 1 auto}
html[data-size="compact"] .prj-subbar.searching .prj-filters,
html[data-size="compact"] .prj-subbar.searching .prj-iconbtn.find{display:none}
.prj-chip{display:inline-flex;align-items:center;gap:var(--sp-2);height:28px;padding:0 var(--sp-3);border-radius:var(--r-pill);
  border:1px solid var(--border);background:transparent;color:var(--text-dim);font-size:12px;
  cursor:pointer;white-space:nowrap;transition:color .15s,border-color .15s,background .15s}
:where(html[data-pointer="fine"]) .prj-chip:hover{color:var(--text-bright);border-color:#8b949e}
.prj-chip.on{color:var(--accent);border-color:var(--accent-border);background:var(--accent-soft)}
.prj-chip .n{font-family:ui-monospace,monospace;font-size:var(--fs-micro);color:var(--text-dimmer)}
.prj-chip.on .n{color:var(--accent)}

/* 「其他项目」：没有会话在跑的项目不值一张卡（图纸 14-desktop-workspace/desktop-ia.html §二）——
   实测 4 个空项目占掉 467px 的栅格。折成一行一个：名字 + 路径 + 可清理标。 */
.prj-quiet{display:grid;grid-template-columns:minmax(96px,150px) minmax(0,1fr) auto;align-items:center;
  gap:var(--sp-3);min-height:36px;padding:var(--sp-1) var(--sp-2);border-radius:var(--r-sm);
  cursor:pointer;transition:background .14s}
.prj-quiet+.prj-quiet{border-top:1px solid var(--border-subtle)}
:where(html[data-pointer="fine"]) .prj-quiet:hover{background:var(--list-hover)}
.prj-quiet .nm{font-size:var(--fs-sm);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prj-quiet .p{font-family:ui-monospace,monospace;font-size:var(--fs-meta);color:var(--text-dimmer);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
html[data-size="compact"] .prj-quiet{grid-template-columns:minmax(0,1fr) auto;min-height:44px}
html[data-size="compact"] .prj-quiet .p{display:none}
/* 右列：可清理标签或「空闲多久」。两者互斥——有活要干时不必再说它闲着。 */
.prj-quiet .qt{font-size:var(--fs-micro);color:var(--text-dimmer);white-space:nowrap}

.prj-panel{background:var(--bg-container);border:1px solid var(--border-subtle);border-radius:12px;margin-top:8px}
.prj-wtrow{padding:13px 16px}
.prj-wtrow+.prj-wtrow{border-top:1px solid var(--border-subtle)}
.prj-subrow{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:8px;cursor:pointer;transition:background .14s}
:where(html[data-pointer="fine"]) .prj-subrow:hover{background:var(--list-hover)}
.prj-peek{flex:1;min-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-family:ui-monospace,monospace;font-size:11px;color:var(--text-dimmer);
  background:var(--bg-term);border:1px solid var(--border-subtle);border-radius:6px;padding:3px 8px}
.prj-addline{display:flex;align-items:center;flex-wrap:wrap;gap:var(--sp-2);padding:var(--sp-2) var(--sp-3);margin-top:var(--sp-1);
  border:1px dashed var(--border);border-radius:var(--r-sm);color:var(--text-dim);font-size:var(--fs-meta);
  transition:border-color .15s,color .15s}
:where(html[data-pointer="fine"]) .prj-addline:hover{border-color:#8b949e;color:var(--text-bright)}

.prj-empty{color:var(--text-dimmer);font-size:12.5px;padding:14px 12px}

/* 分叉图：主干是整行高的绝对定位线（行高随内容变，画进 svg 必断），
   svg 只画「从主干拐出来的一小段 + 节点」，钉在行顶 22px 处。 */
.prj-fork{position:relative;display:flex;padding:0 14px 0 40px}
.prj-fork::before{content:'';position:absolute;left:15px;top:0;bottom:0;width:1.6px;background:hsl(212,78%,58%)}
.prj-fork.head::before{top:22px}
.prj-fork:last-child::before{bottom:auto;height:24px}
.prj-fork+.prj-fork .col{border-top:1px solid var(--border-subtle)}
.prj-fork .fk{position:absolute;left:0;top:4px;overflow:visible}
.prj-fork .col{flex:1;min-width:0;padding:11px 0 12px;display:flex;gap:12px;align-items:flex-start}
.prj-fork .info{flex:1;min-width:0;display:flex;flex-direction:column;gap:5px}
.prj-fork .n1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.prj-fork .n2{font-size:12px;color:var(--text-dimmer)}
.prj-fork .wt-br{font-family:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace;
  font-size:var(--fs-sm);font-weight:600;color:var(--text-bright)}
.prj-fork .wt-br{display:inline-flex;align-items:center;gap:4px}
.prj-fork .wt-ab{font-family:ui-monospace,monospace;font-size:12px;display:inline-flex;align-items:center;gap:1px}
.prj-fork .wt-ab.up{color:var(--ok)} .prj-fork .wt-ab.dn{color:#d29922}
.prj-fork .wt-acts{flex:0 0 auto;display:flex;gap:6px;align-items:center;opacity:.55;transition:opacity .15s}
:where(html[data-pointer="fine"]) .prj-fork:hover .wt-acts,.prj-fork .wt-acts:focus-within{opacity:1}
html[data-pointer="coarse"] .prj-fork .wt-acts{opacity:1}
.prj-fork.merged .col,.prj-fork.ext .col{opacity:.75}
`

// 分叉图（11 §8.2）：主干蓝取提交树 lane 0 同色，支线按状态着色——
// 绿=有会话在跑 / 琥珀=孤儿待收尾 / 灰虚线=已合入待清理 / 灰菱形=外部。
const FORK_TRUNK = 'hsl(212, 78%, 58%)'
const FORK_COLOR: Record<string, string> = {
  live: 'var(--ok)', orphan: '#d29922', merged: 'rgba(139,148,158,.55)', ext: 'rgba(139,148,158,.7)',
}
const CLI_KINDS = ['shell', 'claude', 'codex', 'pi', 'opencode'] as const

// 行尾动作钮：一行四五个动作写成汉字太吵，收成图标方钮。
// 图标不写进文案（图标硬规则）：label 只给字，Tooltip 和 aria-label 都用它，图标在调用处传。
//
// 粗指针下**不挂 Tooltip**：触屏点一下就把浮层弹出来，之后没有 mouseleave 让它收，
// 它就一直悬在按钮上方那一条；而 antd 的 .ant-tooltip 是 pointer-events: auto，
// 于是它盖住的那块区域后续的点全被吞掉——表现就是「点了没有该有的动作」。
// 手指档靠 aria-label + 原生 title 说明动作，不弹浮层。
export const ActBtn = ({ icon, label, tone, onClick }: {
  icon: ReactNode; label: string; tone?: 'danger' | 'ok'; onClick?: () => void
}) => {
  const { coarse } = useLayout()
  const btn = (
    <button type="button" className={`tt-act ico${tone ? ' ' + tone : ''}`} aria-label={label}
      title={coarse ? label : undefined} onClick={onClick}>{icon}</button>
  )
  return coarse ? btn : <Tooltip title={label}>{btn}</Tooltip>
}

// hollow：休眠会话（台账里还认得它，点开即恢复）。空心而不是灰色实心——
// 灰色实心已经是「活着但空闲」，而这两者的区别是能不能直接用。
export const dot = (on: boolean, color?: string, hollow?: boolean) => (
  <span style={{
    width: 8, height: 8, borderRadius: '50%', flex: '0 0 8px', display: 'inline-block',
    background: hollow ? 'transparent' : color || (on ? 'var(--ok)' : 'var(--text-dimmer)'),
    boxShadow: hollow
      ? 'inset 0 0 0 1.5px var(--text-dimmer)'
      : color || on ? `0 0 0 3px ${color ? 'rgba(210,153,34,.12)' : 'rgba(63,185,80,.12)'}` : undefined,
  }} />
)

// ── 生命周期导轨（P2 图纸）：建→干→审→并，当前段呼吸 ──────
// 四段原来一段一个颜色（青/绿/黄/紫）。同一行里已经有分支片、状态标、agent 品牌标在说话，
// 再摆一道四色阶梯就成了彩虹，而且颜色本身并不表达「进行到第几步」——长度才表达。
// 改成单色进度条：走过/当前的段是强调色，没到的留灰，阶段名就在旁边写着。
export function Lifec({ done, cur }: { done: number; cur?: number }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
      {[1, 2, 3, 4].map((i) => (
        <i key={i} style={{
          width: 11, height: 4, borderRadius: 2,
          background: i <= done || i === cur ? 'var(--accent)' : 'rgba(139,148,158,.25)',
          animation: i === cur ? 'projLifecPulse 1.6s ease-in-out infinite' : undefined,
        }} />
      ))}
    </span>
  )
}

export default function Projects({ openTerm, closeTerm, initialKey, activeTerm }: { openTerm: (n: string) => void; closeTerm: (n: string) => void; initialKey?: string; activeTerm?: string | null }) {
  const [data, setData] = useState<{ projects: Proj[]; loose: ProjSession[] }>({ projects: [], loose: [] })
  const [loaded, setLoaded] = useState(false)
  const load = () => api('GET', '/projects').then((r) => {
    setData({ projects: r?.data?.projects || [], loose: r?.data?.loose || [] })
    setLoaded(true)
  }).catch(() => {})
  useEffect(() => { load(); const i = setInterval(load, 5000); return () => clearInterval(i) }, [])

  return (
    <>
      <style>{PRJ_CSS + NEEDS_CSS + CARD_CSS + RAIL_CSS}</style>
      {initialKey
        ? <ProjectHome proj={data.projects.find((x) => x.key === initialKey)} allProjects={data.projects} loaded={loaded} openTerm={openTerm} closeTerm={closeTerm} refresh={load} activeTerm={activeTerm} />
        : <ProjectList data={data} loaded={loaded} openTerm={openTerm} refresh={load} />}
    </>
  )
}

// ── 新项目弹窗：创建的是「项目」这个存储对象（POST /projects），不建任何会话。
// 项目 = 任意目录（git 可选）；开 session / 建 feature 是进项目之后 composer 的事。
export function NewProjectModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: () => void }) {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [dir, setDir] = useState('')
  const [pick, setPick] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  // 三种来源。后端其实一直支持「目录不存在就新建」，但界面从没说过，
  // 于是用户只敢填已经存在的路径——这里把它摆到明面上。
  const [source, setSource] = useState<'existing' | 'clone'>('existing')
  const [cloneUrl, setCloneUrl] = useState('')
  // 名字是不是用户自己写过：写过就不再被目录覆盖，否则改一次目录就把他写的名字冲掉
  const [nameTouched, setNameTouched] = useState(false)
  useEffect(() => { if (open) { setDir(''); setName(''); setNameTouched(false); setSource('existing'); setCloneUrl('') } }, [open])

  /** 从 git URL 猜仓库名：git@host:org/repo.git 或 https://host/org/repo(.git) → repo */
  const repoNameFromUrl = (u: string): string => {
    const cleaned = u.trim().replace(/\.git$/, '').replace(/\/+$/, '')
    const seg = cleaned.split(/[/:]/).filter(Boolean).pop() || ''
    return /^[\w.-]+$/.test(seg) ? seg : ''
  }

  /** 目录定下来就把名字填成路径最后一段（/home/ai/codes/ttmux → ttmux）。
   *  只在「选完」时填——选目录、选历史项、离开输入框，不跟着每次按键跳。 */
  const fillNameFromDir = (p: string) => {
    if (nameTouched) return
    const seg = dirTailName(p)
    if (seg) setName(seg)
  }
  const ok = async () => {
    if (!dir.trim()) { message.error(t('session.dirPlaceholder')); return }
    if (source === 'clone' && !cloneUrl.trim()) { message.error(t('project.cloneUrlRequired')); return }
    try {
      setCreating(true)
      // 克隆可能要几分钟（大仓库），loading 里说清楚在干嘛，别让人以为卡死了
      if (source === 'clone') message.loading({ content: t('project.cloning'), key: 'newproj', duration: 0 })
      const res = await api('POST', '/projects', {
        dir: dir.trim(), displayName: name.trim(),
        ...(source === 'clone' ? { cloneUrl: cloneUrl.trim() } : {}),
      })
      message.destroy('newproj')
      pushRecentDir(dir.trim())
      // 目录是某个已在册仓库的 worktree：没有新项目，归到那个项目下，名字也没动
      if (res.data.created === false) message.info(res.data.worktree ? t('project.existsAsWorktree', { name: res.data.name }) : t('project.existsAlready', { name: res.data.name }), 6)
      else message.success(t('project.createdProject'))
      onClose(); onCreated?.()
      location.hash = '#/projects/' + encodeURIComponent(res.data.key)
    } catch (e: any) { message.destroy('newproj'); message.error(e.message) }
    finally { setCreating(false) }
  }
  return (
    <>
      <Modal open={open} onCancel={onClose} onOk={ok} title={t('project.newModalTitle')}
        okText={t('file.create')} destroyOnClose confirmLoading={creating}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Segmented block value={source} onChange={(v) => setSource(v as 'existing' | 'clone')}
            options={[
              { value: 'existing', label: t('project.sourceLocal') },
              { value: 'clone', label: t('project.sourceClone') },
            ]} />
          {source === 'clone' && (
            <Input value={cloneUrl} autoFocus
              onChange={(e) => {
                setCloneUrl(e.target.value)
                // 顺手把目录和名字填好：绝大多数情况就是「克隆到 ~/codes/<仓库名>」。
                const repo = repoNameFromUrl(e.target.value)
                if (repo && !nameTouched) setName(repo)
                if (repo && (!dir || /(^|\/)[\w.-]*$/.test(dir))) {
                  const base = dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : '~/codes'
                  setDir(base + '/' + repo)
                }
              }}
              placeholder={t('project.cloneUrlPlaceholder')} />
          )}
          <Space.Compact style={{ width: '100%' }}>
            <AutoComplete style={{ flex: 1, minWidth: 0 }} value={dir} onChange={setDir} autoFocus={source === 'existing'}
              onSelect={(v) => fillNameFromDir(String(v))}
              onBlur={() => fillNameFromDir(dir)}
              options={recentDirs().map((d) => ({ value: d }))}
              filterOption={(input, opt) => String(opt?.value).toLowerCase().includes(input.toLowerCase())}
              placeholder={t('session.dirPlaceholder')} />
            <Button onClick={() => setPick(true)}>{t('common.browse')}</Button>
          </Space.Compact>
          <Input placeholder={t('project.displayName')} value={name}
            onChange={(e) => { setName(e.target.value); setNameTouched(true) }} />
          <div style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)', lineHeight: 1.7 }}>
            {source === 'clone' ? t('project.cloneHint') : t('project.newHint')}
          </div>
        </Space>
      </Modal>
      <DirPicker open={pick} start={dir}
        onPick={(p) => { setDir(p); fillNameFromDir(p); setPick(false) }} onClose={() => setPick(false)} />
    </>
  )
}

// ── P1 工作台（18 设计）：概览并进来之后，这一页同时回答「该做什么」和「有哪些项目」──
// ①问候+状态条 ②「需要你」行动条 ③工具条(sticky) ④项目卡栅格 ⑤安静/散会话 ⑥最近活动轨
// 数据只有一条 GET /projects（+ /swarms 投影、/activity 右轨）——绿点/黄点/agent 品牌标
// 后端一趟进程树扫描就算好了，前端不再逐会话探测（18 §9）。
function ProjectList({ data, loaded, openTerm, refresh }: {
  data: { projects: Proj[]; loose: ProjSession[] }; loaded: boolean
  openTerm: (n: string) => void; refresh: () => void
}) {
  const { t } = useI18n()
  const [newOpen, setNewOpen] = useState(false)
  const [sortBy, setSortBy] = useState<ProjSort>(() => {
    try {
      const v = localStorage.getItem(SORT_KEY) as ProjSort
      return SORTS.includes(v) ? v : 'needs'
    } catch { return 'needs' }
  })
  const changeSort = (v: ProjSort) => { setSortBy(v); try { localStorage.setItem(SORT_KEY, v) } catch {} }

  const swarms = useSwarmProjection(data.projects)
  const acts = useRecentActivity(data.projects)

  // 搜索 + 筛选（14 §6.1）：项目一多，「哪些还欠着事」比「一共有几个」有用得多
  const { phone: isPhone } = useLayout()
  const [q, setQ] = useState('')
  const [searching, setSearching] = useState(false)
  const [sortSheet, setSortSheet] = useState(false)
  const searchRef = useRef<InputRef>(null)
  const [filter, setFilter] = useState<ProjFilter>('needs')

  const needsOf = (p: Proj) => projNeeds(p, swarms)
  // 排序：置顶恒在最前；需要你(默认) / 名称(稳定) / 创建时间 / 最近活跃
  const sorted = useMemo(() => [...data.projects].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    if (sortBy === 'created') return (b.firstSeen || 0) - (a.firstSeen || 0)
    if (sortBy === 'active') return (b.lastActivity || 0) - (a.lastActivity || 0)
    if (sortBy === 'needs') return (needsOf(b) - needsOf(a)) || ((b.lastActivity || 0) - (a.lastActivity || 0))
    return a.name.localeCompare(b.name)
  }), [data.projects, sortBy, swarms])

  const counts = useMemo(() => ({
    needs: data.projects.filter((p) => needsOf(p) > 0).length,
    active: data.projects.filter((p) => p.sessions > 0).length,
    unfinished: data.projects.filter((p) => p.unfinished > 0).length,
    all: data.projects.length,
  }), [data.projects, swarms])
  const visible = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return sorted.filter((p) => {
      if (filter === 'needs' && needsOf(p) <= 0) return false
      if (filter === 'active' && p.sessions <= 0) return false
      if (filter === 'unfinished' && p.unfinished <= 0) return false
      if (!kw) return true
      return p.name.toLowerCase().includes(kw) || p.dir.toLowerCase().includes(kw)
    })
  }, [sorted, q, filter, swarms])
  // 「需要你」筛选下一个项目都没有时自动退回「活跃」：空列表不是答案，是死路
  useEffect(() => {
    if (filter === 'needs' && loaded && counts.needs === 0 && counts.all > 0) setFilter('active')
  }, [filter, loaded, counts.needs, counts.all])

  // 置顶与其余共用同一套栅格，只靠 section header 分组（14 §6.1）——两套栅格会让
  // 卡片宽度在分组之间对不齐
  const pinned = visible.filter((p) => p.pinned)
  // 没有会话、也没有待收尾/竞赛的项目折到页尾（图纸 desktop-ia.html §二）：它们和「正在跑
  // 两个任务」的项目占同样大的卡，还被同一行最高的卡撑高，页面下三分之一因此全是空卡。
  const isQuiet = (p: Proj) => p.sessions <= 0 && p.unfinished <= 0 && p.races <= 0
  const rest = visible.filter((p) => !p.pinned && !isQuiet(p))
  // 不活跃那节按「什么时候空下来的」排：刚空的在前，久无人问津的沉底。
  // 跟着上面的通用排序走的话，这一节读起来没有次序感。
  const quiet = visible.filter((p) => !p.pinned && isQuiet(p))
    .sort((a, b) => (b.archivedAt || b.lastActivity || 0) - (a.archivedAt || a.lastActivity || 0))

  // 行动队列与状态条：跨项目，不吃搜索/筛选（它们只作用于下面的栅格）
  const goProject = (key: string) => { location.hash = '#/projects/' + encodeURIComponent(key) }
  const goSwarm = (name: string) => { location.hash = '#/swarm/' + encodeURIComponent(name) }
  const cards = useMemo(
    () => buildNeedCards(data.projects, swarms, t, { openTerm, goProject, goSwarm }),
    [data.projects, swarms, t])
  // 计数走后端的全量字段：top 只有三行，拿它数会漏掉第 4 个以后的会话（#186 的账）
  const stats = {
    running: data.projects.reduce((n, p) => n + runningCount(p), 0),
    waiting: data.projects.reduce((n, p) => n + waitingCount(p), 0),
    unfinished: data.projects.reduce((n, p) => n + (p.unfinished || 0), 0),
    swarms: swarms.length,
  }
  const lastAt = data.projects.reduce((n, p) => Math.max(n, p.lastActivity || 0), 0)

  // 上下左右移动选中：列数从栅格实际算，不写死——它随 Canvas 宽度变
  const onGridKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return
    const grid = e.currentTarget
    const cards = [...grid.querySelectorAll<HTMLElement>('[data-prj-card]')]
    const at = cards.indexOf(document.activeElement as HTMLElement)
    if (at < 0) return
    e.preventDefault()
    const cols = Math.max(1, getComputedStyle(grid).gridTemplateColumns.split(' ').length)
    const step = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' ? -cols : cols
    cards[Math.max(0, Math.min(cards.length - 1, at + step))]?.focus()
  }

  const card = (p: Proj, i: number) => (
    <ProjectCard key={p.key} p={p} swarms={swarms} index={i} openTerm={openTerm} refresh={refresh} />
  )

  return (
    // 这里**不能**加 overflow:auto——任何非 visible 的祖先都会成为 sticky 的
    // 参照系，而这一层并不真的滚动（真正滚的是 .tt-canvas），于是页头永远粘不住。
    <div className="prj-wrap-wide">
      {/* ① 问候 + 状态条 */}
      <WorkbenchHead needs={cards.length} stats={stats} lastAt={lastAt} phone={isPhone}
        onNew={() => setNewOpen(true)}
        onSummaryClick={(f) => { setFilter(f); setQ('') }} />

      {/* ② 行动条：搜索/筛选进行时收成一行（它是跨项目待办，不该被过滤掉） */}
      <NeedsQueue cards={cards} collapsed={!!q.trim() || filter !== 'needs'}
        onViewAll={() => { setQ(''); setFilter('needs') }} />

      {/* ③ 工具条：滚到列表深处时这一条还在——筛选条件跟着内容滚走，等于要滚回顶部才能改 */}
      <div className={`prj-subbar${searching ? ' searching' : ''}`}>
        {/* 筛选与排序合成一条横滑带：手机上它俩各自换行的话，加上搜索框一共占 5 行 */}
        <div className="prj-filters">
          {([
            ['needs', t('project.filterNeeds'), counts.needs],
            ['active', t('project.filterActive'), counts.active],
            ['unfinished', t('project.section.unfinished'), counts.unfinished],
            ['all', t('project.filterAll'), counts.all],
          ] as const).map(([k, label, n]) => (
            <button key={k} type="button" className={`prj-chip${filter === k ? ' on' : ''}`}
              onClick={() => setFilter(k)}>{label}<span className="n">{n}</span></button>
          ))}
          <span className="sp" />
        </div>
        {/* 搜索与排序贴右：左端回答「看什么」（筛选，属于内容），右端放「怎么找」（工具） */}
        {/* 一开始打字就跳出筛选：默认筛选是「需要你」，而搜索是「找这一个项目」的明确动作，
            两者叠加的话搜任何没欠事的项目都只会得到「没有匹配的项目」 */}
        <Input allowClear size="small" value={q}
          onChange={(e) => { const v = e.target.value; setQ(v); if (v.trim() && filter !== 'all') setFilter('all') }}
          ref={searchRef} className="prj-search" onBlur={() => { if (!q) setSearching(false) }}
          placeholder={t('project.searchPlaceholder')} style={{ width: isPhone ? undefined : 200 }} />
        <Dropdown trigger={['click']} menu={{
          selectable: true, selectedKeys: [sortBy],
          items: SORTS.map((k) => ({ key: k, label: t(`project.sort.${k}`) })),
          onClick: ({ key }) => changeSort(key as ProjSort),
        }}>
          <button type="button" className="prj-chip prj-sortpill" aria-label={t('project.sortBy')}>
            {t(`project.sort.${sortBy}`)}{ICON_CHEVRON}
          </button>
        </Dropdown>
        {/* 手机：搜索原地展开、排序进 sheet。两枚图标钉在右侧，不随筛选带横滑跑掉 */}
        <button type="button" className="prj-iconbtn find" aria-label={t('project.searchPlaceholder')}
          onClick={() => { setSearching(true); setTimeout(() => searchRef.current?.focus(), 0) }}>
          {ICON_SEARCH}
        </button>
        <button type="button" className="prj-iconbtn" aria-label={t('project.sortBy')}
          onClick={() => setSortSheet(true)}>{ICON_SORT}</button>
        {searching && (
          <button type="button" className="prj-iconbtn" style={{ display: 'grid', width: 'auto', padding: '0 4px', fontSize: 'var(--fs-meta)' }}
            onClick={() => { setSearching(false); setQ('') }}>{t('common.cancel')}</button>
        )}
      </div>

      <MobileSheet open={sortSheet} title={t('project.sortBy')} onClose={() => setSortSheet(false)}>
        {SORTS.map((k) => (
          <SheetRow key={k} minHeight={44} active={sortBy === k}
            title={t(`project.sort.${k}`)}
            extra={sortBy === k ? <span style={{ color: 'var(--accent)' }}>{ICON_CHECK}</span> : undefined}
            onClick={() => { changeSort(k); setSortSheet(false) }} />
        ))}
      </MobileSheet>

      {/* ④⑥ 栅格 + 最近活动轨（Canvas ≥1180 时右轨 sticky，窄于此落回页尾） */}
      <div className="prj-layout">
        <div className="prj-feed">
          {loaded && data.projects.length === 0 && (
            <div className="prj-empty" style={{ textAlign: 'center', padding: '48px 0' }}>{t('project.empty')}</div>
          )}
          {loaded && data.projects.length > 0 && visible.length === 0 && (
            <div className="prj-empty" style={{ textAlign: 'center', padding: '48px 0' }}>{t('project.noMatch')}</div>
          )}

          {pinned.length > 0 && (
            <div className="prj-sect"><b>{t('project.pinnedSection')}</b><span className="n">{pinned.length}</span><span className="ln" /></div>
          )}
          {pinned.length > 0 && <div className="prj-grid" onKeyDown={onGridKey}>{pinned.map(card)}</div>}
          {pinned.length > 0 && rest.length > 0 && (
            <div className="prj-sect"><b>{t('overview.activeProjects')}</b><span className="n">{rest.length}</span><span className="ln" /></div>
          )}
          {rest.length > 0 && <div className="prj-grid" onKeyDown={onGridKey}>{rest.map(card)}</div>}

          {quiet.length > 0 && (
            <>
              <div className="prj-sect">
                <b>{t('project.quietSection')}</b><span className="n">{quiet.length}</span>
                <span className="hint">{t('project.quietHint')}</span>
                <span className="ln" />
              </div>
              <div>
                {quiet.map((p) => (
                  <div key={p.key} className="prj-quiet" onClick={() => goProject(p.key)}
                    role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); goProject(p.key) } }}>
                    <span className="nm">{p.name}</span>
                    <span className="p" title={p.dir}>{p.dir}</span>
                    <span className="qt">
                      {p.cleanable > 0
                        ? <Tag color="success" style={{ margin: 0 }}>{t('project.cleanableCount', { count: p.cleanable })}</Tag>
                        : (p.archivedAt ? t('project.quietSince', { when: relTime(p.archivedAt, t) }) : null)}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* ⑤ 散会话：不属于任何项目的会话，放在项目之后，避免被作战地图淹没 */}
          {data.loose.length > 0 && (
            <>
              <div className="prj-sect">
                <b>{t('project.loose')}</b><span className="n">{data.loose.length}</span>
                <span className="hint">{t('project.looseHint')}</span>
                <span className="ln" />
              </div>
              <div>
                {data.loose.map((s) => (
                  <div key={s.name} className="prj-row" onClick={() => openTerm(s.name)}>
                    <span style={{ marginTop: 5, display: 'inline-flex' }}>{dot(false, s.waiting ? 'var(--warn)' : s.running ? 'var(--ok)' : undefined)}</span>
                    <span style={{ fontWeight: 600 }} title={s.name}>{s.label || sessionLabel(s.name)}</span>
                    <span style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-meta)', marginTop: 2 }}>{relTime(s.lastActivity, t)}</span>
                    <span style={{ flex: 1 }} />
                    <span className="acts"><ActBtn icon={<TerminalIcon size={14} />} label={t('project.enter')} /></span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <ActivityRail acts={acts} />
      </div>
      <NewProjectModal open={newOpen} onClose={() => { setNewOpen(false); refresh() }} />
    </div>
  )
}

// ── P3 收尾抽屉：孤儿 worktree 的三选一（合并并删除 / 复活 / 丢弃删除）──
// 合并档走 POST /git/worktree/finish（冻结 expectedHead→wip→merge→remove→留痕，
// 08 §5.4）；复活 = 新命令行进入；丢弃 = force remove。损失清单先行。
function FinishModal({ w, base, onClose, onDone, onRevive }: {
  w: any | null; base: string
  onClose: () => void; onDone: () => void; onRevive: (w: any) => void
}) {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [mode, setMode] = useState<'merge' | 'revive' | 'discard'>('merge')
  const [strategy, setStrategy] = useState<'squash' | 'merge' | 'rebase'>('squash')
  const [delBranch, setDelBranch] = useState(true)
  const [diff, setDiff] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!w) return
    // 已合入（10 §5）：丢弃升为推荐首选——零损失，只是删掉本地载体
    // 收养来的分支（开工时选的「已有分支」）不是随工作区建的：默认不勾「删分支」，
    // 那是用户自己的东西，删了它连 reflog 之外都不剩什么
    setMode(w.mergedInto ? 'discard' : 'merge'); setStrategy('squash'); setDelBranch(!w.adopted); setDiff(null)
    api('GET', `/git/worktree/diff?path=${encodeURIComponent(w.path)}`)
      .then((r) => setDiff(r?.data || null)).catch(() => {})
  }, [w])
  if (!w) return null
  const merged = !!w.mergedInto
  const wtBase = w.base || base
  const uncommitted = (diff?.workingTree?.files?.length || 0) + (diff?.untracked ?? w.untracked ?? 0)
  const ok = async () => {
    if (mode === 'revive') { onRevive(w); onClose(); return }
    setBusy(true)
    try {
      if (mode === 'merge') {
        await api('POST', '/git/worktree/finish', { path: w.path, strategy, expectedHead: w.head, deleteBranch: delBranch })
        message.success(t('project.finish.merged', { base: wtBase }))
      } else {
        await api('POST', '/git/worktree/remove', { path: w.path, forceWorktree: true, deleteBranch: delBranch, forceDeleteBranch: delBranch })
        message.success(t('project.finish.discarded'))
      }
      onClose(); onDone()
    } catch (e: any) {
      const ae = e.apiError || {}
      message.error(ae.stage ? t('worktree.close.failedAtStage', { stage: ae.stage, msg: e.message }) : e.message)
    } finally { setBusy(false) }
  }
  const radio = (k: typeof mode, title: any, desc: string, danger?: boolean) => (
    <div onClick={() => setMode(k)} style={{
      display: 'flex', gap: 'var(--sp-2)', padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
      border: `1px solid ${mode === k ? 'rgba(88,166,255,.6)' : 'var(--border)'}`,
      background: mode === k ? 'rgba(31,111,235,.09)' : 'transparent',
    }}>
      <span style={{
        width: 14, height: 14, borderRadius: '50%', marginTop: 3, flex: '0 0 14px',
        border: `1.5px solid ${mode === k ? 'var(--accent)' : 'var(--text-dimmer)'}`,
        background: mode === k ? 'radial-gradient(circle at center, var(--accent) 40%, transparent 45%)' : 'transparent',
      }} />
      <span style={{ minWidth: 0 }}>
        <b style={{ display: 'block', fontSize: 13.5, color: danger ? '#f85149' : undefined }}>{title}</b>
        <span style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dim)' }}>{desc}</span>
      </span>
    </div>
  )
  return (
    <Modal open onCancel={onClose} onOk={ok} okText={t('project.finish.ok')} confirmLoading={busy}
      okButtonProps={mode === 'discard' && !merged ? { danger: true } : undefined}
      title={<span>{t('project.finish.title')} <span className="tt-branch" style={{ marginLeft: 4 }}><BranchIcon size={10} />{w.branch}</span></span>} destroyOnClose>
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <div className="prj-mono" style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dim)', lineHeight: 1.8, padding: '9px 12px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--r-sm)', background: 'var(--bg-term)' }}>
          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('project.finish.kept', { path: w.path })}</div>
          {/* 已合入：损失清单换成绿色定心丸（10 §5），未提交改动仍如实提示 */}
          {merged
            ? (<>
              <div style={{ color: 'var(--ok)' }}>{t('project.finish.mergedRemote', { target: w.mergedInto, kind: w.mergedKind })}</div>
              {uncommitted > 0 && <div style={{ color: '#d29922' }}>{t('project.finish.uncommitted', { count: uncommitted })}</div>}
            </>)
            : <div>{t('project.finish.stats', { base: wtBase || '?', ahead: w.committedAhead, dirty: uncommitted })}</div>}
        </div>
        {(diff?.committed?.files?.length || 0) > 0 && (
          <div>
            <div style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dim)', marginBottom: 5 }}>{t('project.finish.take', { base: wtBase })}</div>
            <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 'var(--r-sm)', padding: '4px 2px', maxHeight: 160, overflow: 'auto' }}>
              {diff.committed.files.slice(0, 20).map((f: any) => (
                <div key={f.path} className="prj-mono" style={{ display: 'flex', gap: 8, padding: '3px 10px', fontSize: 'var(--fs-meta)' }}>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.path}</span>
                  {f.binary ? <span style={{ color: 'var(--text-dimmer)' }}>bin</span> : (<span style={{ flex: '0 0 auto' }}>
                    <span style={{ color: 'var(--ok)' }}>+{f.adds}</span> <span style={{ color: '#f85149' }}>-{f.dels}</span>
                  </span>)}
                </div>
              ))}
            </div>
            {uncommitted > 0 && <div style={{ fontSize: 'var(--fs-meta)', color: '#d29922', marginTop: 5 }}>{t('project.finish.uncommitted', { count: uncommitted })}</div>}
          </div>
        )}
        {radio('merge', <>
          {t('project.finish.optMerge', { base: wtBase || '?' })}
          <Select size="small" value={strategy} onChange={(v) => setStrategy(v)} style={{ marginLeft: 8, minWidth: 96 }}
            onClick={(e) => e.stopPropagation()}
            options={[{ value: 'squash', label: 'squash' }, { value: 'merge', label: 'merge' }, { value: 'rebase', label: 'rebase' }]} />
        </>, t('project.finish.optMergeDesc'))}
        {radio('revive', t('project.finish.optRevive'), t('project.finish.optReviveDesc'))}
        {merged
          ? radio('discard', t('project.finish.optDiscard'), t('project.finish.optDiscardMergedDesc', { target: w.mergedInto }))
          : radio('discard', t('project.finish.optDiscard'), t('project.finish.optDiscardDesc', { ahead: w.committedAhead }), true)}
        {mode !== 'revive' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>
            <input type="checkbox" checked={delBranch} onChange={(e) => setDelBranch(e.target.checked)} style={{ accentColor: 'var(--accent-solid)' }} />
            {t('project.finish.delBranch', { branch: w.branch })}
            {w.adopted && <span style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)' }}>{t('worktree.adoptedKeepBranch')}</span>}
          </label>
        )}
      </Space>
    </Modal>
  )
}

// 终端捕获 → 尾行预览：去 ANSI/OSC，取最后一行非空输出
function tailLine(raw: string): string {
  const clean = String(raw || '').replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '').replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, '')
  const lines = clean.split('\n').map((l) => l.trim()).filter(Boolean)
  return (lines[lines.length - 1] || '').slice(0, 90)
}

// ── P2 项目主页：头部 + composer(hero) + 任务流/Worktree/编队/活动 ──
function ProjectHome({ proj, allProjects, loaded, openTerm, closeTerm, refresh, activeTerm }: {
  activeTerm?: string | null
  proj?: Proj; allProjects: Proj[]; loaded: boolean; openTerm: (n: string) => void; closeTerm: (n: string) => void; refresh: () => void
}) {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [prefs] = usePreferences()
  const [tab, setTab] = useState<'tasks' | 'wt' | 'race' | 'act' | 'files'>('tasks')
  const [wtsAll, setWtsAll] = useState<any[]>([])
  const [defBranch, setDefBranch] = useState('')
  const [sessions, setSessions] = useState<any[]>([])
  const [ann, setAnn] = useState<Record<string, any>>({})
  const agentKinds = useAgentKinds()
  const [cc, setCc] = useState<Record<string, boolean>>({})
  const [cx, setCx] = useState<Record<string, boolean>>({})
  const [needsInput, setNeedsInput] = useState<Record<string, boolean>>({})
  const [races, setRaces] = useState<any[]>([])
  const [swarms, setSwarms] = useState<any[]>([])
  const [swarmOpen, setSwarmOpen] = useState(false)
  // 「＋ 开始」的主动作：回到 composer 并聚焦——这一页最主要的事就是在这儿描述需求
  const composerRef = useRef<HTMLDivElement>(null)
  const composerApi = useRef<TaskComposerHandle>(null)
  const focusComposer = () => {
    composerRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    composerApi.current?.focus()
  }
  const [activity, setActivity] = useState<any[]>([])
  const [finishing, setFinishing] = useState<any>(null)
  const [swarmExtras, setSwarmExtras] = useState<Record<string, { cols: Record<string, number>; last?: any }>>({})
  const [saying, setSaying] = useState<string>('') // 给指挥发话的目标蜂群名
  const [sayText, setSayText] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [peeks, setPeeks] = useState<Record<string, string>>({})
  const [creating, setCreating] = useState(false)
  const [wtOpen, setWtOpen] = useState(false)
  const [gitOpen, setGitOpen] = useState(false)
  const [gitAt, setGitAt] = useState<{ dir: string; tab: 'changes' | 'base' } | null>(null) // Git 面板落点（分叉图「对比 base」用）
  const [mergingWt, setMergingWt] = useState('')
  const [forking, setForking] = useState<string | null>(null)
  const [closing, setClosing] = useState<{ name: string; st: any } | null>(null)
  const [raceOpen, setRaceOpen] = useState(false)
  const [compareRace, setCompareRace] = useState<any>(null)
  const dir = proj?.dir || ''
  const isGit = !!proj?.git

  // worktree 清单（含 main，用于 HEAD 展示；「已有(N)」与任务流用非 main 子集）
  useEffect(() => {
    if (!dir || !isGit) { setWtsAll([]); return }
    let stop = false
    const loadWts = () => api('GET', `/git/worktrees?dir=${encodeURIComponent(dir)}`).then((r) => {
      if (stop) return
      setWtsAll(Array.isArray(r?.data) ? r.data : [])
    }).catch(() => {})
    loadWts()
    const i = setInterval(loadWts, 5000)
    return () => { stop = true; clearInterval(i) }
  }, [dir, isGit])
  useEffect(() => {
    if (!dir || !isGit) return
    api('GET', `/git/branches?dir=${encodeURIComponent(dir)}`).then((r) => {
      const def = r?.data?.default || ''
      setDefBranch(def)
    }).catch(() => {})
  }, [dir, isGit])
  // 远端轻量同步（10 §3 驻留档）：进项目页即同步一次，驻留期间每 5 分钟一次；
  // 失败静默（判定退回本地），worktree 轮询自然吃到新判定。
  useEffect(() => {
    if (!dir || !isGit) return
    const sync = () => api('POST', '/git/worktree/sync', { dir }).catch(() => {})
    sync()
    const i = setInterval(sync, 5 * 60_000)
    return () => clearInterval(i)
  }, [dir, isGit])
  const wts = useMemo(() => wtsAll.filter((w: any) => !w.isMain && !w.prunable), [wtsAll])
  const mainWt = useMemo(() => wtsAll.find((w: any) => w.isMain), [wtsAll])
  const mainHead = useMemo(() => (wtsAll.find((w: any) => w.isMain)?.head || '').slice(0, 7), [wtsAll])
  // 会话 + 归属注解（任务流数据源，与会话页同两条接口）
  useEffect(() => {
    let stop = false
    const loadSess = () => api('GET', '/sessions?tree=1').then((roots) => {
      if (stop) return
      const flat: any[] = []
      const walk = (nodes: any[]) => { for (const n of nodes || []) { flat.push(n); walk(n.children) } }
      walk(Array.isArray(roots) ? roots : [])
      setSessions(flat)
    }).catch(() => {})
    const loadAnn = () => api('GET', '/sessions/annotations').then((r) => { if (!stop) setAnn(r?.data || {}) }).catch(() => {})
    loadSess(); loadAnn()
    const i = setInterval(() => { loadSess(); loadAnn() }, 5000)
    return () => { stop = true; clearInterval(i) }
  }, [dir])
  // 竞赛（编队 tab + 任务计数）
  useEffect(() => {
    if (!isGit) return
    let stop = false
    const loadRaces = () => api('GET', '/races').then((r) => {
      if (!stop) setRaces((Array.isArray(r?.data) ? r.data : []).filter((x: any) => x.dir === dir))
    }).catch(() => {})
    loadRaces()
    const i = setInterval(loadRaces, 8000)
    return () => { stop = true; clearInterval(i) }
  }, [dir, isGit])
  // 编队 tab 才拉的重数据（P5 帧一）：看板列计数 + 广场最后一条（15s）
  useEffect(() => {
    if (tab !== 'race' || !swarms.length) return
    let stop = false
    const loadExtras = () => swarms.forEach(async (sw: any) => {
      try {
        const [board, feed] = await Promise.all([
          api('GET', `/swarms/${encodeURIComponent(sw.name)}/board`).catch(() => []),
          api('GET', `/swarms/${encodeURIComponent(sw.name)}/feed?n=1`).catch(() => []),
        ])
        if (stop) return
        const cols: Record<string, number> = {}
        for (const c of (Array.isArray(board) ? board : [])) cols[c.col] = (cols[c.col] || 0) + 1
        const posts = Array.isArray(feed) ? feed : []
        setSwarmExtras((m) => ({ ...m, [sw.name]: { cols, last: posts[posts.length - 1] } }))
      } catch {}
    })
    loadExtras()
    const i = setInterval(loadExtras, 15000)
    return () => { stop = true; clearInterval(i) }
  }, [tab, swarms])

  // 活动流（懒加载：切到活动 tab 才拉，60s 后端缓存）
  useEffect(() => {
    if (tab !== 'act' || !proj) return
    let stop = false
    // 活动流 = git log(commits) ∪ 收尾留痕(traces)，按时间合并倒序（08 §2.2）
    const loadAct = () => api('GET', `/projects/${encodeURIComponent(proj.key)}/activity`)
      .then((r) => {
        if (stop) return
        const commits = (r?.data?.commits || []).map((x: any) => ({ ...x, kind: 'commit' }))
        const traces = (r?.data?.traces || []).map((x: any) => ({ ...x, kind: 'trace' }))
        setActivity([...commits, ...traces].sort((a, b) => (b.at || 0) - (a.at || 0)))
      }).catch(() => {})
    loadAct()
    const i = setInterval(loadAct, 30000)
    return () => { stop = true; clearInterval(i) }
  }, [tab, proj?.key])

  const mine = useMemo(() => {
    if (!dir) return []
    if (isGit) return sessions.filter((s) => ann[s.name]?.primary?.repo === dir)
    // 非 git 项目：按 pane cwd 目录前缀认领（对齐后端 project.go 的两阶段归属），
    // 而不是只取 P1 卡片的 top(≤2)——否则该项目的第 3+ 个会话在详情页永远不出现。
    // 已被某 git 仓库认领的会话(annotation 有 primary.repo)排除，避免嵌套 git 子项目
    // 的会话重复挂到非 git 父目录下。
    // 归属看会话钉死的 home 目录（annotation.home），不是实时 cwd：在会话里 cd 出去
    // 不该让它掉出项目。后端没给 home（老后端/刚起的会话）才退回 ls 的实时 cwd。
    const homeOf = (s: any) => ann[s.name]?.home || s.cwd
    const under = (c: string) => !!c && (c === dir || c.startsWith(dir + '/'))
    // 同一会话归最深(最长前缀)的非 git 项目：排除落在更具体的非 git 兄弟项目里的会话，
    // 与后端最长前缀口径一致，否则父项目详情页会把子项目会话重复计入（外层少、里层多）。
    const deeper = allProjects.filter((p) => !p.git && p.dir !== dir && p.dir.startsWith(dir + '/')).map((p) => p.dir)
    const claimedByDeeper = (c: string) => deeper.some((d) => c === d || c.startsWith(d + '/'))
    return sessions.filter((s) => !ann[s.name]?.primary?.repo && under(homeOf(s)) && !claimedByDeeper(homeOf(s)))
  }, [sessions, ann, dir, isGit, allProjects])
  // 蜂群归属（08 §2.2）：两条判据取并集
  //  1) 蜂群自报的工作目录 dir == 本项目目录（swarm new/adopt --dir 落库，CLI 建的群靠这条）
  //  2) 「指挥/成员会话 ∈ 本项目会话」现算（老蜂群没有 dir，保留兼容）
  // 光靠 2) 不够：项目会话来自 ttmux ls --json，而它按设计过滤掉所有蜂群会话，
  // 于是 CLI 建的群 inProj 恒为 0、永远不显示（issue #125）。
  const mineKey = useMemo(() => mine.map((s) => s.name).sort().join('\n'), [mine])
  useEffect(() => {
    if (!isGit) return
    let stop = false
    const loadSwarms = async () => {
      try {
        const list = await api('GET', '/swarms')
        const names = new Set(mineKey.split('\n').filter(Boolean))
        const here = normDir(dir)
        const active = (Array.isArray(list) ? list : []).filter((s: any) => s.status !== 'archived')
        const out: any[] = []
        await Promise.all(active.map(async (sw: any) => {
          try {
            const st = await api('GET', `/swarms/${encodeURIComponent(sw.name)}`)
            const members = (st?.members || []) as any[]
            const inProj = members.filter((m: any) => names.has(m.session)).length + (st?.supervisor && names.has(st.supervisor) ? 1 : 0)
            const swDir = normDir(sw.dir || st?.dir || '')
            const byDir = !!here && !!swDir && swDir === here
            const roster = members.length + (st?.supervisor ? 1 : 0)
            // 认了 dir 的群，整支班子都算本项目的：它的会话本来就被 ls 过滤掉了，
            // 按会话数算会显示成 0/N 且每行都标「跨项目」。
            if (inProj > 0 || byDir) out.push({ ...sw, inProj: byDir ? roster : inProj, byDir, roster, supervisor: st?.supervisor || '', members })
          } catch {}
        }))
        if (!stop) setSwarms(out.sort((a, b) => String(a.name).localeCompare(String(b.name))))
      } catch {}
    }
    loadSwarms()
    const i = setInterval(loadSwarms, 10000)
    return () => { stop = true; clearInterval(i) }
  }, [isGit, mineKey, dir])
  // Agent 运行标注 + 待输入检测（仅本项目会话，量小）
  useEffect(() => {
    let stop = false
    const check = () => mine.forEach(async (s: any) => {
      try { const r = await api('GET', `/sessions/${encodeURIComponent(s.name)}/claude`); if (!stop) setCc((m) => ({ ...m, [s.name]: !!r.data?.running })) } catch {}
      try { const r = await api('GET', `/sessions/${encodeURIComponent(s.name)}/codex`); if (!stop) setCx((m) => ({ ...m, [s.name]: !!r.data?.running })) } catch {}
      try { const r = await api('GET', `/sessions/${encodeURIComponent(s.name)}/capture?lines=50`); if (!stop) setNeedsInput((m) => ({ ...m, [s.name]: !!detectPrompt(r.data || '') })) } catch {}
    })
    if (mine.length) check()
    const i = setInterval(() => { if (mine.length) check() }, 6000)
    return () => { stop = true; clearInterval(i) }
  }, [mine])
  // 展开的 worktree 的命令行尾行预览（懒加载，5s）
  useEffect(() => {
    const names = wts.filter((w: any) => expanded[w.path]).flatMap((w: any) => (w.sessions || []).map((x: any) => x.session))
    if (!names.length) return
    let stop = false
    const peek = () => names.forEach(async (n: string) => {
      try { const r = await api('GET', `/sessions/${encodeURIComponent(n)}/capture?lines=8`); if (!stop) setPeeks((m) => ({ ...m, [n]: tailLine(r.data) })) } catch {}
    })
    peek()
    const i = setInterval(peek, 5000)
    return () => { stop = true; clearInterval(i) }
  }, [wts, expanded])

  // session → 蜂群成员映射（任务流 ⬡ 分组 + 成员标签的数据源）
  const swarmMap = useMemo(() => {
    const m: Record<string, { swarm: string; role: string; subrole?: string; done?: boolean }> = {}
    for (const sw of swarms) {
      if (sw.supervisor) m[sw.supervisor] = { swarm: sw.name, role: 'leader' }
      for (const mem of (sw.members || [])) {
        if (mem.session) m[mem.session] = { swarm: sw.name, role: mem.role === 'leader' || mem.role === 'master' ? 'leader' : 'member', subrole: mem.subrole, done: !!mem.done }
      }
    }
    return m
  }, [swarms])

  const orphans = useMemo(() => wts.filter((w: any) => !w.external && !(w.sessions?.length)), [wts])
  // 三桶（10 §5）：已合入·待清理（绿，零损失一键清）/ 真·未合并（黄，三选一决策，
  // 含「已合入但有未提交改动」）/ 干净（老 ⇥ 语义，ahead=0）
  const wtDirty = (w: any) => w.dirty > 0 || w.untracked > 0
  // 判据与后端概览 (api/project.go) 对齐：cleanable = 已合入 ∧ 无未提交改动，不看
  // committedAhead——S1 祖先(FF)合入 committedAhead==0 也算零损失可清，否则外层「可清理」
  // 计数与详情页对不上（详情把它落进「干净」桶、丢了已合入徽标）。
  // git 生命周期三态细化（已提交→已推送→已合入）：pushed 来自后端本地 ref 判定，
  // 把旧「待收尾」黄条里「本地已提交未推送」与「已推送待合入」拆成两态。
  const wtStage = (w: any): 'merged' | 'pushed' | 'committed' | 'clean' =>
    w?.mergedInto ? 'merged' : w?.committedAhead > 0 ? (w?.pushed ? 'pushed' : 'committed') : 'clean'
  const cleanable = orphans.filter((w: any) => w.mergedInto && !wtDirty(w))
  const unfinished = orphans.filter((w: any) => (w.committedAhead > 0 || wtDirty(w)) && !(w.mergedInto && !wtDirty(w)))
  const clean = orphans.filter((w: any) => !w.mergedInto && !(w.committedAhead > 0 || wtDirty(w)))
  const wtOf = (s: any) => wts.find((w: any) => w.path === ann[s.name]?.primary?.worktree)

  // 图片上传到 /tmp 并把绝对路径插进需求框：开干时路径会随命令传给 agent，模型按绝对路径读图（同对话页 Ctrl+V）
  // 新开命令行（P4）：shell = 裸会话；agent = 会话 + 启动命令。孤儿复活/外部收编同款。
  const newCli = async (w: any, kind: 'shell' | AgentKind) => {
    const base = (w.branch || 'wt').replace(/[^a-zA-Z0-9_.-]+/g, '-')
    const name = `${base}-${({ shell: 'sh', claude: 'cc', codex: 'cx', pi: 'pi', opencode: 'oc' } as const)[kind]}`
    try {
      const res = await api('POST', '/sessions', { name, dir: w.path })
      const actual = res.name || name
      if (kind !== 'shell') {
        const cmd = agentCommand(kind, prefs)
        await api('POST', '/tasks/_/send', { sess: actual, msg: cmd })
      }
      message.success(t('session.created')); openTerm(actual); refresh()
    } catch (e: any) { message.error(e.message) }
  }
  // 纯命令行：项目目录里开一个裸 shell 会话（同名已存在则直接进入，不重复建）
  // ＋命令行：每次都开一个新命令行会话（一个项目可有多个）；名字冲突就递增后缀。
  // 已开的命令行会话 cwd 落在项目根，annotation 归属本项目 → 都列在「任务」活动区，可再进入。
  const newShell = async () => {
    if (!proj) return
    const base = proj.name + '-sh'
    const taken = new Set(sessions.map((s) => s.name))
    let name = base
    for (let i = 2; taken.has(name); i++) name = base + i
    try {
      const res = await api('POST', '/sessions', { name, dir })
      message.success(t('session.created')); openTerm(res.name || name); refresh()
    } catch (e: any) { message.error(e.message) }
  }
  // 复制项目 id（不可变身份，日志/台账/接口都按它对齐）
  const copyId = async () => {
    if (!proj) return
    try {
      await navigator.clipboard.writeText(proj.key)
      message.success(t('project.idCopied'))
    } catch { message.error(t('common.copyFailed')) }
  }
  // 重命名 = 改 displayName 偏好（空值回退目录名，id/目录不变）
  const rename = async (v: string) => {
    if (!proj || v.trim() === proj.name) return
    try {
      await api('PATCH', `/projects/${encodeURIComponent(proj.key)}/prefs`, { displayName: v.trim() })
      message.success(t('project.renamed')); refresh()
    } catch (e: any) { message.error(e.message) }
  }
  // 收尾（W7 三选一）：会话在 worktree 内走 CloseWorktreeModal；否则普通关闭
  const beginClose = async (n: string) => {
    let st: any = null
    try { st = (await api('GET', `/sessions/${encodeURIComponent(n)}/worktree-status`))?.data } catch {}
    if (!st?.inWorktree || st.external) {
      Modal.confirm({
        title: t('project.killConfirm', { name: n }),
        onOk: async () => { try { await api('DELETE', '/sessions/' + encodeURIComponent(n)); message.success(t('session.closed')); closeTerm(n); refresh() } catch (e: any) { message.error(e.message) } },
      })
      return
    }
    setClosing({ name: n, st })
  }

  if (!proj) {
    return (
      <div style={{ padding: 24, color: 'var(--text-dim)' }}>
        {loaded ? t('project.notFound') : <Spin />}
        <div style={{ marginTop: 12 }}><a onClick={() => { location.hash = '#/projects' }}>‹ {t('project.back')}</a></div>
      </div>
    )
  }

  const sect = (label: string, count: number, tone?: 'warn' | 'ok') => (
    <div className={`prj-sect${tone ? ' ' + tone : ''}`}>
      <b>{label}</b><span className="n">{count}</span><span className="ln" />
    </div>
  )
  // ── Worktree 分叉图的就地操作（设计 11 §8.3：三个动作都在行内做完，不再跳面板）──
  // 对比 base：把 Git 面板开到这条 worktree 上并直接落在「对比 base」tab
  const compareWt = (w: any) => setGitAt({ dir: w.path, tab: 'base' })
  const mergeWt = async (w: any, strategy: 'merge' | 'squash' | 'rebase') => {
    if (mergingWt) return
    setMergingWt(w.path)
    try {
      await api('POST', '/git/worktree/merge', { path: w.path, strategy, expectedHead: w.head })
      message.success(t('git.wt.mergeDone', { base: w.base }))
      refresh()
    } catch (e: any) {
      const ae = e.apiError
      if (ae?.code === 'MERGE_CONFLICT') {
        Modal.error({
          title: t('worktree.mergeConflictTitle'),
          content: (
            <div style={{ fontSize: 13 }}>
              <div style={{ marginBottom: 6 }}>{t('worktree.mergeConflictDesc', { stage: ae.stage || '?' })}</div>
              <ul style={{ paddingLeft: 18, margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 'var(--fs-meta)' }}>
                {(ae.conflictFiles || []).map((cf: string) => <li key={cf}>{cf}</li>)}
              </ul>
            </div>
          ),
        })
      } else message.error(e.message)
    } finally { setMergingWt('') }
  }
  // 删除：先把「会丢什么」摆出来再确认。分支一律留着——真要连分支删走「一键清理」那条零损失路径。
  const removeWt = (w: any) => {
    const dirty = (w.dirty || 0) + (w.untracked || 0)
    Modal.confirm({
      title: t('project.wt.deleteConfirm', { branch: w.branch || w.path }),
      content: (
        <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dim)', lineHeight: 1.8 }}>
          <div>{t('project.wt.deleteKeepsBranch', { branch: w.branch || '?' })}</div>
          {dirty > 0 && <div style={{ color: '#d29922' }}>{t('project.wt.deleteLosesDirty', { count: dirty })}</div>}
          {w.committedAhead > 0 && !w.pushed && <div style={{ color: '#d29922' }}>{t('project.wt.deleteUnpushed', { count: w.committedAhead })}</div>}
        </div>
      ),
      okText: t('project.wt.delete'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await api('POST', '/git/worktree/remove', { path: w.path, forceWorktree: dirty > 0 })
          message.success(t('project.wt.deleted')); refresh()
        } catch (e: any) { message.error(e.message) }
      },
    })
  }
  const pruneWts = async () => {
    try {
      const r = await api('POST', '/git/worktree/prune', { dir })
      message.success(r?.data?.output?.trim?.() || t('project.wt.pruned')); refresh()
    } catch (e: any) { message.error(e.message) }
  }
  const wtRowMenu = (w: any, cat: string, live: number): MenuProps => ({
    items: [
      { key: 'open', label: t('project.wt.openFolder') },
      { key: 'copy', label: t('project.wt.copyPath') },
      { key: 'manage', label: t('project.wtManage') },
      { type: 'divider' },
      {
        key: 'delete', label: t('project.wt.delete'), danger: true,
        disabled: live > 0 || cat === 'ext',
      },
    ],
    onClick: ({ key }) => {
      if (key === 'open') setGitAt({ dir: w.path, tab: 'changes' })
      else if (key === 'copy') navigator.clipboard?.writeText(w.path).then(() => message.success(t('common.copied')), () => {})
      else if (key === 'manage') setWtOpen(true)
      else if (key === 'delete') removeWt(w)
    },
  })

  // 已合入·待清理的一键清（10 §5）：零损失确认后删 worktree + 本地分支（留痕 cleaned）
  const cleanupMerged = (w: any) => {
    Modal.confirm({
      title: t('project.cleanupConfirm', { branch: w.branch }),
      content: t('project.cleanupConfirmDesc', { target: w.mergedInto }),
      okText: t('project.cleanup'),
      onOk: async () => {
        try {
          await api('POST', '/git/worktree/remove', { path: w.path, deleteBranch: !w.adopted, forceDeleteBranch: !w.adopted })
          message.success(t('project.cleaned'))
          refresh()
        } catch (e: any) { message.error(e.message) }
      },
    })
  }

  // 任务行：生命周期导轨 = 建(必亮)→干(agent 跑)→审(待输入/有未合并)→并(merged)
  // 状态点语义（设计 W2）：绿 = agent 正在干活，黄 = 待输入，其余一律灰。
  const row = (s: any, i: number) => {
    const a = ann[s.name] || {}
    const hit = a.primary || {}
    const isChild = !!s.parent && mine.some((x) => x.name === s.parent)
    const w = wtOf(s)
    const ahead = w?.committedAhead || 0
    const changes = (w?.dirty || 0) + (w?.untracked || 0)
    const gs = wtStage(w)
    const merged = gs === 'merged'
    const running = !!agentKinds[s.name] || cc[s.name] || cx[s.name]
    const waiting = needsInput[s.name]
    // 休眠：机器重启带走了 tmux 那一半，点开即恢复。它没有进程，
    // 所以生命周期导轨/未提交改动那些运行时判断对它都不适用。
    const dormant = s.state === 'dormant' 
    let done = 2, cur: number | undefined, stage = t('project.stage.idle')
    if (running && !waiting) { done = 1; cur = 2; stage = t('project.stage.doing') }
    else if (waiting) { done = 2; cur = 3; stage = t('project.stage.review') }
    else if (gs === 'merged') { done = 4; stage = t('project.stage.merged') } // 合入检测（10 §5）：导轨走满
    else if (gs === 'pushed') { done = 3; cur = 4; stage = t('project.stage.pushed') } // 已推送待合入：审毕、并在跑
    else if (gs === 'committed') { done = 2; cur = 3; stage = t('project.stage.committed') } // 本地已提交未推送
    // 告诉**当前**会话怎么跟这一行说话。和拖拽同一件事、同一段介绍词——
    // 拖拽在触屏上根本不存在（HTML5 DnD 没有触摸事件），在桌面上也可能被
    // 选区拖拽之类的东西抢走，所以必须有一条不依赖手势的路。
    const tellCurrent = async () => {
      if (!activeTerm) { message.warning(t('pair.noCurrent')); return }
      const drag = {
        id: s.name, label: s.label || sessionLabel(s.name),
        project: proj.name, dir: hit.worktree || proj.dir,
        agent: agentKinds[s.name] || (cc[s.name] ? 'claude' : cx[s.name] ? 'codex' : ''),
      }
      const v = canDrop(drag, { id: activeTerm })
      if (!v.ok) { message.warning(t('pair.cannotSelf')); return }
      try {
        await api('POST', '/tasks/_/send', { sess: activeTerm, msg: buildIntro(drag, activeTerm, t) })
        message.success(t('pair.sent', { name: sessionDisplay(activeTerm), peer: drag.label }))
      } catch (e: any) { message.error(e.message) }
    }
    // 从这一行开的会话：行保持选中并给细蓝边，页面与终端的对应关系不靠记（14 §6.3.1）
    const rowNode = (
      <div key={s.name} className={`prj-row prj-in${activeTerm === s.name ? ' on' : ''}`}
        aria-current={activeTerm === s.name ? 'true' : undefined}
        style={{ marginLeft: isChild ? 22 : 0, animationDelay: `${Math.min(i, 8) * 40}ms` }}
        // 拖到终端标签上 = 告诉那个会话怎么跟这个会话说话（21 设计）。
        // 自定义 MIME：用 text/plain 会被文件区/终端当成路径拖拽接走。
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(SESSION_MIME, JSON.stringify({
            id: s.name, label: s.label || sessionLabel(s.name),
            project: proj.name, dir: hit.worktree || proj.dir,
            agent: agentKinds[s.name] || (cc[s.name] ? 'claude' : cx[s.name] ? 'codex' : ''),
            node: currentNodeId() || '',
          }))
          e.dataTransfer.effectAllowed = 'copy'
        }}
        onClick={() => openTerm(s.name)}>
        <span style={{ marginTop: 7, display: 'inline-flex' }}>{dot(false, waiting ? '#d29922' : running ? 'var(--ok)' : undefined, dormant)}</span>
        {isChild && <span style={{ color: 'var(--swarm)', marginTop: 3, display: 'inline-flex' }}><BranchIcon size={12} /></span>}
        <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 700, color: dormant ? 'var(--text-dim)' : undefined }} title={s.name}>{s.label || sessionLabel(s.name)}</span>
            {dormant && (
              <Tag style={{ margin: 0 }} color={s.resumable ? 'blue' : undefined}>
                {t(s.resumable ? 'session.dormant.resumable' : 'session.dormant.hint')}
              </Tag>
            )}
            {hit.linked && hit.branch && <span className="tt-branch" title={hit.branch}><BranchIcon size={10} />{hit.branch}</span>}
            {hit.external && hit.linked && <Tag style={{ margin: 0 }}><WindowsIcon size={11} /></Tag>}
            {swarmMap[s.name]?.role === 'leader' && <Tag color="purple" style={{ margin: 0 }}>{t('project.swarm.leaderTag')}</Tag>}
            {swarmMap[s.name]?.subrole && <Tag style={{ margin: 0 }}>{t(('swarm.subrole.' + swarmMap[s.name]!.subrole) as any) || swarmMap[s.name]!.subrole}</Tag>}
            {swarmMap[s.name]?.done && <Tag color="purple" style={{ margin: 0 }}>{t('project.swarm.integrate')}</Tag>}
            {(agentKinds[s.name] || (cc[s.name] ? 'claude' : cx[s.name] ? 'codex' : undefined)) && <span className="tt-agentmark" title={agentName(agentKinds[s.name] || (cc[s.name] ? 'claude' : 'codex'))}><AgentLogo kind={agentKinds[s.name] || (cc[s.name] ? 'claude' : 'codex')} size={13} /></span>}
            {waiting && <Tag color="warning" style={{ margin: 0 }}>{t('session.waiting')}</Tag>}
            <MemBar mem={s.mem} />
            {a.ambiguous && (
              <Tooltip title={(a.matches || []).map((m: any) => m.worktree).join('\n')}>
                <span style={{ color: '#d29922', display: 'inline-flex' }}><WarnIcon size={13} /></span>
              </Tooltip>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)' }}>
            {!dormant && <><Lifec done={done} cur={cur} /><span>{stage}</span></>}
            {/* 已合入后 ↑n 不再展示（对比远端已零领先，只会误导）；未提交改动照常提示 */}
            {merged && (
              <Tooltip title={`${w.mergedInto} · ${w.mergedKind}`}>
                <span style={{ color: 'var(--ok)', fontSize: 'var(--fs-meta)', display: 'inline-flex', alignItems: 'center', gap: 3 }}><CheckIcon size={12} />{t('project.mergedTag')}</span>
              </Tooltip>
            )}
            {gs === 'pushed' && (
              <Tooltip title={hit.branch ? `origin/${hit.branch}` : undefined}>
                <span style={{ color: 'var(--accent)', fontSize: 'var(--fs-meta)', display: 'inline-flex', alignItems: 'center', gap: 3 }}><PushIcon size={12} />{t('project.pushedTag')}</span>
              </Tooltip>
            )}
            {(!merged && ahead > 0 || changes > 0) && (
              <span className="prj-mono" style={{ fontSize: 'var(--fs-meta)' }}>
                {!merged && ahead > 0 && <span style={{ color: 'var(--accent)', display: 'inline-flex', alignItems: 'center', gap: 1 }}><ArrowUp size={11} />{ahead}</span>}
                {!merged && ahead > 0 && changes > 0 && ' · '}
                {changes > 0 && <span style={{ color: '#d29922' }}>{t('project.wt.changes', { count: changes })}</span>}
              </span>
            )}
            <span>{relTime(s.last_activity, t)}</span>
          </div>
        </div>
        <span className="acts" onClick={(e) => e.stopPropagation()}>
          <ActBtn icon={<TerminalIcon size={14} />} label={t('project.enter')} onClick={() => openTerm(s.name)} />
          {hit.linked && <ActBtn icon={<DiffIcon size={14} />} label={t('project.compare')} onClick={() => setGitOpen(true)} />}
          <ActBtn icon={<ForkIcon size={14} />} label={t('project.forkTask')} onClick={() => setForking(s.name)} />
          {hit.linked
            ? <ActBtn icon={<ArchiveIcon size={14} />} label={t('project.finish')} tone="danger" onClick={() => beginClose(s.name)} />
            : <ActBtn icon={<CloseIcon size={14} />} label={t('common.close')} tone="danger" onClick={() => beginClose(s.name)} />}
        </span>
      </div>
    )
    return (
      <Dropdown key={s.name} trigger={['contextMenu']} menu={{ items: [
        { key: 'tell', disabled: !activeTerm || activeTerm === s.name,
          label: t('pair.tellCurrent', { name: s.label || sessionLabel(s.name) }),
          onClick: () => { void tellCurrent() } },
      ] }}>{rowNode}</Dropdown>
    )
  }

  const tabBtn = (k: typeof tab, label: string, n?: number) => (
    <span key={k} className={`prj-tab${tab === k ? ' on' : ''}`} onClick={() => setTab(k)}>
      {label}{n !== undefined && <span className="n">{n}</span>}
    </span>
  )

  return (
    // 这里**不能**加 overflow:auto——任何非 visible 的祖先都会成为 sticky 的
    // 参照系，而这一层并不真的滚动（真正滚的是 .tt-canvas），于是页头永远粘不住。
    <div>
      <div className="prj-wrap">
        {/* 项目头：面包屑 | 名称 / 路径 · ⎇主干@HEAD | 主操作。sticky（14 §6.2）——
            往下翻任务流时"我在哪个项目、要新建什么"不该跟着滚走。 */}
        <div className="prj-in prj-head" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)' }}>
          <Button type="text" size="small" onClick={() => { location.hash = '#/projects' }}
            style={{ color: 'var(--text-dim)', paddingInline: 6, flex: '0 0 auto' }}>‹ {t('project.title')}</Button>
          <span style={{ width: 1, height: 18, background: 'var(--border-subtle)', flex: '0 0 auto' }} />
          <div style={{ minWidth: 0, flex: 1 }}>
            {/* 名称可编辑 = 重命名（displayName 偏好，key/目录不变） */}
            <Typography.Text style={{ fontSize: 16, fontWeight: 700, display: 'block', whiteSpace: 'nowrap' }}
              ellipsis editable={{ onChange: rename, tooltip: t('project.rename'), triggerType: ['icon'] }}>
              {proj.name}
            </Typography.Text>
            <div className="prj-mono" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)' }}>
              <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={proj.dir}>
                {proj.dir}
                {isGit && defBranch && <span style={{ color: 'var(--text-dim)', display: 'inline-flex', alignItems: 'center', gap: 4 }}> · <BranchIcon size={11} />{defBranch}{mainHead ? ` @ ${mainHead}` : ''}</span>}
              </span>
              {/* 项目 id（不可变，目录搬家也不变）：排障时对着日志/台账查同一个项目 */}
              <Tooltip title={t('project.copyId')}>
                <span onClick={copyId} style={{ flex: '0 0 auto', cursor: 'pointer', opacity: .7 }}>#{proj.key}</span>
              </Tooltip>
            </div>
          </div>
          {isGit && <Button size="small" onClick={() => setGitOpen(true)}>{t('project.gitPanel')}</Button>}
          {/* 「新建会话 / 蜂群 / Race / 命令行」原来散在页头和编队 tab 里，两处入口互相不知道
              对方存在。集中成一枚 split button：主动作 = 回到 composer 描述需求（这一页最主要的
              事），其余进菜单（14 §6.2）。 */}
          {/* 必须包一层并钉住 flex：Dropdown.Button 内部的 Space.Compact 在 flex 容器里
              是块级 flex 子项，会一路撑到 723px，把左边的项目名挤成 0 宽 */}
          <span style={{ flex: '0 0 auto', display: 'inline-flex' }}>
          <Dropdown.Button size="small" type="primary" trigger={['click']}
            onClick={focusComposer}
            menu={{ items: [
              { key: 'shell', label: t('project.shell'), onClick: newShell },
              ...(isGit ? [
                { key: 'swarm', label: t('project.newSwarm'), onClick: () => setSwarmOpen(true) },
                { key: 'race', label: t('project.newRace'), onClick: () => setRaceOpen(true) },
              ] : []),
            ] }}>
            <PlusIcon size={13} /> {t('project.start')}
          </Dropdown.Button>
          </span>
        </div>

        {/* Composer（hero）：需求 ⏎ 开干——抽成 TaskComposer，项目行「+」/ ⌘N 的弹窗用同一份 */}
        <div ref={composerRef}>
          <TaskComposer ref={composerApi} dir={dir} isGit={isGit} openTerm={openTerm} onCreated={() => refresh()} />
        </div>

        {/* Tabs：任务 | Worktree | 编队 | 活动（非 git 只有任务）。同样 sticky，贴在项目头下面 */}
        <div className="prj-tabs prj-in" style={{ animationDelay: '110ms' }}>
          {tabBtn('tasks', t('project.tasks'), mine.length + unfinished.length + cleanable.length + clean.length)}
          {isGit && tabBtn('wt', 'Worktree', wts.length)}
          {isGit && tabBtn('race', t('project.tab.race'), races.length + swarms.length)}
          {isGit && tabBtn('act', t('project.tab.activity'))}
          {tabBtn('files', t('project.tab.files'))}
        </div>

        {/* ── 任务流 ── */}
        {tab === 'tasks' && (<>
          {sect(t('project.section.active'), mine.length)}
          {/* 分组优先级 蜂群 ⬡ > parent 树 > 平铺（08 §2.2）：成员按编队组头聚合，组头 → 蜂群台 */}
          {(() => {
            const groups = new Map<string, any[]>()
            const rest: any[] = []
            for (const s of mine) {
              const sm = swarmMap[s.name]
              if (sm) {
                if (!groups.has(sm.swarm)) groups.set(sm.swarm, [])
                groups.get(sm.swarm)!.push(s)
              } else rest.push(s)
            }
            return (<>
              {[...groups.entries()].map(([swName, rows]) => {
                const sw = swarms.find((x: any) => x.name === swName)
                return (
                  <div key={'g' + swName}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 6px 2px', fontSize: 'var(--fs-sm)', color: 'var(--text-dim)' }}>
                      <span style={{ color: 'var(--swarm)', display: 'inline-flex' }}><SwarmIcon /></span>
                      <b style={{ color: 'var(--text-bright)' }}>{swName}</b>
                      {sw && <span style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)' }}>{t('project.swarm.members', { mine: sw.inProj, total: sw.roster })}</span>}
                      <span style={{ flex: 1 }} />
                      <a style={{ fontSize: 'var(--fs-meta)' }} onClick={() => { location.hash = '#/swarm/' + encodeURIComponent(swName) }}>{t('project.swarm.board')}</a>
                    </div>
                    <div style={{ marginLeft: 6, paddingLeft: 10, borderLeft: '2px solid rgba(163,113,247,.3)' }}>
                      {rows.map(row)}
                    </div>
                  </div>
                )
              })}
              {rest.map(row)}
            </>)
          })()}
          {mine.length === 0 && <div className="prj-empty">{t('project.noTasks')}</div>}

          {cleanable.length > 0 && (<>
            {sect(t('project.section.cleanable'), cleanable.length, 'ok')}
            {cleanable.map((w: any) => (
              <div key={w.path} className="prj-row">
                <span style={{ marginTop: 7, display: 'inline-flex' }}>{dot(false, 'var(--ok)')}</span>
                <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
                    <span className="tt-branch" title={w.branch}><BranchIcon size={10} />{w.branch}</span>
                    <Tooltip title={`${w.mergedInto} · ${w.mergedKind}`}>
                      <Tag color="success" style={{ margin: 0 }} icon={<CheckIcon size={11} />}>{t('project.mergedTag')}</Tag>
                    </Tooltip>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)', flexWrap: 'wrap' }}>
                    <Lifec done={4} /><span>{t('project.stage.merged')}</span>
                    <span className="prj-mono" style={{ fontSize: 'var(--fs-meta)', color: 'var(--ok)' }}>{t('project.mergedInto', { target: w.mergedInto })}</span>
                    <span>{relTime(w.lastCommitAt, t)}</span>
                  </div>
                </div>
                <span className="acts">
                  <ActBtn icon={<TrashIcon size={14} />} label={t('project.cleanup')} tone="ok" onClick={() => cleanupMerged(w)} />
                  <ActBtn icon={<PlayIcon size={13} />} label={t('project.revive')} onClick={() => newCli(w, 'shell')} />
                  <ActBtn icon={<DiffIcon size={14} />} label={t('project.compare')} onClick={() => setGitOpen(true)} />
                </span>
              </div>
            ))}
          </>)}

          {unfinished.length > 0 && (<>
            {sect(t('project.section.unfinished'), unfinished.length, 'warn')}
            {unfinished.map((w: any) => (
              <div key={w.path} className="prj-row warn">
                <span style={{ marginTop: 7, display: 'inline-flex' }}>{dot(false, '#d29922')}</span>
                <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
                    <span className="tt-branch" title={w.branch}><BranchIcon size={10} />{w.branch}</span>
                    <Tag color="warning" style={{ margin: 0 }}>{t('project.sessionClosed')}</Tag>
                    {/* 已合入但还有未提交改动：绿标缓解焦虑，损失只剩 working tree */}
                    {w.mergedInto && (
                      <Tooltip title={`${w.mergedInto} · ${w.mergedKind}`}>
                        <Tag color="success" style={{ margin: 0 }} icon={<CheckIcon size={11} />}>{t('project.mergedTag')}</Tag>
                      </Tooltip>
                    )}
                    {/* 三态细化：已推送未合入——蓝标区分「本地已提交」，收尾丢弃前知道远端还留着 */}
                    {!w.mergedInto && w.pushed && (
                      <Tooltip title={`origin/${w.branch}`}>
                        <Tag color="blue" style={{ margin: 0 }} icon={<PushIcon size={11} />}>{t('project.pushedTag')}</Tag>
                      </Tooltip>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)', flexWrap: 'wrap' }}>
                    {w.mergedInto
                      ? <><Lifec done={2} cur={3} /><span>{t('project.stage.unfinished')}</span></>
                      : w.pushed
                        ? <><Lifec done={3} cur={4} /><span>{t('project.stage.pushed')}</span></>
                        : <><Lifec done={2} cur={3} /><span>{t('project.stage.committed')}</span></>}
                    <span className="prj-mono" style={{ fontSize: 'var(--fs-meta)' }}>
                      {w.mergedInto
                        ? <span style={{ color: '#d29922' }}>{t('project.wt.changes', { count: w.dirty + w.untracked })}</span>
                        : t('project.aheadDirty', { ahead: w.committedAhead, dirty: w.dirty + w.untracked })}
                    </span>
                    {/* S3 佐证（10 §4）：远端分支已删只给线索，不替人拍板 */}
                    {!w.mergedInto && w.remoteGone && <span style={{ color: '#d29922', fontSize: 'var(--fs-meta)' }}>{t('project.remoteGoneHint')}</span>}
                    <span>{relTime(w.lastCommitAt, t)}</span>
                  </div>
                </div>
                <span className="acts">
                  <ActBtn icon={<ArchiveIcon size={14} />} label={t('project.finish')} tone="danger" onClick={() => setFinishing(w)} />
                  <ActBtn icon={<PlayIcon size={13} />} label={t('project.revive')} onClick={() => newCli(w, 'shell')} />
                  <ActBtn icon={<DiffIcon size={14} />} label={t('project.compare')} onClick={() => setGitOpen(true)} />
                </span>
              </div>
            ))}
          </>)}

          {clean.length > 0 && (<>
            {sect(t('project.section.clean'), clean.length)}
            {clean.map((w: any) => (
              <div key={w.path} className="prj-row">
                <span style={{ marginTop: 7, display: 'inline-flex' }}>{dot(false, 'var(--swarm)')}</span>
                <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
                    <span className="tt-branch" title={w.branch}><BranchIcon size={10} />{w.branch}</span>
                    <Tag color="purple" style={{ margin: 0 }} icon={<MergeIcon size={11} />}>{t('project.mergedClean')}</Tag>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)' }}>
                    <Lifec done={4} /><span>{t('project.stage.done')}</span>
                  </div>
                </div>
                <span className="acts">
                  <ActBtn icon={<PlayIcon size={13} />} label={t('project.revive')} onClick={() => newCli(w, 'shell')} />
                  <ActBtn icon={<TrashIcon size={14} />} label={t('project.cleanup')} onClick={() => setWtOpen(true)} />
                </span>
              </div>
            ))}
          </>)}
        </>)}

        {/* ── Worktree tab：分叉图（设计 11 §8/G5）──
            主干一条竖线贯穿全表，每条 worktree 从主干分叉出去；状态编码在节点形状上。
            主干必须是整行高的绝对定位元素——行高随内容变，画进每行的 SVG 里必断。 */}
        {tab === 'wt' && (
          <div className="prj-panel prj-in">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', flexWrap: 'wrap' }}>
              <Button size="small" onClick={() => setWtOpen(true)} icon={<PlusIcon size={12} />}>{t('project.wt.newWorktree')}</Button>
              <Button size="small" onClick={pruneWts}>{t('project.wt.prune')}</Button>
              <span style={{ flex: 1 }} />
              <a style={{ fontSize: 'var(--fs-sm)' }} onClick={() => setWtOpen(true)}>{t('project.wt.allRepos')} ›</a>
            </div>

            {mainWt && (
              <div className="prj-fork head">
                <svg width="38" height="44" className="fk">
                  <circle cx="15" cy="22" r="7.4" fill="none" stroke={FORK_TRUNK} strokeWidth="1.4" opacity=".45" />
                  <circle cx="15" cy="22" r="4.2" fill={FORK_TRUNK} />
                </svg>
                <div className="col">
                  <div className="info">
                    <div className="n1">
                      {/* 分支名一律中性：状态由左边那颗节点的颜色说（主干蓝 / 绿在跑 / 琥珀待收尾），
                          名字再各染一色，一列看下来就是三种蓝绿在跳 */}
                      <span className="wt-br">{mainWt.branch || 'HEAD'}</span>
                      <Tag style={{ margin: 0 }}>{t('project.wt.mainTag')}</Tag>
                      <span className="prj-mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-dimmer)' }}>{(mainWt.head || '').slice(0, 7)}</span>
                    </div>
                    <div className="n2">
                      <span className="prj-mono">{mainWt.path}</span>
                      {wts.length > 0 && <> · {t('project.wt.forkCount', { count: wts.length })}</>}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {wts.length === 0 && <div className="prj-empty">{t('project.wt.none')}</div>}

            {wts.map((w: any) => {
              const open = !!expanded[w.path]
              const live = (w.sessions || []).length
              const dirty = (w.dirty || 0) + (w.untracked || 0)
              const cleanable = !!w.mergedInto && dirty === 0
              const cat = w.external ? 'ext' : live > 0 ? 'live' : cleanable ? 'merged' : 'orphan'
              const color = FORK_COLOR[cat]
              return (
                <div key={w.path} className={`prj-fork ${cat}`}>
                  <svg width="38" height="44" className="fk">
                    <path d="M15 2C15 16,23 12,29 22" stroke={color} strokeWidth="1.6" fill="none"
                      strokeDasharray={cat === 'merged' ? '3 3' : undefined} />
                    {cat === 'ext'
                      ? <rect x="25.5" y="18.5" width="7" height="7" transform="rotate(45 29 22)" fill="none" stroke={color} strokeWidth="1.5" />
                      : cat === 'merged'
                        ? <circle cx="29" cy="22" r="4.4" fill="var(--bg-container)" stroke={color} strokeWidth="1.6" />
                        : <>
                            {cat === 'live' && <circle cx="29" cy="22" r="8" fill="none" stroke={color} strokeWidth="1.2" opacity=".35" />}
                            <circle cx="29" cy="22" r="4.6" fill={color} />
                          </>}
                  </svg>
                  {/* 动作区是 .col 的第二列，不能塞进会换行的 .n1——否则名字一长按钮就掉行 */}
                  <div className="col">
                    <div className="info">
                    <div className="n1">
                      <span className="wt-br" onClick={() => setExpanded((m) => ({ ...m, [w.path]: !open }))}
                        style={{ cursor: 'pointer', color: cat === 'merged' || cat === 'ext' ? 'var(--text-dim)' : undefined }}>
                        {w.branch || '(detached)'}
                      </span>
                      {w.committedAhead > 0 && <span className="wt-ab up"><ArrowUp size={10} />{w.committedAhead}</span>}
                      {w.behind > 0 && <span className="wt-ab dn"><ArrowDown size={10} />{w.behind}</span>}
                      {cat === 'live' && <Tag color="green" style={{ margin: 0 }}>{t('project.wt.cli', { count: live })}</Tag>}
                      {cat === 'orphan' && <Tag color="warning" style={{ margin: 0 }}>{t('project.wt.orphanPending')}</Tag>}
                      {cat === 'merged' && <Tag color="success" style={{ margin: 0 }} icon={<CheckIcon size={11} />}>{t('project.wt.mergedInto', { target: w.mergedInto })}</Tag>}
                      {cat === 'ext' && <Tag style={{ margin: 0 }}>{t('project.wt.externalTag')}</Tag>}
                    </div>
                    <div className="n2 prj-mono">
                      {w.external
                        ? <>{w.path} · {t('project.wt.externalNote')}</>
                        : <>
                            <span style={{ color: dirty > 0 ? '#d29922' : undefined }}>{t('project.wt.uncommitted', { count: dirty })}</span>
                            {' · '}
                            {cleanable
                              ? <>{t('project.wt.mergedKind', { kind: w.mergedKind || '?' })} · {t('project.wt.zeroLoss')}</>
                              : w.committedAhead > 0
                                ? <span style={{ color: w.pushed ? undefined : '#d29922' }}>
                                    {w.pushed ? t('project.wt.pushed') : t('project.wt.notPushed', { count: w.committedAhead })}
                                  </span>
                                : t('project.wt.noCommits')}
                            {' · '}{relTime(w.lastCommitAt, t)}
                            {live === 0 && <> · {t('project.wt.noSession')}</>}
                          </>}
                    </div>

                    {open && (
                      <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {(w.sessions || []).map((ref: any) => (
                          <div key={ref.session} className="prj-subrow" onClick={() => openTerm(ref.session)}>
                            {dot(false, agentKinds[ref.session] || cc[ref.session] || cx[ref.session] ? 'var(--ok)' : undefined)}
                            <span style={{ fontWeight: 600, fontSize: 13 }} title={ref.session}>{sessionLabel(ref.session)}</span>
                            {agentKinds[ref.session] && <span className="tt-agentmark" title={agentName(agentKinds[ref.session])}><AgentLogo kind={agentKinds[ref.session]} size={12} /></span>}
                            <span className="prj-peek">{peeks[ref.session] || '…'}</span>
                            <a style={{ fontSize: 'var(--fs-meta)' }} onClick={(e) => { e.stopPropagation(); openTerm(ref.session) }}>{t('project.enter')}</a>
                          </div>
                        ))}
                        {live === 0 && <div style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)', padding: '4px 8px' }}>{t('project.wt.noCli')}</div>}
                        <div className="prj-addline">
                          {t('project.wt.newCli')}
                          {CLI_KINDS.map((kind) => <button key={kind} type="button" className="tt-act" onClick={() => newCli(w, kind)}>{kind === 'shell' ? 'shell' : agentName(kind)}</button>)}
                        </div>
                      </div>
                    )}
                    </div>

                    <span className="wt-acts">
                      {!!w.base && (
                        <Button size="small" onClick={() => compareWt(w)}>
                          {cleanable ? t('project.wt.viewMerged') : t('project.wt.compareWith', { base: w.base })}
                        </Button>
                      )}
                      {cleanable && <Button size="small" onClick={() => cleanupMerged(w)}>{t('project.cleanup')}</Button>}
                      {!cleanable && !w.external && !!w.base && (
                        live === 0 && w.committedAhead === 0 && dirty === 0
                          ? <Dropdown menu={{ items: CLI_KINDS.map((k) => ({ key: k, label: k === 'shell' ? 'shell' : agentName(k) })), onClick: ({ key }) => newCli(w, key as 'shell' | AgentKind) }}>
                              <Button size="small" iconPosition="end" icon={<ChevronDown size={11} />}>{t('project.wt.resume')}</Button>
                            </Dropdown>
                          : <Dropdown.Button size="small" type="primary" disabled={mergingWt === w.path}
                              icon={<ChevronDown size={11} />}
                              onClick={() => mergeWt(w, 'squash')}
                              menu={{ items: [{ key: 'merge', label: 'merge' }, { key: 'rebase', label: 'rebase' }], onClick: ({ key }) => mergeWt(w, key as any) }}>
                              {mergingWt === w.path ? <Spin size="small" /> : t('worktree.mergeInto', { base: w.base })}
                            </Dropdown.Button>
                      )}
                      <Dropdown menu={wtRowMenu(w, cat, live)} trigger={['click']} placement="bottomRight">
                        <Button size="small">⋯</Button>
                      </Dropdown>
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* ── 编队 tab：竞赛 + 蜂群（只列组，编排去对比台/蜂群页）── */}
        {tab === 'race' && (<>
          {races.map((r: any) => (
            <div key={r.id} className="prj-panel prj-in" style={{ padding: '13px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Tag color="gold" style={{ margin: 0 }}>RACE</Tag>
                <b>{r.name}</b>
                <span style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)' }}>{t('project.race.meta', { count: (r.contestants || []).length, base: r.base })}</span>
                <span style={{ flex: 1 }} />
                <Button size="small" type="primary" onClick={() => setCompareRace(r)}>{t('project.race.compare')} →</Button>
              </div>
            </div>
          ))}
          {/* 蜂群卡（P5 帧一）：成员/看板计数/广场尾声只读投影 + 给指挥发话；编排一律去蜂群台 */}
          {swarms.map((sw: any) => {
            const ex = swarmExtras[sw.name]
            const mineNames = new Set(mine.map((x) => x.name))
            // label：蜂群成员的语义名 `<群>-<成员>` / 指挥 cc-<群>。蜂群会话被会话列表
            // 过滤掉（不在全局展示名表里），所以名字要由蜂群接口随行带来。
            const memberRow = (session: string, role: string, subrole?: string, done?: boolean, status?: string, label?: string) => {
              // 按 dir 认领的群：成员会话不在 ls 清单里（被蜂群过滤挡掉），但确实属于本项目
              const inProj = mineNames.has(session) || !!sw.byDir
              const running = !!agentKinds[session] || cc[session] || cx[session] || status === 'running'
              return (
                <div key={session} className="prj-subrow" style={{ opacity: inProj ? 1 : 0.45 }}
                  onClick={() => { if (inProj) openTerm(session) }}>
                  {dot(false, status === 'waiting' ? '#d29922' : running ? 'var(--ok)' : undefined)}
                  <span style={{ fontWeight: 600, fontSize: 13 }} title={session}>{label || sessionLabel(session)}</span>
                  {role === 'leader' && <Tag color="purple" style={{ margin: 0, fontSize: 'var(--fs-micro)', lineHeight: '16px' }}>{t('project.swarm.leaderTag')}</Tag>}
                  {subrole && <Tag style={{ margin: 0, fontSize: 'var(--fs-micro)', lineHeight: '16px' }}>{t(('swarm.subrole.' + subrole) as any) || subrole}</Tag>}
                  {done && <Tag color="purple" style={{ margin: 0, fontSize: 'var(--fs-micro)', lineHeight: '16px' }}>{t('project.swarm.integrate')}</Tag>}
                  {ann[session]?.primary?.linked && <span className="tt-branch" title={ann[session].primary.branch}><BranchIcon size={10} />{ann[session].primary.branch}</span>}
                  <span style={{ flex: 1 }} />
                  {inProj
                    ? <a style={{ fontSize: 'var(--fs-meta)' }} onClick={(e) => { e.stopPropagation(); openTerm(session) }}>{t('project.enter')}</a>
                    : <span style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)' }}>{t('project.swarm.crossProj')}</span>}
                </div>
              )
            }
            return (
              <div key={sw.id || sw.name} className="prj-panel prj-in" style={{ padding: '13px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <Tag color="purple" style={{ margin: 0 }} icon={<SwarmIcon size={11} />}>{t('nav.swarm')}</Tag>
                  <b>{sw.name}</b>
                  {sw.goal && <span style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 280 }}>{sw.goal}</span>}
                  {!sw.supervisor && <Tag color="warning" style={{ margin: 0 }}>{t('project.swarm.noLeader')}</Tag>}
                  <span style={{ flex: 1 }} />
                  {ex && Object.keys(ex.cols).length > 0 && (
                    <span className="prj-mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-dimmer)' }}>
                      {['backlog', 'assigned', 'doing', 'review', 'done'].filter((c) => ex.cols[c]).map((c) => `${t(('swarm.board.col.' + c) as any)} ${ex.cols[c]}`).join(' · ')}
                    </span>
                  )}
                  {/* 无指挥修复入口（09 S2）：群在指挥不在（拉起失败/被杀）→ adopt 接管 */}
                  {!sw.supervisor && (
                    <Button size="small" onClick={async () => {
                      try {
                        await api('POST', `/swarms/${encodeURIComponent(sw.name)}/adopt`, { dir, worktree: true })
                        message.success(t('project.swarm.adopted')); openTerm('cc-' + sw.name)
                      } catch (e: any) { message.error(e.message) }
                    }}>{t('project.swarm.adopt')}</Button>
                  )}
                  <Button size="small" onClick={() => { setSaying(sw.name); setSayText('') }}>{t('project.swarm.sayLeader')}</Button>
                  <Button size="small" type="primary" onClick={() => { location.hash = '#/swarm/' + encodeURIComponent(sw.name) }}>{t('project.swarm.board')} →</Button>
                </div>
                <div style={{ margin: '9px 0 0 5px', paddingLeft: 12, borderLeft: '2px solid rgba(163,113,247,.3)', display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {sw.supervisor && memberRow(sw.supervisor, 'leader', undefined, false, undefined, 'cc-' + sw.name)}
                  {(sw.members || []).filter((m: any) => m.session && m.session !== sw.supervisor)
                    .map((m: any) => memberRow(m.session, m.role, m.subrole, !!m.done, m.status, m.label))}
                </div>
                {ex?.last && (
                  <div className="prj-mono" style={{ display: 'flex', gap: 8, marginTop: 9, padding: '6px 10px', borderRadius: 'var(--r-sm)', background: 'var(--bg-term)', border: '1px solid var(--border-subtle)', fontSize: 'var(--fs-meta)', color: 'var(--text-dim)' }}>
                    <span style={{ color: '#c4a5f9', flex: '0 0 auto' }}>{ex.last.author}</span>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ex.last.text}</span>
                  </div>
                )}
              </div>
            )
          })}
          {races.length === 0 && swarms.length === 0 && <div className="prj-empty">{t('project.formation.empty')}</div>}
          <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
            {/* 新建入口统一收在页头的「＋ 开始」里，这里不再重复（14 §6.2） */}
          </div>
        </>)}

        {/* ── 活动 tab：全部分支近 30 天提交 ── */}
        {tab === 'act' && (
          <div className="prj-panel prj-in" style={{ padding: '6px 4px' }}>
            {activity.map((e: any) => e.kind === 'trace' ? (
              <div key={'t' + e.at + e.branch} className="prj-mono" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', fontSize: 'var(--fs-sm)' }}>
                <span style={{ color: 'var(--swarm)', display: 'inline-flex' }}><MergeIcon /></span>
                <span style={{ color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {e.action === 'merged'
                    ? t('project.act.traceMerged', { branch: e.branch, base: e.base || '?', strategy: e.strategy || 'squash' })
                    : t('project.act.traceDiscarded', { branch: e.branch })}
                </span>
                <span style={{ marginLeft: 'auto', color: 'var(--text-dimmer)', fontSize: 'var(--fs-meta)', flex: '0 0 auto' }}>{relTime(e.at, t)}</span>
              </div>
            ) : (
              <div key={e.oid + e.at} className="prj-mono" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', fontSize: 'var(--fs-sm)' }}>
                <span style={{ color: 'var(--text-dimmer)' }}>{e.oid}</span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.subject}</span>
                <span style={{ marginLeft: 'auto', color: 'var(--text-dimmer)', fontSize: 'var(--fs-meta)', flex: '0 0 auto' }}>
                  {e.refs ? `${String(e.refs).split(',')[0]} · ` : ''}{relTime(e.at, t)}
                </span>
              </div>
            ))}
            {activity.length === 0 && <div className="prj-empty">{t('project.act.empty')}</div>}
            <div style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)', padding: '8px 12px', borderTop: '1px dashed var(--border-subtle)' }}>{t('project.act.hint')}</div>
          </div>
        )}

        {/* ── 文件浏览 ── split 是 height:100% 的组件，需给有界高度的父容器；预留头/Composer/Tab 占位 */}
        {tab === 'files' && (
          <div className="prj-panel prj-in" style={{ height: 'calc(100vh - 300px)', minHeight: 420, overflow: 'hidden', padding: 0 }}>
            <FileBrowser
              dir={proj.dir}
              layout="split"
              onInsertPath={(p) => composerApi.current?.insert(p)}
            />
          </div>
        )}

        <Suspense fallback={<Spin />}>
          {wtOpen && <WorktreePanel open={wtOpen} onClose={() => { setWtOpen(false); refresh() }} openTerm={openTerm} initialDir={dir} />}
          {/* 手机走全屏二级页；桌面仍是右缘面板 + 遮罩。原来这里是一套手搓的
              zIndex:1000 遮罩 + 面板，和会话页那套 FloatingFileDrawer 宽度/层级/阴影全不一样——
              同一个 GitPanel 不该有两套壳（13 §6）。 */}
          <AdaptivePanel open={!!(gitOpen || gitAt)} title={t('git.title')}
            onClose={() => { setGitOpen(false); setGitAt(null) }}>
            <GitPanel dir={gitAt?.dir || dir} initialTab={gitAt?.tab} openTerm={openTerm}
              onClose={() => { setGitOpen(false); setGitAt(null) }} />
          </AdaptivePanel>
          {raceOpen && <RaceCreateModal open={raceOpen} onClose={() => setRaceOpen(false)} onDone={() => { setRaceOpen(false); refresh() }} />}
          {swarmOpen && (
            <NewSwarmModal open={swarmOpen} initialDir={dir} lockDir
              onClose={() => setSwarmOpen(false)}
              onDone={(n) => { setSwarmOpen(false); refresh(); if (n) openTerm('cc-' + n) }} />
          )}
          {compareRace && <RaceComparePanel race={compareRace} onClose={() => setCompareRace(null)} openTerm={openTerm} onChanged={refresh} />}
        </Suspense>
        {/* 弹窗只剩「派生」在用（parent 固定）：新建的全部字段已经在 composer 里就地填完；
            收尾走 W7 三选一 */}
        <NewSessionModal open={!!forking} parent={forking}
          onClose={() => setForking(null)}
          onDone={(n) => { openTerm(n); refresh() }} />
        <CloseWorktreeModal info={closing} onClose={() => setClosing(null)} onDone={(name) => { closeTerm(name); setClosing(null); refresh() }} />
        <FinishModal w={finishing} base={defBranch} onClose={() => setFinishing(null)}
          onDone={() => { setFinishing(null); refresh() }} onRevive={(w) => newCli(w, 'shell')} />
        {/* 给指挥发话 = 广场署名 human 发言（08 §3），编排动作仍去蜂群台 */}
        <Modal open={!!saying} onCancel={() => setSaying('')} title={t('project.swarm.sayTitle', { name: saying })}
          okText={t('project.swarm.saySend')} destroyOnClose
          onOk={async () => {
            if (!sayText.trim()) return
            try {
              await api('POST', `/swarms/${encodeURIComponent(saying)}/say`, { text: '@leader ' + sayText.trim(), kind: 'ask' })
              message.success(t('project.swarm.saySent')); setSaying('')
            } catch (e: any) { message.error(e.message) }
          }}>
          <Input.TextArea autoFocus rows={3} value={sayText} onChange={(e) => setSayText(e.target.value)}
            placeholder={t('project.swarm.sayPlaceholder')} />
        </Modal>
      </div>
    </div>
  )
}
