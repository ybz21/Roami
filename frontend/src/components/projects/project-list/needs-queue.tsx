// 工作台页头 + 「需要你」行动队列（18 设计 §4/§6）——原概览页的前两层。
//
// 它回答的是「下一步做什么」，不是「一共有多少」：等待输入排最前，因为那是唯一
// 「人不动就卡住」的一类。三张封顶，超出走「查看全部」；零事项时整层不渲染，
// 不留空槽（旧概览的常驻琥珀横幅没事也占一屏）。
//
// 搜索/筛选进行时收成一行：行动队列是**跨项目**的待办，不该被「搜索 ttmux」过滤掉，
// 但用户明显在找某个项目时也不该占三行。
import { useState } from 'react'
import { useI18n } from '../../../i18n'
import { relTime } from '../../../time-format'
import { ChevronDown, ChevronRight, ChevronUp, FlagIcon, PlusIcon, SwarmIcon } from '../../../icons'
import { waitingSessions, type Proj, type ProjSwarm } from './project-model'

export type NeedCard = {
  key: string; kind: 'waiting' | 'unfinished' | 'swarm'
  proj: string; title: string; desc: string; action: string; go: () => void
}

/** 行动队列的三类事项。顺序即优先级：等待输入 > 蜂群待解锁 > 待收尾。 */
export function buildNeedCards(
  projects: Proj[], swarms: ProjSwarm[], t: (k: string, v?: any) => string,
  nav: { openTerm: (n: string) => void; goProject: (k: string) => void; goSwarm: (n: string) => void },
): NeedCard[] {
  const items: NeedCard[] = []
  for (const p of projects) {
    for (const s of waitingSessions(p)) {
      items.push({
        key: 'w' + s.name, kind: 'waiting', proj: p.name,
        title: s.label || s.name,
        desc: s.tail || t('overview.cardWaitingDesc'),
        action: t('overview.cardGoSession'), go: () => nav.openTerm(s.name),
      })
    }
  }
  for (const sw of swarms) {
    if (sw.pending <= 0) continue
    items.push({
      key: 's' + sw.name, kind: 'swarm', proj: sw.projName, title: sw.name,
      desc: t('overview.cardSwarmDesc', { count: sw.pending }),
      action: t('project.swarm.board'), go: () => nav.goSwarm(sw.name),
    })
  }
  for (const p of projects) {
    if (p.unfinished <= 0) continue
    items.push({
      key: 'u' + p.key, kind: 'unfinished', proj: p.name,
      title: t('overview.unfinishedN', { count: p.unfinished }),
      desc: t('overview.cardUnfinishedDesc'),
      action: t('overview.goFinish'), go: () => nav.goProject(p.key),
    })
  }
  return items
}

const Go = () => <span className="prj-goi"><ChevronRight size={12} /></span>

/** 页头：问候 + 一句话状态 + 状态概况 + 快捷创建。数字都是导航入口，零值不渲染。 */
export function WorkbenchHead({ stats, lastAt, onNew, onSummaryClick, phone }: {
  stats: { running: number; waiting: number; unfinished: number; swarms: number }
  lastAt: number
  onNew: () => void
  onSummaryClick: (filter: 'needs' | 'running') => void
  phone: boolean
}) {
  const { t, locale } = useI18n()
  const hour = new Date().getHours()
  const greet = t(hour < 6 ? 'overview.greetNight' : hour < 12 ? 'overview.greetMorning'
    : hour < 18 ? 'overview.greetAfternoon' : 'overview.greetEvening')
  let kicker = ''
  try { kicker = new Date().toLocaleDateString(locale, { weekday: 'long', month: 'long', day: 'numeric' }) } catch {}
  const total = stats.running + stats.waiting + stats.unfinished + stats.swarms

  // 「0 等待输入」不是信息，是噪声——四格里常有三格是 0，一排 0 比不显示更空洞
  const item = (n: number, cls: string, label: string, to: 'needs' | 'running') => (n > 0 ? (
    <button key={label} type="button" onClick={() => onSummaryClick(to)}>
      <i className={`prj-sd ${cls}`} /><b>{n}</b>{label}
    </button>
  ) : null)

  return (
    <header className="tt-pagehead prj-head">
      <div className="ttl">
        <h2>{greet}{stats.waiting > 0 ? t('mobile.home.headNeeds', { n: stats.waiting })
          : stats.running > 0 ? t('mobile.home.headRunning', { n: stats.running }) : t('mobile.home.headQuiet')}</h2>
        {/* 数字归状态条，一个数只说一次：副句里不再重复「N 个任务正在运行」 */}
        <p>{kicker}{' · '}{stats.running > 0
          ? t('overview.metaActivity', { time: relTime(lastAt, t) })
          : t('overview.sublineIdle')}</p>
      </div>
      {/* 状态条与快捷创建同在一个 .acts 里：分成两个的话桌面上会各占一行，
          标题右边空出 800px，而这两样加起来还不到 500 */}
      <div className="acts">
        {total > 0 && (
          <div className="prj-sum">
            {item(stats.running, '', t('overview.sumRunning'), 'running')}
            {item(stats.waiting, 'a', t('overview.sumWaiting'), 'needs')}
            {item(stats.unfinished, 'a', t('overview.sumUnfinished'), 'needs')}
            {item(stats.swarms, 'p', t('overview.sumSwarms'), 'needs')}
          </div>
        )}
        {!phone && (
          <button type="button" className="prj-new" onClick={onNew}>
            <PlusIcon size={13} />{t('overview.newTask')}
          </button>
        )}
      </div>
    </header>
  )
}

