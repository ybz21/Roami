import { useRegisteredAgents } from '../../agent-registry'
import { agentLaunch } from '../../agent-command'
import { agentName } from '../../agent-kind'
// 竞赛（设计 docs/design/web/07-worktree.md §3 W5/W6）：
// W5 创建弹窗 = 一个 prompt × N 选手，提交一次调 POST /races（后端逐选手编排）。
// W6 对比台 = 全屏浮层，横排选手 lane + 下半屏 diff；「选为赢家」走 crown 状态机。
import { useEffect, useRef, useState } from 'react'
import { App as AntApp, AutoComplete, Button, Checkbox, Drawer, Dropdown, Empty, Input, Modal, Select, Space, Tag, Tooltip } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { usePreferences } from '../../preferences'
import { recentDirs } from '../sessions/DirPicker'
import DiffView from '../files/DiffView'
import { CloseIcon, PlusIcon } from '../../icons'
import { BranchIcon } from '../git/parts'
import { branchNames } from '../git/local-branches'

export type RaceContestant = {
  // session 会话名(= 会话 id)：打开终端的 handle；label 展示名 `<竞赛>-<字母>`
  session: string; label?: string; agent: string; branch: string; path: string
  status: string; error?: string
}
export type Race = {
  id: string; name: string; dir: string; base: string; prompt: string
  createdAt: string; status: string; winner?: string; contestants: RaceContestant[]
}

const enc = encodeURIComponent
const AGENT_COLOR: Record<string, string> = { claude: 'var(--accent)', codex: 'var(--ok)' }
const MAX_CONTESTANTS = 5

function laneSlug(name: string): string {
  const s = name.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '')
  return s || 'task'
}

