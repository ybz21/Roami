// 项目卡（18 设计 §5）——原概览「作战卡」与项目页「项目卡」的并集。
//
// 头部取项目卡（置顶 / 删除），图标与双行名字取概览卡；计数行保留，但**「待收尾」不再当 Tag**
// ——它是个动作，Tag 点不动，所以下移到脚注带自己的出口。会话行 3 条，带 agent 品牌标与分支标。
//
// 点击语义：整张卡就是「进入项目」的按钮——原来右上角那条「进入项目 ›」是全卡唯一入口，
// 把一个 300px 宽的目标缩成了 60px 的小链接。卡内的会话行/看板/去收尾各自 stopPropagation。
import { App as AntApp, Popconfirm, Tag, Tooltip } from 'antd'
import { MemBar } from '../../sessions/session-memory'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { relTime } from '../../../time-format'
import { sessionLabel } from '../../sessions/session-label'
import { AgentLogo, ChevronRight, CloseIcon, FlagIcon, StarIcon, SwarmIcon } from '../../../icons'
import { agentName } from '../../../agent-kind'
import { BranchIcon } from '../../git/parts'
import { icoOf } from './project-model'
import type { Proj, ProjSwarm } from './project-model'

const Go = () => <span className="prj-goi"><ChevronRight size={12} /></span>

/** 状态点：黄（等待输入）优先于绿（agent 在跑），灰 = 闲着。 */
// 休眠会话画成空心点：它「在」但不「活」，与实心的活会话一眼分得开。
const StatusDot = ({ waiting, running, dormant }: { waiting?: boolean; running?: boolean; dormant?: boolean }) => (
  <i className={`prj-cdot${dormant ? ' d' : waiting ? ' a' : running ? ' g' : ''}`} />
)

export function ProjectCard({ p, swarms, index, openTerm, refresh }: {
  p: Proj; swarms: ProjSwarm[]; index: number
  openTerm: (n: string) => void; refresh: () => void
}) {
  const { t } = useI18n()
  const { coarse } = useLayout()
  const { message } = AntApp.useApp()
  const [fg, bg] = icoOf(p.key)
  const rows = p.top || []
  const projSwarms = swarms.filter((sw) => sw.projKey === p.key)
  const open = () => { location.hash = '#/projects/' + encodeURIComponent(p.key) }
  const goSwarm = (n: string) => { location.hash = '#/swarm/' + encodeURIComponent(n) }

  const pin = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try { await api('PATCH', `/projects/${encodeURIComponent(p.key)}/prefs`, { pinned: !p.pinned }); refresh() }
    catch (err: any) { message.error(err.message) }
  }
  const remove = async () => {
    try { await api('DELETE', `/projects/${encodeURIComponent(p.key)}`); message.success(t('project.removed')); refresh() }
    catch (err: any) { message.error(err.message) }
  }

  // 粗指针下不挂 Tooltip：触屏点开的浮层没有 mouseleave 收它，之后会吃掉下一次点击
  const pinLabel = p.pinned ? t('project.unpin') : t('project.pin')
  const pinBtn = (
    <button type="button" className={`prj-cact${p.pinned ? ' on' : ''}`} onClick={pin}
      aria-label={pinLabel} title={coarse ? pinLabel : undefined}><StarIcon filled={p.pinned} /></button>
  )

  return (
    <div className="prj-card prj-in" data-prj-card role="button" tabIndex={0}
      aria-label={p.name} title={t('overview.enterProject')}
      onClick={open}
      // role="button" 就得按按钮的键盘语义来：Enter **和** Space 都要能打开。
      // 只认 Enter 是半套——原生 <button> 两个都响应，用户的手指记的是这个。
      onKeyDown={(e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return
        if (e.target !== e.currentTarget) return // 卡片里的按钮自己处理，别被外层抢走
        e.preventDefault()
        open()
      }}
      style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}>
      <div className="hd">
        <span className="prj-cico" style={{ color: fg, background: bg }} aria-hidden>{(p.name[0] || '?').toUpperCase()}</span>
        <span className="nm">
          <b title={p.name}>{p.name}</b>
          <span className="prj-mono" title={p.dir}>{p.dir}</span>
        </span>
        <span className="prj-cacts">
          {coarse ? pinBtn : <Tooltip title={pinLabel}>{pinBtn}</Tooltip>}
          <Popconfirm title={t('project.removeConfirm')} onConfirm={remove}
            onPopupClick={(e) => e.stopPropagation()}>
            <button type="button" className="prj-cact" onClick={(e) => e.stopPropagation()}
              aria-label={t('project.remove')} title={coarse ? t('project.remove') : undefined}><CloseIcon size={13} /></button>
          </Popconfirm>
          <span className="go" aria-hidden><ChevronRight size={13} /></span>
        </span>
      </div>

      <div className="prj-cstat">
        <span><b>{p.sessions}</b> {t('project.tasks')}</span>
        {p.git && <>·<span><b>{p.worktrees}</b> worktree</span></>}
        {p.races > 0 && <Tag color="gold" style={{ margin: 0 }}>{t('project.race', { count: p.races })}</Tag>}
        {/* 「可清理」是零损失的一键动作，不进「需要你」，留在这里当状态标就够 */}
        {p.cleanable > 0 && <Tag color="success" style={{ margin: 0 }}>{t('project.cleanableCount', { count: p.cleanable })}</Tag>}
      </div>

      {rows.length > 0 && (
        <div className="prj-crows">
          {rows.map((s) => (
            <div key={s.name} className="prj-crow" role="button" tabIndex={0}
              onClick={(e) => { e.stopPropagation(); openTerm(s.name) }}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); openTerm(s.name) } }}>
              <StatusDot waiting={s.waiting} running={s.running} dormant={s.state === 'dormant'} />
              <span className={`t${s.state === 'dormant' ? ' dorm' : ''}`}
                title={s.state === 'dormant'
                  ? `${s.label || sessionLabel(s.name)}（${s.name}）· ${t('session.dormant.hint')}`
                  : `${s.label || sessionLabel(s.name)}（${s.name}）`}>{s.label || sessionLabel(s.name)}</span>
              {s.linked && <span className="tt-branch" title={s.branch}><BranchIcon size={11} /></span>}
              {s.agent && (
                <span className="tt-agentmark" title={agentName(s.agent)}>
                  <AgentLogo kind={s.agent} size={12} />
                </span>
              )}
              <MemBar mem={s.mem} compact />
              <span className="tm">{relTime(s.lastActivity, t)}</span>
            </div>
          ))}
          {p.sessions > rows.length && <div className="prj-cmore">{t('overview.moreTasks', { count: p.sessions - rows.length })}</div>}
        </div>
      )}

      {projSwarms.map((sw) => (
        <div key={sw.name} className="prj-cfoot">
          <SwarmIcon size={12} /><b>{sw.name}</b>
          <span className="dim">{t('project.swarm.members', { mine: sw.inProj, total: sw.total })}</span>
          <button type="button" onClick={(e) => { e.stopPropagation(); goSwarm(sw.name) }}>{t('project.swarm.board')}<Go /></button>
        </div>
      ))}
      {p.unfinished > 0 && (
        <div className="prj-cfoot w">
          <FlagIcon size={12} /><b>{t('overview.unfinishedN', { count: p.unfinished })}</b>
          <button type="button" onClick={(e) => { e.stopPropagation(); open() }}>{t('overview.goFinish')}<Go /></button>
        </div>
      )}
    </div>
  )
}