/** 行动队列本体。collapsed = 搜索/筛选进行时的一行摘要（可点开）。 */
export function NeedsQueue({ cards, collapsed, onViewAll }: {
  cards: NeedCard[]
  collapsed: boolean
  onViewAll: () => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!cards.length) return null

  const counts = {
    waiting: cards.filter((c) => c.kind === 'waiting').length,
    swarm: cards.filter((c) => c.kind === 'swarm').length,
    unfinished: cards.filter((c) => c.kind === 'unfinished').length,
  }
  const parts = [
    counts.waiting > 0 && `${t('overview.cardWaiting')} ${counts.waiting}`,
    counts.swarm > 0 && `${t('nav.swarm')} ${counts.swarm}`,
    counts.unfinished > 0 && `${t('overview.cardUnfinished')} ${counts.unfinished}`,
  ].filter(Boolean).join(' · ')

  if (collapsed && !open) {
    return (
      <button type="button" className="prj-needbar" onClick={() => setOpen(true)}>
        <i className="prj-sd a" />
        <b>{t('overview.followUp')} {cards.length}</b>
        <span className="sub">{parts}</span>
        <span className="sp" />
        <span className="ex">{t('common.expand')}<ChevronDown size={12} /></span>
      </button>
    )
  }

  return (
    <>
      <div className="prj-sect">
        <b>{t('overview.followUp')}</b><span className="n">{cards.length}</span><span className="ln" />
        {collapsed && open && (
          <button type="button" className="prj-sectbtn" onClick={() => setOpen(false)}>
            {t('common.collapse')}<ChevronUp size={12} />
          </button>
        )}
        {cards.length > 3 && (
          <button type="button" className="prj-sectbtn" onClick={onViewAll}>
            {t('overview.viewAllN', { count: cards.length })}<Go />
          </button>
        )}
      </div>
      <div className="prj-needs">
        {cards.slice(0, 3).map((c, i) => (
          <article key={c.key} className={`prj-need prj-in${c.kind === 'swarm' ? ' p' : ''}`}
            role="button" tabIndex={0} style={{ animationDelay: `${80 + i * 40}ms` }}
            onClick={c.go}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); c.go() } }}>
            <div className="ty">
              {c.kind === 'swarm' ? <SwarmIcon size={12} /> : c.kind === 'unfinished' ? <FlagIcon size={12} /> : <i className="prj-sd a" />}
              {t(c.kind === 'waiting' ? 'overview.cardWaiting' : c.kind === 'swarm' ? 'overview.cardSwarm' : 'overview.cardUnfinished')}
              <span className="pj">· {c.proj}</span>
            </div>
            <h4 title={c.title}>{c.title}</h4>
            <p>{c.desc}</p>
            <span className="go">{c.action}<Go /></span>
          </article>
        ))}
      </div>
    </>
  )
}

