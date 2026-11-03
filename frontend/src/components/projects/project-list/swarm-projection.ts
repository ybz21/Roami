// 蜂群在项目列表上的投影（10s）。
//
// 归属两条判据取并集，与项目详情页（08 §2.2）**必须**是同一套，否则列表说这个群属于 A、
// 点进去 A 里又没有它：
//   1) 蜂群自报的工作目录 dir == 项目目录（swarm new/adopt --dir 落库，新群走这条）
//   2) 指挥/成员会话的归属仓库 == 项目目录（老群没有 dir，只能这么认）
// 判据 2 只要一张 session → repo 的表（/sessions/annotations），不必像旧概览那样再拉
// 整棵会话树来拼归属——项目归属后端已经在 /projects 里算过了。
import { useEffect, useState } from 'react'
import { api } from '../../../api'
import { pollWhileVisible } from '../../../visible-poll'
import type { Proj, ProjSwarm } from './project-model'

/** 目录规整：去尾斜杠 + 折叠重复斜杠，用于蜂群 dir 与项目 dir 的等值比较。 */
export function normDir(p: string): string {
  const s = String(p || '').trim().replace(/\/+/g, '/').replace(/\/+$/, '')
  return s || ''
}

export function useSwarmProjection(projects: Proj[]): ProjSwarm[] {
  const [swarms, setSwarms] = useState<ProjSwarm[]>([])
  // 只在项目目录集合变化时重订阅——projects 每 5s 换一个新数组，直接进依赖会把定时器打散
  const dirsKey = projects.map((p) => `${p.key}\t${p.dir}\t${p.name}`).join('\n')
  useEffect(() => {
    let stop = false
    const load = async (signal: AbortSignal) => {
        const byDir = new Map(projects.map((p) => [normDir(p.dir), p]))
        const [list, annRes] = await Promise.all([
          api('GET', '/swarms', undefined, { signal }),
          api('GET', '/sessions/annotations', undefined, { signal }).catch(() => null),
        ])
        const ann: Record<string, any> = annRes?.data || {}
        const active = (Array.isArray(list) ? list : []).filter((s: any) => s.status !== 'archived')
        const out: ProjSwarm[] = []
        await Promise.all(active.map(async (sw: any) => {
          try {
            const managed = sw.engine === 'roami_v2'
            const st = managed ? { ...sw, pending: [] } : await api('GET', `/swarms/${encodeURIComponent(sw.name)}`, undefined, { signal })
            const members = (st?.members || []) as any[]
            const names = [st?.supervisor, ...members.map((m) => m.session)].filter(Boolean) as string[]
            const roster = managed ? members.length : names.length
            const swDir = normDir(sw.dir || st?.dir || '')
            // 空 dir 不能拿去查表：normDir('') 会撞上任何同样为空的键
            const proj = (swDir ? byDir.get(swDir) : undefined)
              || projects.find((p) => names.some((n) => ann[n]?.primary?.repo === p.dir))
            if (!proj) return
            const inProj = names.filter((n) => ann[n]?.primary?.repo === proj.dir).length
            // 认了 dir 的群整支班子都算本项目的：它的会话本来就被 ttmux ls 过滤掉了，
            // 按会话数算会显示成 0/N 且每行都标「跨项目」（issue #125）
            const byDirHit = !!swDir && swDir === normDir(proj.dir)
            out.push({
              name: sw.name, label: sw.label, projKey: proj.key, projName: proj.name,
              total: roster, inProj: byDirHit ? roster : inProj, pending: (st?.pending || []).length,
            })
          } catch {}
        }))
        if (!stop && !signal.aborted) setSwarms(out.sort((a, b) => a.name.localeCompare(b.name)))
    }
    const polling = pollWhileVisible(load, 10000)
    return () => { stop = true; polling.stop() }
  }, [dirsKey])
  return swarms
}