export const CARD_CSS = `
/* 卡片列固定在 ≥320：更窄的话右侧一开终端就塌成一条极窄列表（14 §6.1）。
   align-items:start —— 默认 stretch 会把整行卡片拉到最高那张的高度。 */
.prj-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:var(--sp-4);align-items:start}

.prj-card{min-width:0;background:var(--bg-container);border:1px solid var(--border-subtle);border-radius:var(--r-card);
  padding:var(--sp-3) var(--sp-3) var(--sp-2);cursor:pointer;display:flex;flex-direction:column;gap:var(--sp-1);
  transition:border-color .18s,transform .18s,box-shadow .18s,background .18s}
:where(html[data-pointer="fine"]) .prj-card:hover{border-color:var(--accent-border);transform:translateY(-1px);box-shadow:var(--card-hover-shadow)}
.prj-card:focus-visible{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
/* 指针落在会话行/脚注按钮上时，把卡片自己的 hover 收回去：
   高亮要指明「点下去会中哪个」，两层同时亮等于没说 */
:where(html[data-pointer="fine"]) .prj-card:has(.prj-crow:hover),
:where(html[data-pointer="fine"]) .prj-card:has(.prj-cfoot button:hover),
:where(html[data-pointer="fine"]) .prj-card:has(.prj-cact:hover){transform:none;box-shadow:none;border-color:var(--border-subtle)}
:where(html[data-pointer="fine"]) .prj-card:has(.prj-crow:hover) .hd .go,
:where(html[data-pointer="fine"]) .prj-card:has(.prj-cfoot button:hover) .hd .go{color:var(--text-dimmer);transform:none}

.prj-card .hd{display:flex;align-items:center;gap:var(--sp-2)}
.prj-cico{width:28px;height:28px;flex:0 0 auto;display:grid;place-items:center;border-radius:var(--r-sm);
  font-size:12px;font-weight:800}
.prj-card .nm{min-width:0;flex:1 1 auto}
.prj-card .nm b{display:block;font-size:var(--fs-body);color:var(--text-bright);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prj-card .nm span{display:block;margin-top:2px;font-size:var(--fs-micro);line-height:1.3;color:var(--text-dimmer);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* 次要操作 hover 才出现，但键盘走到时同样要看得见——否则纯键盘用户够不着（14 §6.1） */
.prj-cacts{flex:0 0 auto;display:inline-flex;align-items:center;gap:var(--sp-1)}
.prj-cact{opacity:.25;display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;
  border:0;border-radius:var(--r-xs);background:none;color:var(--text-dimmer);cursor:pointer;transition:opacity .15s,color .15s}
.prj-cact.on{opacity:1;color:var(--warn)}
.prj-card:focus-within .prj-cact,.prj-card:focus-visible .prj-cact{opacity:1}
:where(html[data-pointer="fine"]) .prj-card:hover .prj-cact{opacity:1}
:where(html[data-pointer="fine"]) .prj-cact:hover{color:var(--text-bright)}
html[data-pointer="coarse"] .prj-cact{opacity:1}
/* 手指档把命中区撑到 44，视觉尺寸不变；相邻两枚各自超出 4px 才不会互相咬到（13 §7.1） */
html[data-pointer="coarse"] .prj-cact{position:relative}
html[data-pointer="coarse"] .prj-cact::after{content:"";position:absolute;left:50%;top:50%;
  width:44px;height:44px;transform:translate(-50%,-50%)}
html[data-pointer="coarse"] .prj-cacts{gap:var(--sp-3)}
/* 右上角只留一枚箭头当方向暗示：整张卡都能点，再写一遍「进入项目」是废话 */
.prj-card .hd .go{flex:0 0 auto;display:inline-flex;color:var(--text-dimmer);transition:color .15s,transform .15s}
:where(html[data-pointer="fine"]) .prj-card:hover .hd .go{color:var(--accent);transform:translateX(2px)}

.prj-cstat{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;
  font-size:var(--fs-meta);color:var(--text-dim)}
.prj-cstat b{color:var(--text-bright)}

.prj-crows{display:flex;flex-direction:column;gap:1px;margin-top:var(--sp-1);padding:5px 4px;
  border-radius:var(--r-sm);background:var(--bg-term);border:1px solid var(--border-subtle)}
.prj-crow{display:flex;align-items:center;gap:var(--sp-2);min-height:30px;padding:var(--sp-1) var(--sp-2);
  border-radius:var(--r-xs);font-size:var(--fs-sm);color:var(--text-bright);cursor:pointer;transition:background .14s}
:where(html[data-pointer="fine"]) .prj-crow:hover{background:var(--list-hover)}
.prj-crow:focus-visible{outline:1px solid var(--accent-border);outline-offset:-1px}
html[data-pointer="coarse"] .prj-crow{min-height:44px}
.prj-crow .t{min-width:0;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prj-crow .tm{margin-left:auto;flex:0 0 auto;font-size:var(--fs-meta);color:var(--text-dimmer);white-space:nowrap}
.prj-cdot{width:8px;height:8px;flex:0 0 8px;border-radius:50%;display:inline-block;background:var(--text-dimmer)}
.prj-cdot.g{background:var(--ok);box-shadow:0 0 0 3px var(--ok-soft)}
.prj-cdot.a{background:var(--warn);box-shadow:0 0 0 3px var(--warn-soft)}
/* 休眠：空心。不用灰色实心——那会和「活着但空闲」撞脸，而两者的区别是能不能直接用 */
.prj-cdot.d{background:transparent;box-shadow:inset 0 0 0 1.5px var(--text-dimmer)}
.prj-crow .t.dorm{color:var(--text-dim)}
.prj-cmore{padding:2px var(--sp-2);font-size:var(--fs-meta);color:var(--text-dimmer)}

.prj-cfoot{display:flex;align-items:center;gap:var(--sp-2);min-height:28px;margin-top:var(--sp-1);
  padding:var(--sp-1) var(--sp-2);border-radius:var(--r-xs);font-size:var(--fs-meta);
  border:1px solid var(--swarm-border);background:var(--swarm-soft);color:var(--swarm)}
.prj-cfoot.w{border-color:var(--warn-border);background:var(--warn-soft);color:var(--warn)}
.prj-cfoot b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prj-cfoot .dim{color:var(--text-dimmer);flex:0 0 auto}
.prj-cfoot button{margin-left:auto;flex:0 0 auto;border:0;background:none;color:inherit;
  font:inherit;cursor:pointer;padding:var(--sp-1);margin-right:calc(var(--sp-1) * -1)}
html[data-pointer="coarse"] .prj-cfoot{min-height:44px}
`
