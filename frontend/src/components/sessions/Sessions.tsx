import { agentName, useAgentKinds } from '../../agent-kind'
// ── 会话（可新建/指定目录 / 进终端 / 关闭） ──
import { Suspense, useEffect, useState } from 'react'
import { RaceComparePanel, RaceCreateModal } from '../swarm/Race'
import WorktreePanel from '../git/WorktreePanel'
import { api } from '../../api'
import { useSessionCloser } from './session-closer'
import { NewSessionModal } from './NewSessionModal'
import { useI18n } from '../../i18n'
import { SessionHistory } from './SessionHistory'
import { useLayout } from '../../layout'
import { MemBar } from './session-memory'
import { detectPrompt } from '../prompt'
import { sessionLabel, setSessionLabels } from './session-label'
import { SESSION_MIME } from '../shell/session-drop'
import { currentNodeId } from '../cluster/node-url'
import { sessionLocation, useSessionProjects } from './session-project'
import { absTime, relTime } from '../../time-format'
import { Button, Empty, Input, List, Popconfirm, Segmented, Select, Space, Tag, Tooltip, App as AntApp } from 'antd'
import { AgentLogo, ArrowDown, ArrowUp, Disclosure, SearchIcon, WindowsIcon } from '../../icons'
import { BranchIcon } from '../git/parts'
import { Dropdown } from 'antd'