// ── W5 竞赛创建弹窗 ──────────────────────────────────────
export function RaceCreateModal({ open, onClose, onDone }: {
  open: boolean; onClose: () => void; onDone: (race: Race) => void
}) {
  const [name, setName] = useState('')
  const [dir, setDir] = useState('')
  const [isGitRepo, setIsGitRepo] = useState(false)
  const [base, setBase] = useState('')
  const [branches, setBranches] = useState<string[]>([])
  const [defBranch, setDefBranch] = useState('')
  const [prompt, setPrompt] = useState('')
  const registered = useRegisteredAgents(open)
  const [agents, setAgents] = useState<string[]>(['claude', 'codex'])
  const [creating, setCreating] = useState(false)
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [prefs] = usePreferences()
  useEffect(() => {
    if (open) { setName(''); setDir(''); setIsGitRepo(false); setBase(''); setBranches([]); setDefBranch(''); setPrompt(''); setAgents(['claude', 'codex']); setCreating(false) }
  }, [open])
  useEffect(() => {
    const d = dir.trim()
    if (!d) { setIsGitRepo(false); return }
    let cancelled = false
    api('GET', `/git/is-repo?path=${enc(d)}`).then((r) => { if (!cancelled) setIsGitRepo(!!r?.data?.repo) })
      .catch(() => { if (!cancelled) setIsGitRepo(false) })
    return () => { cancelled = true }
  }, [dir])
  useEffect(() => {
    if (!isGitRepo || !dir.trim()) return
    let cancelled = false
    api('GET', `/git/branches?dir=${enc(dir.trim())}`).then((r) => {
      if (cancelled) return
      const bs = branchNames(r?.data?.branches)
      const def: string = r?.data?.default || ''
      setBranches(bs); setDefBranch(def)
      setBase((prev) => (prev && bs.includes(prev) ? prev : def))
    }).catch(() => {})
    return () => { cancelled = true }
  }, [isGitRepo, dir])

  const ok = async () => {
    if (!name.trim()) return message.error(t('race.nameRequired'))
    if (!isGitRepo || !dir.trim()) return message.error(t('race.needRepo'))
    if (!prompt.trim()) return message.error(t('race.promptRequired'))
    try {
      setCreating(true)
      const res = await api('POST', '/races', {
        name: name.trim(), dir: dir.trim(), prompt: prompt.trim(),
        ...(base ? { base } : {}),
        contestants: agents.map((a) => ({
          agent: a,
          cmd: agentLaunch(a, prefs),
        })),
      })
      const race: Race = res.data
      const failed = (race.contestants || []).filter((c) => c.status === 'failed').length
      if (failed > 0) message.warning(t('race.someFailed', { count: failed }))
      else message.success(t('race.created'))
      onClose(); onDone(race)
    } catch (e: any) { message.error(e.message) }
    finally { setCreating(false) }
  }

  const slug = laneSlug(name)
  return (
    <Modal open={open} onCancel={onClose} onOk={ok} okText={t('race.start')} title={t('race.title')} destroyOnClose
      confirmLoading={creating} width={560}>
      <Space direction="vertical" style={{ width: '100%' }} size={10}>
        <Input placeholder={t('race.namePlaceholder')} value={name} autoFocus onChange={(e) => setName(e.target.value)} />
        <AutoComplete style={{ width: '100%' }} value={dir} onChange={setDir}
          options={recentDirs().map((d) => ({ value: d }))}
          filterOption={(input, opt) => String(opt?.value).toLowerCase().includes(input.toLowerCase())}
          placeholder={t('race.repoPlaceholder')} />
        {!isGitRepo && dir.trim() && <div style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>{t('race.needRepo')}</div>}
        {isGitRepo && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ flex: '0 0 auto', color: 'var(--text-dim)', fontSize: 13 }}>{t('session.wt.base')}</span>
            <Select size="small" showSearch optionFilterProp="label" style={{ flex: 1, minWidth: 0 }}
              value={base || undefined} onChange={(v) => setBase(v)} placeholder={t('session.wt.basePlaceholder')}
              options={[
                ...(defBranch ? [{ value: defBranch, label: t('session.wt.defaultBranch', { name: defBranch }) }] : []),
                ...branches.filter((b) => b !== defBranch).map((b) => ({ value: b, label: b })),
              ]} />
          </div>
        )}
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 13, marginBottom: 6 }}>{t('race.contestants', { max: MAX_CONTESTANTS })}</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {agents.map((a, i) => (
              <div key={i} style={{
                width: 112, border: '1px solid var(--border-subtle, #30363d)', borderRadius: 10, padding: '10px 10px 8px',
                position: 'relative', background: 'var(--bg-elevated)', display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center',
              }}>
                <span style={{ position: 'absolute', top: 3, right: 8, color: 'var(--text-dimmer)', fontSize: 11, cursor: 'pointer' }}
                  onClick={() => setAgents((xs) => xs.filter((_, j) => j !== i))}><CloseIcon size={12} /></span>
                <span style={{ fontSize: 13, fontWeight: 700, color: AGENT_COLOR[a] }}>{agentName(a)}</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text-dimmer)', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {slug}-{String.fromCharCode(97 + i)}
                </span>
              </div>
            ))}
            {agents.length < MAX_CONTESTANTS && (
              <Dropdown trigger={['click']} menu={{
                items: registered.map(agent => ({ key: agent.kind, label: agent.displayName })),
                onClick: ({ key }) => setAgents((xs) => [...xs, key]),
              }}>
                <div style={{
                  width: 112, minHeight: 66, border: '1px dashed var(--border-subtle, #30363d)', borderRadius: 10,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, color: 'var(--text-dimmer)', cursor: 'pointer', fontSize: 12.5,
                }}><PlusIcon size={12} />{t('race.addContestant')}</div>
              </Dropdown>
            )}
          </div>
        </div>
        <Input.TextArea placeholder={t('race.promptPlaceholder')} value={prompt}
          onChange={(e) => setPrompt(e.target.value)} autoSize={{ minRows: 4, maxRows: 10 }} />
        {agents.length > 0 && (
          <div style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>{t('race.estimate', { count: agents.length })}</div>
        )}
      </Space>
    </Modal>
  )
}

// ── W6 竞赛对比台 ────────────────────────────────────────
type Lane = {
  ct: RaceContestant
  wt: any | null       // /git/worktrees 里的实况行
  diff: any | null     // /git/worktree/diff 统计
  alive: boolean       // 会话还在
  running: boolean     // agent 进程仍在跑
}


