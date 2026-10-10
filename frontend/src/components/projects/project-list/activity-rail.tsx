// 跨项目最近活动轨（18 设计 §4⑥）——原概览页的第五层。
// 活跃 git 项目取前 3 个，各拿头几条 commit 与合并留痕，合并倒序（60s 一轮）。
// Canvas ≥1180 时是右侧 sticky 侧轨；窄于此它只是网格的第二行，自然落回页尾。
import { useEffect, useState } from 'react'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { relTime } from '../../../time-format'
import { MergeIcon } from '../../../icons'
import type { Proj } from './project-model'

type Act = { oid?: string; subject?: string; branch?: string; base?: string; strategy?: string; at: number; kind: 'commit' | 'trace'; projName?: string }

export function useRecentActivity(projects: Proj[]): Act[] {
  const [acts, setActs] = useState<Act[]>([])
  // 「最近活动」得挑**最近在动的**三个 git 项目。原来取的是数组里的前 3 个——
  // 那个顺序来自列表的排序（置顶/名字/需要你…），于是活动轨会长期盯着几个冷仓库，
  // 真正刚提交过的那个反而不出现。
  const keys = projects
    .filter((p) => p.git)
    .slice()
    .sort((a, b) => (b.lastActivity || 0) - (a.lastActivity || 0))
    .slice(0, 3)
    .map((p) => p.key)
  const dep = keys.join(',')
  useEffect(() => {
    if (!keys.length) { setActs([]); return }
    let stop = false
    const load = async () => {
      const all: Act[] = []
      await Promise.all(keys.map(async (k) => {
        try {
          const r = await api('GET', `/projects/${encodeURIComponent(k)}/activity`)
          const name = projects.find((x) => x.key === k)?.name
          for (const c of (r?.data?.commits || []).slice(0, 3)) all.push({ ...c, kind: 'commit', projName: name })
          for (const tr of (r?.data?.traces || []).slice(0, 2)) all.push({ ...tr, kind: 'trace', projName: name })
        } catch {}
      }))
      if (!stop) setActs(all.sort((a, b) => (b.at || 0) - (a.at || 0)).slice(0, 8))
    }
    load()
    const i = setInterval(load, 60000)
    return () => { stop = true; clearInterval(i) }
  }, [dep])
  return acts
}

export function ActivityRail({ acts }: { acts: Act[] }) {
  const { t } = useI18n()
  if (!acts.length) return null
  return (
    <aside className="prj-rail prj-in" style={{ animationDelay: '160ms' }}>
      <h3>{t('project.codeActivity')}</h3>
      <div className="prj-tl">
        {acts.map((e) => (
          <div key={(e.oid || e.branch) + '' + e.at} className={`prj-ev ${e.kind === 'trace' ? 'p' : ''}`}>
            <b>{e.kind === 'trace'
              ? <><MergeIcon size={12} />{e.branch}</>
              : <><span className="prj-mono">{e.oid}</span> · {e.projName}</>}</b>
            <p>{e.kind === 'trace'
              ? t('project.act.traceMerged', { branch: e.branch, base: e.base || '?', strategy: e.strategy || 'squash' })
              : e.subject}</p>
            <time>{e.kind === 'trace' ? `${e.projName} · ` : ''}{relTime(e.at, t)}</time>
          </div>
        ))}
      </div>
    </aside>
  )
}

export const RAIL_CSS = `
.prj-rail{min-width:0;padding:var(--sp-3);border-radius:var(--r-card);background:var(--bg-container)}
.prj-rail h3{margin:0 0 var(--sp-3);font-size:var(--fs-sm);font-weight:600;color:var(--text-bright)}
.prj-tl{position:relative;display:flex;flex-direction:column;gap:var(--sp-4)}
.prj-tl::before{content:"";position:absolute;left:4px;top:6px;bottom:6px;border-left:1px solid var(--border-subtle)}
.prj-ev{position:relative;padding-left:18px}
.prj-ev::before{content:"";position:absolute;left:1px;top:4px;width:7px;height:7px;border-radius:50%;
  border:2px solid var(--bg-container);background:var(--accent)}
.prj-ev.p::before{background:var(--swarm)}
.prj-ev b{display:flex;align-items:center;gap:var(--sp-1);font-size:var(--fs-meta);color:var(--text-bright);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prj-ev b svg{flex:0 0 auto}
.prj-ev p{margin:var(--sp-1) 0 0;font-size:var(--fs-meta);line-height:1.55;color:var(--text-dim);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.prj-ev time{display:block;margin-top:var(--sp-1);font-size:var(--fs-micro);color:var(--text-dimmer)}

/* 右轨每条只留一行：commit 标题本来就是一行式摘要，展开三行只会和左栏挤在一起 */
@container canvas (min-width: 900px){ .prj-ev p{-webkit-line-clamp:1} }
`