export const NEEDS_CSS = `
/* 页头：窄档 .acts 换行成整条横在标题下面，桌面（≥900）并回标题右端 */
.prj-head .acts{width:100%;margin-left:0;justify-content:flex-start}
.prj-new{flex:0 0 auto;display:inline-flex;align-items:center;gap:var(--sp-2);height:var(--ctl-h);padding:0 var(--sp-4);
  border:0;border-radius:var(--r-sm);background:var(--accent-solid);color:#fff;
  font-size:var(--fs-sm);font-weight:600;cursor:pointer;transition:filter .15s}
:where(html[data-pointer="fine"]) .prj-new:hover{filter:brightness(1.08)}
.prj-sum{display:flex;align-items:center;gap:var(--sp-2) var(--sp-5);flex-wrap:wrap;
  min-height:var(--ctl-h);font-size:var(--fs-meta)}
.prj-sum button{display:inline-flex;align-items:center;gap:var(--sp-2);padding:var(--sp-2) var(--sp-3);
  border:0;border-radius:var(--r-xs);
  background:transparent;color:var(--text-dim);font:inherit;cursor:pointer}
:where(html[data-pointer="fine"]) .prj-sum button:hover{color:var(--text-bright);background:var(--list-hover)}
.prj-sum b{font-family:ui-monospace,monospace;font-weight:700;font-size:var(--fs-body);color:var(--text-bright)}
/* 状态点：画出来的，不是打出来的（● 会跟着字体走） */
.prj-sd{width:6px;height:6px;border-radius:50%;background:var(--ok);flex:0 0 auto;display:block}
.prj-sd.a{background:var(--warn)}.prj-sd.p{background:var(--swarm)}

/* 行动卡：一屏最多三张，不让黄框把项目卡挤到首屏以下 */
.prj-needs{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--sp-3)}
.prj-need{position:relative;min-width:0;min-height:118px;padding:12px 13px 34px;cursor:pointer;
  border:1px solid var(--border-subtle);border-radius:var(--r-card);background:var(--bg-container);
  transition:border-color .15s,transform .15s}
:where(html[data-pointer="fine"]) .prj-need:hover{border-color:var(--warn);transform:translateY(-1px)}
.prj-need:focus-visible{outline:1px solid var(--accent-border);outline-offset:2px}
:where(html[data-pointer="fine"]) .prj-need.p:hover{border-color:var(--swarm)}
.prj-need .ty{display:flex;align-items:center;gap:var(--sp-2);font-size:var(--fs-meta);font-weight:600;color:var(--warn)}
.prj-need.p .ty{color:var(--swarm)}
.prj-need .ty .pj{color:var(--text-dimmer);font-weight:400;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prj-need h4{margin:var(--sp-2) 0 var(--sp-1);font-size:var(--fs-body);color:var(--text-bright);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prj-need p{margin:0;height:36px;overflow:hidden;font-size:var(--fs-meta);line-height:1.5;color:var(--text-dim);
  font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace}
.prj-need .go{position:absolute;left:var(--sp-3);bottom:var(--sp-3);font-size:var(--fs-meta);color:var(--accent)}

/* 折叠态：搜索/筛选时行动队列收成一行，仍可点开 */
.prj-needbar{display:flex;align-items:center;gap:var(--sp-2);width:100%;min-height:36px;
  padding:var(--sp-2) var(--sp-3);border-radius:var(--r-sm);cursor:pointer;text-align:left;
  border:1px solid var(--border-subtle);background:transparent;color:var(--text-bright);font-size:var(--fs-meta)}
:where(html[data-pointer="fine"]) .prj-needbar:hover{background:var(--list-hover);border-color:var(--border)}
.prj-needbar b{font-weight:600}
.prj-needbar .sub{color:var(--text-dimmer)}
.prj-needbar .sp{flex:1}
.prj-needbar .ex{display:inline-flex;align-items:center;gap:var(--sp-1);flex:0 0 auto;color:var(--text-dim)}

.prj-goi{display:inline-flex;vertical-align:-2px;margin-left:3px;opacity:.75}
:where(html[data-pointer="fine"]) button:hover>.prj-goi,
:where(html[data-pointer="fine"]) .prj-need:hover .prj-goi{opacity:1}

/* 手机：行动卡横滑一行，卡宽 76% 露出下一张的边。竖排三张要吃掉 330px，
   第一张项目卡会被推到屏幕 60% 以下。 */
html[data-size="compact"] .prj-needs{display:flex;gap:var(--sp-2);overflow-x:auto;
  scroll-snap-type:x mandatory;scrollbar-width:none;margin:0 calc(var(--sp-4) * -1);padding:0 var(--sp-4)}
html[data-size="compact"] .prj-needs::-webkit-scrollbar{height:0}
html[data-size="compact"] .prj-need{flex:0 0 76%;scroll-snap-align:start;min-height:110px}
/* 只有一张时占满：留 24% 的空槽是在暗示右边还有，而右边什么都没有 */
html[data-size="compact"] .prj-need:only-child{flex:0 0 100%}

@container canvas (min-width: 900px){
  .prj-needs{grid-template-columns:repeat(2,minmax(0,1fr))}
  /* 状态条并进页头右端，与标题同底线：省掉一整行，也不会出现「一枚数字 + 大片空白」 */
  .prj-head{align-items:flex-end}
  .prj-head .acts{width:auto;margin-left:auto;justify-content:flex-end;gap:var(--sp-4);padding-bottom:3px}
}
@container canvas (min-width: 1180px){
  .prj-needs{grid-template-columns:repeat(3,minmax(0,1fr))}
}
`