export function RaceComparePanel({ race, onClose, openTerm, onChanged }: {
  race: Race | null
  onClose: () => void
  openTerm: (n: string) => void
  onChanged: () => void
}) {
  const [lanes, setLanes] = useState<Lane[]>([])
  const [sel, setSel] = useState('')      // 选中 lane 的 session
  const [file, setFile] = useState('')    // 选中文件
  const [fileDiff, setFileDiff] = useState('')
  const [crowning, setCrowning] = useState<Lane | null>(null)
  const [strategy, setStrategy] = useState<'squash' | 'merge' | 'rebase'>('squash')
  const [cleanup, setCleanup] = useState(true)
  const [busy, setBusy] = useState(false)
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const raceRef = useRef(race)
  raceRef.current = race

  // 5s 轮询实况：worktree 状态 + diff 统计 + agent 进程
  useEffect(() => {
    const r = race
    if (!r) { setLanes([]); setSel(''); setFile(''); setFileDiff(''); return }
    let stop = false
    const load = async () => {
      try {
        const [wtsR, sessR] = await Promise.all([
          api('GET', `/git/worktrees?dir=${enc(r.dir)}`).catch(() => null),
          api('GET', '/sessions').catch(() => []),
        ])
        const wts: any[] = Array.isArray(wtsR?.data) ? wtsR.data : []
        const aliveSet = new Set((Array.isArray(sessR) ? sessR : []).map((s: any) => s.name))
        const next = await Promise.all(r.contestants.map(async (ct): Promise<Lane> => {
          const wt = wts.find((w) => w.path === ct.path) || null
          let diff: any = null
          if (wt) {
            try { diff = (await api('GET', `/git/worktree/diff?path=${enc(ct.path)}`))?.data || null } catch {}
          }
          let running = false
          if (aliveSet.has(ct.session)) {
            try {
              const probe = await api('GET', `/sessions/${enc(ct.session)}/${ct.agent === 'codex' ? 'codex' : 'claude'}`)
              running = !!probe?.data?.running
            } catch {}
          }
          return { ct, wt, diff, alive: aliveSet.has(ct.session), running }
        }))
        if (stop) return
        setLanes(next)
        setSel((prev) => (prev && next.some((l) => l.ct.session === prev) ? prev : (next.find((l) => l.diff)?.ct.session || next[0]?.ct.session || '')))
      } catch {}
    }
    load()
    const timer = setInterval(load, 5000)
    return () => { stop = true; clearInterval(timer) }
  }, [race?.id])

  const selLane = lanes.find((l) => l.ct.session === sel) || null
  // 选中 lane 的文件清单：已提交 + 未提交合并展示（文件名去重，± 相加）
  const files: { path: string; adds: number; dels: number }[] = (() => {
    if (!selLane?.diff) return []
    const m = new Map<string, { path: string; adds: number; dels: number }>()
    for (const part of [selLane.diff.committed, selLane.diff.workingTree]) {
      for (const f of part?.files || []) {
        const cur = m.get(f.path) || { path: f.path, adds: 0, dels: 0 }
        cur.adds += f.adds; cur.dels += f.dels
        m.set(f.path, cur)
      }
    }
    return Array.from(m.values())
  })()
  useEffect(() => {
    setFile((prev) => (prev && files.some((f) => f.path === prev) ? prev : (files[0]?.path || '')))
  }, [sel, files.length])
  useEffect(() => {
    if (!selLane || !file) { setFileDiff(''); return }
    let cancelled = false
    api('GET', `/git/worktree/diff?path=${enc(selLane.ct.path)}&file=${enc(file)}`)
      .then((r) => { if (!cancelled) setFileDiff(r?.data?.diff || '') })
      .catch(() => { if (!cancelled) setFileDiff('') })
    return () => { cancelled = true }
  }, [sel, file, lanes])

  const laneStatus = (l: Lane) => {
    if (l.ct.status === 'failed') return <Tag color="error" style={{ margin: 0 }}>{t('race.status.failed')}</Tag>
    if (race?.winner === l.ct.session && race?.status === 'crowned') return <Tag color="gold" style={{ margin: 0 }}>{t('race.status.winner')}</Tag>
    if (!l.alive) return <Tag style={{ margin: 0 }}>{t('race.status.gone')}</Tag>
    if (l.running) return <Tag color="blue" style={{ margin: 0 }}>{t('race.status.running')}</Tag>
    return <Tag color="green" style={{ margin: 0 }}>{t('race.status.idle')}</Tag>
  }

  const doCrown = async () => {
    const r = raceRef.current
    if (!r || !crowning) return
    try {
      setBusy(true)
      await api('POST', `/races/${enc(r.id)}/crown`, {
        winner: crowning.ct.session, strategy, cleanup,
        ...(crowning.wt?.head ? { expectedHead: crowning.wt.head } : {}),
      })
      message.success(t('race.crowned', { base: r.base || 'base' }))
      setCrowning(null); onChanged()
    } catch (e: any) {
      const ae = e.apiError || {}
      message.error(ae.stage ? t('race.crownFailedAtStage', { stage: ae.stage, msg: e.message }) : e.message)
    } finally { setBusy(false) }
  }

  const doCleanAll = () => {
    const r = raceRef.current
    if (!r) return
    modal.confirm({
      title: t('race.cleanAllTitle'),
      content: t('race.cleanAllDesc', { count: r.contestants.length }),
      okText: t('race.cleanAll'), okButtonProps: { danger: true },
      onOk: async () => {
        await api('POST', `/races/${enc(r.id)}/cleanup`)
        await api('DELETE', `/races/${enc(r.id)}`).catch(() => {})
        message.success(t('race.cleaned'))
        onClose(); onChanged()
      },
    })
  }

  const runningOthers = crowning ? lanes.filter((l) => l.ct.session !== crowning.ct.session && l.running).map((l) => l.ct.session) : []

  return (
    <Drawer open={!!race} onClose={onClose} placement="bottom" height="100%" destroyOnClose
      styles={{ body: { display: 'flex', flexDirection: 'column', gap: 14, padding: '14px 18px' }, header: { padding: '10px 18px' } }}
      title={race && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <Tag color="gold" style={{ margin: 0 }}>RACE</Tag>
          <b style={{ fontSize: 15 }}>{race.name}</b>
          <span style={{ color: 'var(--text-dimmer)', fontSize: 12.5, fontWeight: 400 }}>
            {t('race.headMeta', { base: race.base || '?', count: race.contestants.length })}
          </span>
          <span style={{
            color: 'var(--text-dimmer)', fontSize: 12.5, fontWeight: 400, maxWidth: 380, overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap', borderLeft: '1px solid var(--border-subtle, #30363d)', paddingLeft: 10,
          }} title={race.prompt}>{race.prompt}</span>
          <span style={{ flex: 1 }} />
          <Button size="small" danger onClick={doCleanAll}>{t('race.cleanAll')}</Button>
        </div>
      )}>
      {race && (<>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {lanes.map((l) => {
            const isSel = sel === l.ct.session
            const committed = l.diff?.committed
            const working = l.diff?.workingTree
            const adds = (committed?.adds || 0) + (working?.adds || 0)
            const dels = (committed?.dels || 0) + (working?.dels || 0)
            const laneFiles = (() => {
              const set = new Set<string>()
              for (const part of [committed, working]) for (const f of part?.files || []) set.add(f.path)
              return set.size
            })()
            const dirtyCount = (l.wt?.dirty || 0) + (l.wt?.untracked || 0)
            return (
              <div key={l.ct.session} className="tt-racecol" onClick={() => setSel(l.ct.session)} style={{
                flex: '1 1 220px', minWidth: 220, maxWidth: 340, cursor: 'pointer',
                border: isSel ? '1px solid var(--accent)' : '1px solid var(--border-subtle, #30363d)',
                boxShadow: isSel ? '0 0 0 1px rgba(88,166,255,.25), 0 0 20px rgba(31,111,235,.12)' : undefined,
                borderRadius: 12, background: 'var(--bg-container)', padding: '12px 14px',
                display: 'flex', flexDirection: 'column', gap: 8,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700 }}>
                  <span style={{ color: AGENT_COLOR[l.ct.agent] || 'var(--text-bright)' }}>{l.ct.agent === 'codex' ? 'Codex' : 'Claude'}</span>
                  <span style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--text-dim)', fontWeight: 400, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.ct.label || l.ct.session}</span>
                  <span style={{ marginLeft: 'auto', flex: '0 0 auto' }}>{laneStatus(l)}</span>
                </div>
                <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11.5, color: '#39c5cf', display: 'flex', alignItems: 'center', gap: 4 }}><BranchIcon size={11} />{l.ct.branch}</div>
                {l.ct.status === 'failed' ? (
                  <div style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>{l.ct.error}</div>
                ) : (<>
                  <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-dim)' }}>
                    <span><b style={{ display: 'block', color: 'var(--text-bright)', fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>{laneFiles}</b>{t('race.stat.files')}</span>
                    <span><b style={{ display: 'block', fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>
                      <span style={{ color: 'var(--ok)' }}>+{adds}</span> <span style={{ color: '#f85149' }}>−{dels}</span>
                    </b>{t('race.stat.lines')}</span>
                    <span><b style={{ display: 'block', color: 'var(--text-bright)', fontSize: 15, fontFamily: 'ui-monospace, monospace' }}>{l.wt?.committedAhead ?? 0}</b>{t('race.stat.commits')}</span>
                  </div>
                  <div style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>
                    {dirtyCount > 0 ? t('race.uncommitted', { count: dirtyCount }) : t('race.clean')}
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 2 }} onClick={(e) => e.stopPropagation()}>
                    {l.alive && <Button size="small" onClick={() => { openTerm(l.ct.session); onClose() }}>{t('race.enterSession')}</Button>}
                    {race.status !== 'crowned' && l.wt && !!race.base && (
                      <Tooltip title={l.running ? t('race.crownRunningTip') : ''}>
                        <Button size="small" onClick={() => { setStrategy('squash'); setCleanup(true); setCrowning(l) }}
                          style={{ background: 'linear-gradient(135deg,#b8860b,#d4a017)', border: 0, color: '#fff' }}>
                          {t('race.crown')}
                        </Button>
                      </Tooltip>
                    )}
                  </div>
                </>)}
              </div>
            )
          })}
          {!lanes.length && <Empty style={{ margin: '40px auto' }} description={t('race.pickLane')} />}
        </div>

        {/* 下半屏 diff：文件横条切换 + 单文件补丁 */}
        <div style={{ flex: 1, minHeight: 0, border: '1px solid var(--border-subtle, #30363d)', borderRadius: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px', background: 'var(--bg-container)', borderBottom: '1px solid var(--border-subtle, #30363d)', fontSize: 12.5, overflowX: 'auto' }}>
            {selLane && <span style={{ fontFamily: 'ui-monospace, monospace', color: AGENT_COLOR[selLane.ct.agent], flex: '0 0 auto' }}>{selLane.ct.label || selLane.ct.session}</span>}
            <span style={{ flex: 1 }} />
            {files.map((f) => (
              <span key={f.path} onClick={() => setFile(f.path)} style={{
                cursor: 'pointer', padding: '2px 8px', borderRadius: 6, flex: '0 0 auto',
                fontFamily: 'ui-monospace, monospace', fontSize: 12,
                background: file === f.path ? 'var(--bg-elevated)' : 'transparent',
                opacity: file === f.path ? 1 : 0.65,
              }} title={`+${f.adds} −${f.dels}`}>{f.path.split('/').pop()}</span>
            ))}
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            {fileDiff.trim()
              ? <DiffView text={fileDiff} />
              : <Empty style={{ marginTop: 48 }} description={selLane ? t('race.noDiff') : t('race.pickLane')} />}
          </div>
        </div>

        {/* 赢家确认框（crown 状态机入口，可只合并不清理） */}
        <Modal open={!!crowning} onCancel={() => setCrowning(null)} onOk={doCrown} confirmLoading={busy}
          okText={t('race.crownOk')} okButtonProps={{ style: { background: 'linear-gradient(135deg,#b8860b,#d4a017)', border: 0 } }}
          title={crowning ? t('race.crownTitle', { name: crowning.ct.label || crowning.ct.session }) : ''} width={420} destroyOnClose>
          {crowning && (
            <Space direction="vertical" style={{ width: '100%' }} size={10}>
              <div style={{ fontSize: 13, color: 'var(--text-dim)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span>{t('race.crownDesc', { branch: crowning.ct.branch, base: race.base || '?' })}</span>
                <Select size="small" value={strategy} onChange={(v) => setStrategy(v)} style={{ width: 100 }}
                  options={[{ value: 'squash', label: 'squash' }, { value: 'merge', label: 'merge' }, { value: 'rebase', label: 'rebase' }]} />
              </div>
              <Checkbox checked={cleanup} onChange={(e) => setCleanup(e.target.checked)}>
                {t('race.crownCleanup', { count: race.contestants.filter((c) => c.session !== crowning.ct.session).length })}
              </Checkbox>
              {cleanup && runningOthers.length > 0 && (
                <div style={{ color: '#d29922', fontSize: 12.5 }}>{t('race.crownRunningWarn', { names: runningOthers.join(', ') })}</div>
              )}
            </Space>
          )}
        </Modal>
      </>)}
    </Drawer>
  )
}