export default function Sessions({ openTerm, closeTerm, activeTerm, embedded }: {
  openTerm: (n: string) => void; closeTerm: (n: string) => void; activeTerm: string | null
  /** 嵌在概览「会话」tab 里：不渲染页头（外面的 tab 已经说了这是会话） */
  embedded?: boolean
}) {
  const { phone: isPhone } = useLayout()
  const [list, setList] = useState<any[]>([])
  const agentKinds = useAgentKinds()
  const [cc, setCc] = useState<Record<string, boolean>>({})
  const [cx, setCx] = useState<Record<string, boolean>>({})
  const [needsInput, setNeedsInput] = useState<Record<string, boolean>>({})
  const [swarmMap, setSwarmMap] = useState<Record<string, { swarm: string; role: string }>>({})
  const [newOpen, setNewOpen] = useState(false)
  const [wtOpen, setWtOpen] = useState(false)
  const [wtDir, setWtDir] = useState<string | undefined>(undefined)
  // session→worktree 归属注解（cwd 现算的弱关联）：会话行 ⎇ Tag 的数据源
  const [wtAnn, setWtAnn] = useState<Record<string, any>>({})
  // 会话→项目：桌面「项目」列的数据源。表是 App 那份轮询建的，这里只读（14 §6.3）
  const sessProj = useSessionProjects()
  // 竞赛（W5/W6）：Race Service 业务数据，会话按竞赛聚组、组头进对比台
  const [races, setRaces] = useState<any[]>([])
  const [raceOpen, setRaceOpen] = useState(false)
  const [compareId, setCompareId] = useState('')
  // 派生子会话（fork）弹窗：值为父会话名
  const [forking, setForking] = useState<string | null>(null)
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  // tree=1：拿 parent 投影树后拍平（节点字段与平铺一致 + parent），W2 父子分组用
  const load = () => api('GET', '/sessions?tree=1').then((roots) => {
    const flat: any[] = []
    const walk = (nodes: any[]) => { for (const n of nodes || []) { flat.push(n); walk(n.children) } }
    walk(Array.isArray(roots) ? roots : [])
    setList(flat)
    setSessionLabels(Object.fromEntries(flat.filter((s) => s?.name && s?.label).map((s) => [s.name, s.label])))
  }).catch(() => {})
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t) }, [])
  useEffect(() => {
    let stop = false
    const loadAnn = () => api('GET', '/sessions/annotations')
      .then((r) => { if (!stop) setWtAnn(r?.data || {}) }).catch(() => {})
    loadAnn()
    const t = setInterval(loadAnn, 8000)
    return () => { stop = true; clearInterval(t) }
  }, [])
  useEffect(() => {
    let stop = false
    const loadRaces = () => api('GET', '/races')
      .then((r) => { if (!stop) setRaces(Array.isArray(r?.data) ? r.data : []) }).catch(() => {})
    loadRaces()
    const t = setInterval(loadRaces, 8000)
    return () => { stop = true; clearInterval(t) }
  }, [])
  const reloadRaces = () => api('GET', '/races').then((r) => setRaces(Array.isArray(r?.data) ? r.data : [])).catch(() => {})
  // 拉取蜂群拓扑：哪些会话其实是蜂群的指挥/成员。会话页和蜂群页看到的是同一批 tmux 会话，
  // 这里据成员的真实 session 名(非前缀猜测)打标，并据此拦住「关闭」误把成员当完成解锁下游。
  useEffect(() => {
    let stop = false
    const loadSwarms = async () => {
      try {
        const swarms = await api('GET', '/swarms')
        if (!Array.isArray(swarms)) return
        const map: Record<string, { swarm: string; role: string }> = {}
        await Promise.all(swarms.map(async (sw: any) => {
          try {
            const st = await api('GET', `/swarms/${encodeURIComponent(sw.name)}`)
            if (st?.supervisor) map[st.supervisor] = { swarm: sw.name, role: 'leader' }
            for (const m of (st?.members || [])) {
              if (m?.session) map[m.session] = { swarm: sw.name, role: m.role === 'leader' || m.role === 'master' ? 'leader' : 'member' }
            }
          } catch {}
        }))
        if (!stop) setSwarmMap(map)
      } catch {}
    }
    loadSwarms()
    const t = setInterval(loadSwarms, 8000)
    return () => { stop = true; clearInterval(t) }
  }, [])
  // 标注哪些会话在跑 Claude Code
  useEffect(() => {
    let stop = false
    const check = () => list.forEach(async (s: any) => {
      try { const r = await api('GET', `/sessions/${encodeURIComponent(s.name)}/claude`); if (!stop) setCc((m) => ({ ...m, [s.name]: !!r.data?.running })) } catch {}
      try { const r = await api('GET', `/sessions/${encodeURIComponent(s.name)}/codex`); if (!stop) setCx((m) => ({ ...m, [s.name]: !!r.data?.running })) } catch {}
    })
    if (list.length) check()
    const t = setInterval(() => { if (list.length) check() }, 5000)
    return () => { stop = true; clearInterval(t) }
  }, [list])
  // 识别卡在人类决策/审批点的会话，列表上给出醒目标识，方便及时介入。
  useEffect(() => {
    if (!list.length) { setNeedsInput({}); return }
    let stop = false
    const checkPrompts = async () => {
      const entries = await Promise.all(list.map(async (s: any) => {
        try {
          const r = await api('GET', `/sessions/${encodeURIComponent(s.name)}/capture?lines=50`)
          return [s.name, !!detectPrompt(r.data || '')] as const
        } catch {
          return [s.name, false] as const
        }
      }))
      if (!stop) setNeedsInput(Object.fromEntries(entries))
    }
    checkPrompts()
    const t = setInterval(checkPrompts, 4000)
    return () => { stop = true; clearInterval(t) }
  }, [list])
  // W7 关闭分流（非 worktree 确认后结束；worktree 有东西三选一；同 worktree 还有别人只关自己）和左树同一份
  const closer = useSessionCloser(closeTerm, load)
  const goSwarm = (sw: string) => { location.hash = '#/swarm/' + encodeURIComponent(sw) }
  // ── 筛选 / 搜索 ──
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<'all' | 'waiting' | 'claude' | 'codex' | 'opencode' | 'pi' | 'swarm' | 'idle'>('all')
  const ql = q.trim().toLowerCase()
  const isSwarm = (s: any) => !!swarmMap[s.name]
  // 默认不展示蜂群会话（它们有专门的蜂群页）；仅「蜂群」筛选时才列出
  const match = (s: any, f: typeof filter) => {
    if (f === 'swarm') return isSwarm(s)
    if (f === 'waiting') return !!needsInput[s.name]
    if (isSwarm(s)) return false
    switch (f) {
      case 'claude': return !!cc[s.name]
      case 'codex': return !!cx[s.name]
      case 'opencode': return agentKinds[s.name] === 'opencode'
      case 'pi': return agentKinds[s.name] === 'pi'
      case 'idle': return !agentKinds[s.name] && !cc[s.name] && !cx[s.name]
      default: return true
    }
  }
  const filtered = list.filter((s: any) => (!ql || `${s.label || ''} ${s.name}`.toLowerCase().includes(ql)) && match(s, filter))
  const cnt = (f: typeof filter) => list.filter((s: any) => match(s, f)).length

  // ── 排序：名称 / 创建时间 / 最后响应时间，可切升降序 ──
  const [sortBy, setSortBy] = useState<'name' | 'created' | 'activity'>('activity')
  const [sortAsc, setSortAsc] = useState(false)
  const num = (v: any) => parseInt(v, 10) || 0
  const sorted = [...filtered].sort((a: any, b: any) => {
    const d = sortBy === 'name'
      ? a.name.localeCompare(b.name)
      : num(a[sortBy === 'created' ? 'created' : 'last_activity']) - num(b[sortBy === 'created' ? 'created' : 'last_activity'])
    return sortAsc ? d : -d
  })

  // ── W2 仓库分组：同仓库 ≥2 个 worktree 会话聚组，组头可折叠(记 localStorage) ──
  const { desktop: wide } = useLayout()
  const [wtCollapsed, setWtCollapsed] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem('ttmux_wt_groups') || '{}') } catch { return {} }
  })
  const toggleGroup = (repo: string) => setWtCollapsed((m) => {
    const next = { ...m, [repo]: !m[repo] }
    try { localStorage.setItem('ttmux_wt_groups', JSON.stringify(next)) } catch { /* 忽略 */ }
    return next
  })
  const repoOf = (name: string) => { const a = wtAnn[name]; return a?.primary?.linked ? a.primary.repo as string : '' }
  // 分组仓库的 worktree 全貌(总数/孤儿)：让会话页感知还有没挂会话的 worktree
  const [repoWt, setRepoWt] = useState<Record<string, { total: number; orphans: number }>>({})
  useEffect(() => {
    const repos = Array.from(new Set(Object.values(wtAnn)
      .map((a: any) => (a?.primary?.linked ? a.primary.repo as string : ''))
      .filter(Boolean)))
    if (!repos.length) { setRepoWt({}); return }
    let stop = false
    Promise.all(repos.map(async (r) => {
      try {
        const res = await api('GET', `/git/worktrees?dir=${encodeURIComponent(r)}`)
        const wts = (Array.isArray(res?.data) ? res.data : []).filter((w: any) => !w.isMain && !w.prunable)
        return [r, { total: wts.length, orphans: wts.filter((w: any) => !(w.sessions || []).length).length }] as const
      } catch { return [r, { total: 0, orphans: 0 }] as const }
    })).then((es) => { if (!stop) setRepoWt(Object.fromEntries(es)) })
    return () => { stop = true }
  }, [wtAnn])
  // 竞赛成员映射：竞赛分组优先于仓库分组（同一批会话不重复聚组）
  const raceOf: Record<string, any> = {}
  for (const rc of races) {
    if (rc.status === 'cleaned') continue
    for (const ct of rc.contestants || []) raceOf[ct.session] = rc
  }
  // 父子树（设计 §2.2）：parent 是显式强关系（fork 意图），分组优先级 竞赛 > 父子树 > 仓库
  const alive = new Set(sorted.map((s: any) => s.name))
  const byName: Record<string, any> = {}
  for (const s of sorted) byName[s.name] = s
  const kidsOf: Record<string, any[]> = {}
  for (const s of sorted) {
    if (raceOf[s.name]) continue
    if (s.parent && alive.has(s.parent) && !raceOf[s.parent]) (kidsOf[s.parent] ||= []).push(s)
  }
  const famRootOf = (s: any) => {
    let cur = s
    const seen = new Set<string>([s.name])
    while (cur.parent && alive.has(cur.parent) && !raceOf[cur.parent] && !seen.has(cur.parent)) {
      seen.add(cur.parent); cur = byName[cur.parent]
    }
    return cur
  }
  const famInvolved = (s: any) => !raceOf[s.name] &&
    ((kidsOf[s.name]?.length || 0) > 0 || (s.parent && alive.has(s.parent) && !raceOf[s.parent]))
  const groupCounts: Record<string, number> = {}
  for (const s of sorted) { const r = repoOf(s.name); if (r && !raceOf[s.name] && !famInvolved(s)) groupCounts[r] = (groupCounts[r] || 0) + 1 }
  const entries: any[] = []
  {
    const consumed = new Set<string>()
    for (const s of sorted) {
      if (consumed.has(s.name)) continue
      const rc = raceOf[s.name]
      if (rc) {
        // 竞赛组头(W2)：RACE <名> ×N + [对比台]
        const members = sorted.filter((x: any) => raceOf[x.name]?.id === rc.id)
        members.forEach((m: any) => consumed.add(m.name))
        const key = 'race:' + rc.id
        entries.push({ kind: 'race', race: rc, count: members.length, key })
        if (!wtCollapsed[key]) members.forEach((m: any) => entries.push({ kind: 'sess', s: m, indent: true, race: true }))
        continue
      }
      if (famInvolved(s)) {
        // 父子树：根行照常，子孙 DFS 缩进（⑂ 紫色导线）
        const root = famRootOf(s)
        if (consumed.has(root.name)) continue
        consumed.add(root.name)
        entries.push({ kind: 'sess', s: root, indent: false })
        const dfs = (parent: string, depth: number) => {
          for (const kid of kidsOf[parent] || []) {
            if (consumed.has(kid.name)) continue
            consumed.add(kid.name)
            entries.push({ kind: 'sess', s: kid, indent: true, fam: true, depth })
            dfs(kid.name, depth + 1)
          }
        }
        dfs(root.name, 1)
        continue
      }
      const r = repoOf(s.name)
      if (r && groupCounts[r] >= 2) {
        const members = sorted.filter((x: any) => repoOf(x.name) === r && !raceOf[x.name] && !famInvolved(x))
        members.forEach((m: any) => consumed.add(m.name))
        entries.push({ kind: 'group', repo: r, count: members.length })
        if (!wtCollapsed[r]) members.forEach((m: any) => entries.push({ kind: 'sess', s: m, indent: true }))
      } else {
        entries.push({ kind: 'sess', s, indent: false })
      }
    }
  }
  const compareRace = races.find((rc) => rc.id === compareId) || null

  // 会话动作：Worktree 管理 + 新建（两处复用，桌面进页头、手机独占一行）
  const sessionActions = (
    <>
      <Tooltip title={t('worktree.entryTip')}>
        <Button style={isPhone ? { flex: 1, minWidth: 0 } : undefined}
          onClick={() => { setWtDir(undefined); setWtOpen(true) }}>{t('worktree.entry')}</Button>
      </Tooltip>
      {/* 必须钉住 flex：Dropdown.Button 内的 Space.Compact 是块级 flex 子项，不钉就会
          一路撑开并盖住左边那枚按钮（项目页页头、手机头部都踩过同一个坑） */}
      <span style={{ flex: '0 0 auto', display: 'inline-flex' }}>
        {/* 新建下拉(W5 入口)：主点 = 新建会话；菜单 = 新建竞赛 */}
        <Dropdown.Button type="primary" onClick={() => setNewOpen(true)}
          menu={{ items: [{ key: 'race', label: t('race.new') }], onClick: () => setRaceOpen(true) }}>
          + {t('session.new')}
        </Dropdown.Button>
      </span>
    </>
  )

  return (
    // 不再套 Card：嵌在概览「会话」tab 里时，卡片边框 + 「会话 13」标题与外面的 tab
    // 完全重复——一层壳里套一层同名的壳。独立页则用与概览/项目同一套页头。
    <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
      {/* 手机才需要自己占一行（横向放不下）；桌面并进下面搜索那一行，
          否则「Worktree 管理 / ＋新建会话」白占一整行 */}
      {isPhone && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>{sessionActions}</div>
      )}
      {/* 工具条：页名 + 搜索 + 排序同一行，类型筛选另起一行。
          页名并进这一行而不是单独的 .tt-pagehead（图纸 14-desktop-workspace/pagehead.html）：
          眉标「工作区」+ 大标题「会话」+ 一句「所有会话，按 Agent、等待状态与最近响应筛选」
          三层 91px，说的全是侧栏那条高亮导航项已经说完的事。 */}
      <div style={{ marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {!embedded && !isPhone && (<>
            <span className="tt-pagename" title={t('session.subtitle')}>{t('nav.sessions')}</span>
            <span className="tt-pagedivider" aria-hidden="true" />
          </>)}
          <Input allowClear value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('session.searchPlaceholder')}
            style={{ flex: 1, minWidth: 0 }}
            prefix={<SearchIcon size={15} />} />
          <Select value={sortBy} onChange={(v) => setSortBy(v)} title={t('session.sortBy')}
            style={{ width: 120, flex: '0 0 auto' }} options={[
              { label: t('session.sortActivity'), value: 'activity' },
              { label: t('session.sortCreated'), value: 'created' },
              { label: t('session.sortName'), value: 'name' },
            ]} />
          <Button onClick={() => setSortAsc((v) => !v)} style={{ flex: '0 0 auto' }}
            title={sortAsc ? t('session.sortAsc') : t('session.sortDesc')}>
            {sortAsc ? <ArrowUp size={13} /> : <ArrowDown size={13} />}
          </Button>
          {!isPhone && sessionActions}
        </div>
        {/* 一律按内容宽：block 在手机上把 6 项等分成 ~60px、标签全截成「全部…」；
            在桌面上又把 6 个标签摊到 1200px，中间空出大片，读起来是散的。
            筛选条本来就该贴左、只占它需要的宽度。 */}
        <div style={{ overflowX: 'auto' }} className="tt-seg-scroll">
          <Segmented value={filter} onChange={(v) => setFilter(v as any)} size="small" options={[
            { label: `${t('common.all')} ${cnt('all')}`, value: 'all' },
            { label: `${t('session.waiting')} ${cnt('waiting')}`, value: 'waiting' },
            { label: `Claude ${cnt('claude')}`, value: 'claude' },
            { label: `Codex ${cnt('codex')}`, value: 'codex' },
            { label: `OpenCode ${cnt('opencode')}`, value: 'opencode' },
            { label: `Pi ${cnt('pi')}`, value: 'pi' },
            { label: `${t('nav.swarm')} ${cnt('swarm')}`, value: 'swarm' },
            { label: `${t('terminal.status.idle')} ${cnt('idle')}`, value: 'idle' },
          ]} />
        </div>
      </div>

      {list.length === 0 ? <Empty description={t('session.noActive')} />
        : filtered.length === 0 ? <Empty description={t('session.noMatches')} />
          : (
            <List dataSource={entries} renderItem={(en: any) => {
              if (en.kind === 'race') {
                const rc = en.race
                const collapsed = !!wtCollapsed[en.key]
                return (
                  // 竞赛组头(W6 入口)：RACE 徽标 + 名字 + 选手数 + 对比台
                  <List.Item style={{ padding: '10px 8px 4px 6px', cursor: 'pointer', borderBlockEnd: 'none' }} onClick={() => toggleGroup(en.key)}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', minWidth: 0 }}>
                      <span style={{ color: 'var(--text-dimmer)', flex: '0 0 auto', display: 'inline-flex' }}><Disclosure open={!collapsed} /></span>
                      <Tag color="gold" style={{ margin: 0, flex: '0 0 auto', fontSize: 11, lineHeight: '18px', height: 20 }}>RACE</Tag>
                      <span style={{ fontWeight: 700, color: 'var(--text-bright)', fontSize: 13, flex: '0 0 auto' }}>{rc.name}</span>
                      {rc.base && <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11.5, color: 'var(--text-dimmer)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{t('race.groupBase', { base: rc.base })}</span>}
                      <Tag style={{ margin: 0, flex: '0 0 auto', fontSize: 11, lineHeight: '18px', height: 20 }}>×{en.count}</Tag>
                      {rc.status === 'crowned' && <Tag color="gold" style={{ margin: 0, flex: '0 0 auto', fontSize: 11, lineHeight: '18px', height: 20 }}>{t('race.status.crowned')}</Tag>}
                      <span style={{ flex: 1 }} />
                      <a style={{ fontSize: 12.5, flex: '0 0 auto' }} onClick={(e) => { e.stopPropagation(); setCompareId(rc.id) }}>{t('race.compare')}</a>
                    </div>
                  </List.Item>
                )
              }
              if (en.kind === 'group') {
                const repo: string = en.repo
                const base = repo.split('/').filter(Boolean).pop() || repo
                const collapsed = !!wtCollapsed[repo]
                return (
                  // 仓库分组头(W2)：折叠三角 + 仓库名 + 路径 + worktree 计数 + 管理入口
                  <List.Item style={{ padding: '10px 8px 4px 6px', cursor: 'pointer', borderBlockEnd: 'none' }} onClick={() => toggleGroup(repo)}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', minWidth: 0 }}>
                      <span style={{ color: 'var(--text-dimmer)', flex: '0 0 auto', display: 'inline-flex' }}><Disclosure open={!collapsed} /></span>
                      <span style={{ fontWeight: 700, color: 'var(--text-bright)', fontSize: 13, flex: '0 0 auto' }}>{base}</span>
                      <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11.5, color: 'var(--text-dimmer)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{repo}</span>
                      <Tag color="cyan" style={{ margin: 0, flex: '0 0 auto', fontSize: 11, lineHeight: '18px', height: 20 }}>{t('worktree.groupCount', { count: repoWt[repo]?.total ?? en.count })}</Tag>
                      {(repoWt[repo]?.orphans ?? 0) > 0 && (
                        <Tooltip title={t('worktree.groupOrphansTip')}>
                          <Tag color="warning" style={{ margin: 0, flex: '0 0 auto', fontSize: 11, lineHeight: '18px', height: 20, cursor: 'pointer' }}
                            onClick={(e) => { e.stopPropagation(); setWtDir(repo); setWtOpen(true) }}>
                            {t('worktree.groupOrphans', { count: repoWt[repo].orphans })}
                          </Tag>
                        </Tooltip>
                      )}
                      <span style={{ flex: 1 }} />
                      <a style={{ fontSize: 12.5, flex: '0 0 auto' }} onClick={(e) => { e.stopPropagation(); setWtDir(repo); setWtOpen(true) }}>{t('worktree.manage')}</a>
                    </div>
                  </List.Item>
                )
              }
              const s = en.s
              const indent = !!en.indent
              const sw = swarmMap[s.name]
              const connected = s.attached == 1
              const agent = agentKinds[s.name] || (cc[s.name] ? 'claude' : cx[s.name] ? 'codex' : null)
              const waiting = !!needsInput[s.name]
              // 休眠：机器重启带走了 tmux 那一半，台账还认得它，点开即恢复。
              // 它没有进程，所以 attached/agent/待输入这些运行时判断都不适用。
              const dormant = s.state === 'dormant'
              const activeRow = activeTerm === s.name
              return (
                // 整行点击直接进入终端；右侧操作区 stopPropagation 不触发进入
                <List.Item style={{
                  position: 'relative', overflow: 'hidden',
                  marginLeft: indent ? 14 * (en.depth || 1) : 0,
                  borderLeft: indent ? (en.race ? '2px solid rgba(212,160,23,.35)' : en.fam ? '2px solid rgba(163,113,247,.4)' : '2px solid rgba(57,197,207,.3)') : undefined,
                  padding: '10px 8px 10px 12px', cursor: 'pointer',
                  borderRadius: indent ? '0 var(--r-sm) var(--r-sm) 0' : 'var(--r-sm)',
                  background: activeRow ? 'linear-gradient(90deg, rgba(31,111,235,.38), rgba(31,111,235,.16))' : undefined,
                  border: activeRow ? '1px solid var(--accent)' : '1px solid transparent',
                  boxShadow: activeRow ? '0 0 0 1px rgba(88,166,255,.18), 0 0 18px rgba(31,111,235,.14)' : undefined,
                }}
                // 会话页的行也能拖（21 设计）：拖到终端画面/标签上 = 告诉那个会话
                // 怎么跟这一行说话。项目页的任务卡是同一件事，两处入口都给。
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(SESSION_MIME, JSON.stringify({
                    id: s.name, label: sessionLabel(s.name),
                    dir: s.cwd || '', agent: agent || '',
                    node: currentNodeId() || '',
                  }))
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                onClick={() => openTerm(s.name)}>
                  {activeRow && <span aria-hidden style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: 'var(--accent)' }} />}
                  {/* 七个格子恒定：缺一个桌面上就整行错列，所以空的项目/位置格照样渲染（见 .tt-srow） */}
                  <div className="tt-srow">
                    <i title={dormant ? t('session.dormant.hint') : waiting ? t('prompt.confirmRequired') : connected ? t('terminal.status.connected') : t('terminal.status.idle')}
                      style={{
                        width: 8, height: 8, borderRadius: '50%', flex: '0 0 8px',
                        // 休眠是空心：灰实心已经是「活着但空闲」，而这两者的区别是
                        // 点下去会发生什么——一个直接进终端，一个要先把会话重开出来。
                        background: dormant ? 'transparent' : waiting ? '#d29922' : connected ? 'var(--ok)' : 'var(--text-dimmer)',
                        boxShadow: dormant ? 'inset 0 0 0 1.5px var(--text-dimmer)' : undefined,
                      }} />
                    <span className="nm" style={{ color: activeRow ? '#fff' : dormant ? 'var(--text-dim)' : undefined }}
                      title={`${s.label || s.name}（${s.id || s.name}）· ${t('session.createdAt')} ${absTime(s.created)}`}>
                      {en.fam && <Tooltip title={t('session.fork.childOf', { parent: s.parent })}><span style={{ color: 'var(--swarm)', marginRight: 6, display: 'inline-flex' }}><BranchIcon size={12} /></span></Tooltip>}
                      {s.label || s.name}
                      {/* 会话 ID 只留尾 4 位：全名与名字同权并排时，每行前半截都在念一串日期 */}
                      {(s.id || s.name) !== (s.label || s.name) && <span className="id">{(s.id || s.name).slice(-4)}</span>}
                    </span>
                    <span className="pj">{sessProj[s.name]?.name}</span>
                    {(() => { // 位置列：有 worktree 就是 ⎇ 分支（点开进 worktree 管理），否则是工作目录
                      const ann = wtAnn[s.name]
                      const loc = sessionLocation(ann, s.cwd, sessProj[s.name]?.dir)
                      if (!loc.branch && !loc.path) return <span className="loc" />
                      const tip = loc.branch
                        ? t('worktree.sessionTagTip', { path: ann?.primary?.worktree || '' })
                          + (ann?.ambiguous ? ' · ' + t('worktree.sessionTagAmbiguous', { count: ann.matches?.length || 0 }) : '')
                        : loc.title
                      return (
                        <span className="loc" title={tip}
                          onClick={ann?.primary?.linked ? (e) => { e.stopPropagation(); setWtDir(ann.primary.repo); setWtOpen(true) } : undefined}
                          style={ann?.primary?.linked ? { cursor: 'pointer' } : undefined}>
                          {loc.branch ? <span className="br"><BranchIcon size={11} />{loc.branch}{ann?.ambiguous ? ' +' : ''}</span> : loc.path}
                        </span>
                      )
                    })()}
                    <span className="tags">
                      <MemBar mem={s.mem} compact={!wide} />
                      {(() => { // 窄档只留一枚 ⎇ 图标（桌面由位置列接管）；外部 worktree 加 ⧉
                        const ann = wtAnn[s.name]
                        if (!ann?.primary?.linked) return null
                        return (<>
                          <span className="tt-branch act" title={ann.primary.repo}
                            onClick={(e) => { e.stopPropagation(); setWtDir(ann.primary.repo); setWtOpen(true) }}><BranchIcon size={11} /></span>
                          {ann.primary.external && <Tag className="wt" style={{ margin: 0, flex: '0 0 auto' }}><WindowsIcon size={11} /></Tag>}
                        </>)
                      })()}
                      {sw && <Tag color="blue" style={{ margin: 0, flex: '0 0 auto' }}>{t('nav.swarm')}:{sw.swarm}{sw.role === 'leader' ? `·${t('swarm.master')}` : ''}</Tag>}
                      {waiting && !dormant && <Tag color="warning" style={{ margin: 0, flex: '0 0 auto' }}>{t('session.waiting')}</Tag>}
                      {agent && !dormant && <span className="tt-agentmark"><AgentLogo kind={agent} size={12} />{agentName(agent)}</span>}
                      {/* 休眠会话必须一眼看得出来。从前它和活会话一样显示「空闲中」，
                          于是点下去才发现是要重开的——那正是「点击恢复又新建了一个」的由来。 */}
                      {dormant && (
                        <Tag color={s.resumable ? 'blue' : undefined} style={{ margin: 0, flex: '0 0 auto' }}>
                          {t(s.resumable ? 'session.dormant.resumable' : 'session.dormant.hint')}
                        </Tag>
                      )}
                      {!sw && !agent && !dormant && <Tag style={{ margin: 0, flex: '0 0 auto' }}>{connected ? t('terminal.status.connected') : t('terminal.status.idle')}</Tag>}
                      {/* 窗口数 99% 的会话都是 1，常驻就是一列噪声——只在 >1 时说 */}
                      {s.windows > 1 && <span style={{ color: 'var(--text-dim)', fontSize: 12, whiteSpace: 'nowrap' }}>{t('session.windows', { count: s.windows })}</span>}
                    </span>
                    <span className="tm" title={absTime(s.last_activity)}>{relTime(s.last_activity, t)}</span>
                    <span className="acts" onClick={(e) => e.stopPropagation()}>
                      {!sw && wide && <a onClick={() => setForking(s.name)}>{t('session.fork.entry')}</a>}
                      {sw && <a onClick={() => goSwarm(sw.swarm)}>{t('session.swarmPage')}</a>}
                      {sw ? (
                        <Popconfirm
                          title={t('session.closeSwarmSessionTitle')}
                          description={<div style={{ maxWidth: 280 }}>{t('session.closeSwarmSessionDesc', { swarm: sw.swarm, role: sw.role === 'leader' ? t('swarm.master') : t('swarm.member') })}</div>}
                          okText={t('session.closeAnyway')} okButtonProps={{ danger: true }} cancelText={t('common.cancel')}
                          onConfirm={() => closer.kill(s.name)}>
                          <a style={{ color: '#f85149' }}>{t('session.close')}</a>
                        </Popconfirm>
                      ) : (
                        <a style={{ color: '#f85149' }} onClick={() => { void closer.beginClose(s.name) }}>{t('session.close')}</a>
                      )}
                    </span>
                  </div>
                </List.Item>
              )
            }} />
          )}
      {/* 已结束的会话（M3）：默认折叠，展开才拉数据。放在列表尾部——
          它是「要找的时候能找到」，不该跟活着的会话抢位置。 */}
      <SessionHistory onRestored={(name) => { load(); openTerm(name) }} />
      <NewSessionModal open={newOpen || !!forking} parent={forking}
        onClose={() => { setNewOpen(false); setForking(null) }} onDone={(name) => { load(); openTerm(name) }} />
      {closer.node}
      <Suspense fallback={null}>
        <WorktreePanel open={wtOpen} onClose={() => { setWtOpen(false); setWtDir(undefined) }} openTerm={openTerm} initialDir={wtDir} />
      </Suspense>
      <Suspense fallback={null}>
        {raceOpen && <RaceCreateModal open={raceOpen} onClose={() => setRaceOpen(false)}
          onDone={() => { reloadRaces(); load() }} />}
        {compareRace && <RaceComparePanel race={compareRace} onClose={() => setCompareId('')}
          openTerm={openTerm} onChanged={() => { reloadRaces(); load() }} />}
      </Suspense>
    </div>
  )
}
