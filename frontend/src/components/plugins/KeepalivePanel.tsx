// 会话守护面板（roam.keepalive 的宿主侧面板）。界面稿：
// docs/design/plugin/keepalive-panel.html
//
// 这一页要在不滚动的情况下答完四个问题，顺序就是渲染顺序：
// 它在跑吗（横幅）→ 它在守谁（主列表）→ 它会说什么（那句白话 + 规则抽屉）→
// 它刚才说了什么（记录抽屉）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Drawer, Dropdown, Empty, Input, InputNumber, Modal, Segmented, Space, Spin,
  Switch, Tooltip, Typography, message,
} from 'antd'
import { api } from '../../api'
import { useLayout } from '../../layout'
import { AgentLogo, ArrowDown, ArrowUp, PlusIcon, TrashIcon } from '../../icons'
import {
  FILTER_FROM, bulkPreview, counts, filterRows, fmtIdle, idleIsLong, moveRule, normalizeRules,
  nudgedRecently, quietSec, rowState, sortRows,
  type FilterMode, type KaRow, type KaRule, type KaSettings,
} from './keepalive-view'

type T = (k: string, vars?: Record<string, string | number>) => string

type ListResult = {
  settings: KaSettings
  rules: KaRule[]
  sessions: KaRow[]
  orphans: { session: string; label: string }[]
  guarded: number
  tickAt: number
  tickAgoSec?: number
  tickSec: number
  running: boolean
}

/** 列表每 5 秒重取一次——「安静了」那一列要走字。抽屉开着时暂停，免得数据在手底下跳。 */
const POLL_MS = 5000

export default function KeepalivePanel({ pluginId, enabled, t }: { pluginId: string; enabled: boolean; t: T }) {
  const { phone: isPhone } = useLayout()
  const [data, setData] = useState<ListResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')            // 正在动的会话 id
  const [mode, setMode] = useState<FilterMode>('all')
  const [q, setQ] = useState('')
  const [drawer, setDrawer] = useState<'' | 'rules' | 'history'>('')
  const [editing, setEditing] = useState<KaRow | null>(null)
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000))

  const runCmd = useCallback(
    (command: string, args: Record<string, string> = {}) =>
      api('POST', `/plugins/${encodeURIComponent(pluginId)}/run`, { command, args }),
    [pluginId],
  )

  const reload = useCallback(async () => {
    try {
      const d = await runCmd('keepalive.list')
      setData(d as ListResult)
      setErr('')
    } catch (e: any) {
      // 报错时**保留上一次的数据**：把用户看着的东西抹掉换成一句红字，是最糟的错误处理
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }, [runCmd])

  useEffect(() => { reload() }, [reload])

  const paused = !!drawer || !!editing
  useEffect(() => {
    if (paused) return
    const id = setInterval(() => { setNow(Math.floor(Date.now() / 1000)); reload() }, POLL_MS)
    return () => clearInterval(id)
  }, [paused, reload])

  const st = data?.settings
  const rows = useMemo(() => sortRows(data?.sessions || [], now), [data, now])
  const shown = useMemo(() => filterRows(rows, mode, q), [rows, mode, q])
  const tally = useMemo(() => counts(rows), [rows])

  const act = async (session: string, run: () => Promise<any>, ok?: string) => {
    setBusy(session)
    try {
      await run()
      if (ok) message.success(ok)
      await reload()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy('')
    }
  }

  const toggle = (r: KaRow, on: boolean) =>
    act(r.session, () => runCmd(on ? 'keepalive.on' : 'keepalive.off', { session: r.session }))

  const nudge = (r: KaRow) =>
    act(r.session, () => runCmd('keepalive.ping', { session: r.session }), t('ka.nudged', { name: r.label }))

  const saveSettings = async (patch: Record<string, string>) => {
    try {
      await runCmd('keepalive.settings', patch)
      await reload()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const bulk = (on: boolean, agentOnly: boolean) => {
    const { willGuard, skipped } = bulkPreview(rows, agentOnly)
    Modal.confirm({
      title: on ? t('ka.bulkOnTitle') : t('ka.bulkOffTitle'),
      // 确认文案说的是**结果**，不是「你确定吗」——用户要确认的是这句话
      content: on
        ? t('ka.bulkOnBody', { n: willGuard, skipped, min: st?.idleMin || 10 })
        : t('ka.bulkOffBody', { n: data?.guarded || 0 }),
      okText: on ? t('ka.bulkOnOk') : t('ka.bulkOffOk'),
      cancelText: t('ka.cancel'),
      onOk: () => act('', () => runCmd('keepalive.all', { on: String(on), agentOnly: String(agentOnly) })),
    })
  }

  if (loading) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      {err && <Alert type="error" showIcon message={err} />}

      <Banner data={data} enabled={enabled} t={t}
        onRules={() => setDrawer('rules')} onHistory={() => setDrawer('history')}
        onBulk={bulk} hasRows={rows.length > 0} />

      {st && <SentenceBar st={st} t={t} disabled={!enabled} onSave={saveSettings} />}

      {rows.length > FILTER_FROM && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Segmented size="small" value={mode} onChange={(v) => setMode(v as FilterMode)}
            options={[
              { value: 'all', label: `${t('ka.filterAll')} ${tally.all}` },
              { value: 'guarded', label: `${t('ka.filterGuarded')} ${tally.guarded}` },
              { value: 'agent', label: `${t('ka.filterAgent')} ${tally.agent}` },
            ]} />
          <span style={{ flex: 1 }} />
          <Input allowClear size="small" style={{ maxWidth: 240 }} value={q}
            onChange={(e) => setQ(e.target.value)} placeholder={t('ka.searchPlaceholder')} />
        </div>
      )}

      {shown.length === 0
        ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t(rows.length ? 'ka.noMatch' : 'ka.noSessions')} />
        : isPhone
          ? <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {shown.map((r) => (
                <GuardCard key={r.session} r={r} now={now} st={st} t={t} enabled={enabled}
                  busy={busy === r.session} onToggle={toggle} onNudge={nudge} onEdit={setEditing} />
              ))}
            </div>
          : <div className="tt-ka">
              <div className="tt-ka-head">
                <span />
                <span>{t('ka.colSession')}</span>
                <span className="num">{t('ka.colQuiet')}</span>
                <span>{t('ka.colGuard')}</span>
                <span className="ops">{t('ka.colOps')}</span>
              </div>
              {shown.map((r) => (
                <GuardRow key={r.session} r={r} now={now} st={st} t={t} enabled={enabled}
                  busy={busy === r.session} onToggle={toggle} onNudge={nudge} onEdit={setEditing} />
              ))}
            </div>}

      {!!data?.orphans?.length && (
        <Alert type="info" showIcon message={t('ka.orphans', { n: data.orphans.length })}
          description={data.orphans.map((o) => o.label).join('、')} />
      )}

      <RulesDrawer open={drawer === 'rules'} rules={data?.rules || []} rows={rows} t={t} isPhone={isPhone}
        runCmd={runCmd} onClose={() => setDrawer('')} onSaved={reload} />
      <HistoryDrawer open={drawer === 'history'} t={t} isPhone={isPhone} runCmd={runCmd}
        onClose={() => setDrawer('')} />
      <GuardDrawer row={editing} st={st} t={t} isPhone={isPhone} runCmd={runCmd}
        onClose={() => setEditing(null)} onSaved={reload} />
    </Space>
  )
}

// ── 横幅：这一页的诚实性担保 ──
//
// 它不说「已启用」（那只说明配置存在），它说「12 秒前巡检过一轮」——一个只有真的
// 在跑才写得出来的数字。这类插件最恶劣的失败是「配得好好的，但根本没在跑」。
function Banner({ data, enabled, t, onRules, onHistory, onBulk, hasRows }: {
  data: ListResult | null; enabled: boolean; t: T; hasRows: boolean
  onRules: () => void; onHistory: () => void; onBulk: (on: boolean, agentOnly: boolean) => void
}) {
  const [why, setWhy] = useState(false)
  const guarded = data?.guarded || 0
  const ago = data?.tickAgoSec
  const running = !!data?.running

  let tone: 'ok' | 'idle' | 'warn' = 'ok'
  let text = ''
  if (!enabled) {
    tone = 'warn'
    text = t('ka.bannerDisabled')
  } else if (guarded === 0) {
    tone = 'idle'
    text = t('ka.bannerIdle')
  } else if (!running) {
    tone = 'warn'
    text = ago == null ? t('ka.bannerNeverTicked', { n: guarded }) : t('ka.bannerStale', { n: guarded, ago: fmtIdle(ago) })
  } else {
    text = t('ka.bannerOk', { n: guarded, ago: fmtIdle(ago || 0), tick: data?.tickSec || 30 })
  }

  const actions = [
    { key: 'agent', label: t('ka.bulkAgentOnly'), onClick: () => onBulk(true, true) },
    { key: 'any', label: t('ka.bulkAny'), onClick: () => onBulk(true, false) },
    { type: 'divider' as const, key: 'd' },
    { key: 'off', label: t('ka.bulkOff'), onClick: () => onBulk(false, true) },
    // 灰的、写着「不提供」：明着告诉你没有「以后新建的自动守护」这回事——
    // 每一条守护都必须有人亲手打开过
    { key: 'auto', disabled: true, label: t('ka.bulkAutoNever') },
  ]

  return (
    <div className={`tt-ka-banner ${tone}`}>
      <i className="dot" aria-hidden />
      <span className="txt">{text}</span>
      <span className="sp" />
      {tone === 'warn' && enabled && guarded > 0 && (
        <button type="button" className="tt-act sm" onClick={() => setWhy(true)}>{t('ka.whyStale')}</button>
      )}
      <button type="button" className="tt-act sm" onClick={onHistory}>{t('ka.history')}</button>
      <button type="button" className="tt-act sm" onClick={onRules}>{t('ka.rules')}</button>
      <Dropdown menu={{ items: actions }} disabled={!enabled || !hasRows} trigger={['click']}>
        <button type="button" className="tt-act sm" disabled={!enabled || !hasRows}>{t('ka.bulk')}</button>
      </Dropdown>

      <Modal open={why} onCancel={() => setWhy(false)} footer={null} title={t('ka.whyStale')} width={520}>
        {/* 不是一句「请检查 plugind」：按顺序给三条可核对的事实，再给一条可直接粘的命令 */}
        <Typography.Paragraph style={{ whiteSpace: 'pre-line', marginBottom: 12 }}>
          {t('ka.whyBody')}
        </Typography.Paragraph>
        <Typography.Text code copyable style={{ fontSize: 12 }}>ttmux plugin run keepalive.tick</Typography.Text>
      </Modal>
    </div>
  )
}

// ── 全局默认：一句白话 + 一块守护语 ──
//
// 三个**数字**嵌在句子里（一张有四个 label 的表单说不出它们之间的关系，而这句话说得出）；
// **守护语单独成块**——它是一整句甚至几句话，硬塞进句子里只会挤成一坨。
function SentenceBar({ st, t, disabled, onSave }: {
  st: KaSettings; t: T; disabled: boolean; onSave: (patch: Record<string, string>) => Promise<void>
}) {
  return (
    <div className="tt-ka-rule">
      <div className="say">
        {t('ka.sentA')}
        <InlineNum value={st.idleMin} min={1} max={1440} disabled={disabled} unit={t('ka.unitMin')}
          hint={t('ka.rangeMin')} onCommit={(v) => onSave({ idleMin: String(v) })} />
        {t('ka.sentB')}
        <InlineNum value={st.everyMin} min={1} max={1440} disabled={disabled} unit={t('ka.unitMin')}
          hint={t('ka.rangeMin')} onCommit={(v) => onSave({ everyMin: String(v) })} />
        {t('ka.sentC')}
        <InlineNum value={st.maxQuiet} min={0} max={50} disabled={disabled} unit={t('ka.unitTimes')}
          hint={t('ka.rangeQuiet')} onCommit={(v) => onSave({ maxQuiet: String(v) })} />
        {t('ka.sentD')}
      </div>
      <PromptField label={t('ka.promptLabel')} value={st.prompt} max={st.maxPromptLen} t={t}
        disabled={disabled} onCommit={(v) => onSave({ prompt: v })} />
    </div>
  )
}

/** 句子里就地可改的一个数。点它变输入框，**句子结构一个字不动**——整句换成表单，
 *  上下文一瞬间就没了，人还得重新读一遍才知道自己在改哪个。 */
function InlineNum({ value, min, max, unit, hint, disabled, onCommit }: {
  value: number; min: number; max: number; unit: string; hint: string; disabled: boolean
  onCommit: (v: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<number | null>(value)
  const bad = draft == null || draft < min || draft > max

  const commit = () => {
    setEditing(false)
    if (!bad && draft !== value) onCommit(draft as number)
    else setDraft(value)
  }
  if (!editing) {
    return (
      <button type="button" className="num" disabled={disabled}
        onClick={() => { setDraft(value); setEditing(true) }}>{value} {unit}</button>
    )
  }
  return (
    <span className="numedit">
      <InputNumber autoFocus size="small" value={draft} status={bad ? 'error' : undefined}
        onChange={(v) => setDraft(v as number)}
        onBlur={commit}
        onPressEnter={commit}
        onKeyDown={(e) => { if (e.key === 'Escape') { setDraft(value); setEditing(false) } }} />
      <span className="unit">{unit}</span>
      {/* 越界当场说清区间，**不静默夹值**——静默夹值会让人以为自己设成了 0 而实际跑的是 10 */}
      {bad && <span className="bad">{hint}</span>}
    </span>
  )
}

/** 守护语输入：多行、带字数、带预设胶囊。失焦即存。 */
function PromptField({ label, value, max, t, disabled, onCommit, placeholder }: {
  label: string; value: string; max: number; t: T; disabled: boolean
  onCommit: (v: string) => void; placeholder?: string
}) {
  const [draft, setDraft] = useState(value)
  const dirty = useRef(false)
  useEffect(() => { if (!dirty.current) setDraft(value) }, [value])

  const presets: { key: string; text: string }[] = [
    { key: 'done', text: t('ka.preset.done') },
    { key: 'go', text: t('ka.preset.go') },
    { key: 'resume', text: t('ka.preset.resume') },
    { key: 'review', text: t('ka.preset.review') },
  ]
  const over = [...draft].length > max
  const commit = () => {
    dirty.current = false
    if (over) { setDraft(value); return }
    if (draft.trim() !== value.trim()) onCommit(draft.trim())
  }
  return (
    <div className="tt-ka-prompt">
      <span className="lb">{label}</span>
      <div className="box">
        <Input.TextArea value={draft} disabled={disabled} autoSize={{ minRows: 1, maxRows: 4 }}
          status={over ? 'error' : undefined} placeholder={placeholder}
          onChange={(e) => { dirty.current = true; setDraft(e.target.value) }}
          onBlur={commit} />
        <div className="chips">
          {presets.map((p) => (
            <button key={p.key} type="button" disabled={disabled}
              className={`tt-act sm${p.text === draft.trim() ? ' on' : ''}`}
              onClick={() => { dirty.current = true; setDraft(p.text); onCommit(p.text) }}>
              {t(`ka.presetName.${p.key}`)}
            </button>
          ))}
        </div>
      </div>
      <span className={`count${over ? ' bad' : ''}`}>{[...draft].length} / {max}</span>
    </div>
  )
}

// ── 一行 ──
function useRowBits(r: KaRow, now: number, st: KaSettings | undefined, t: T) {
  const state = rowState(r)
  const g = r.guard
  const long = idleIsLong(r, now, st?.idleMin || 10)
  const fresh = nudgedRecently(g, now)
  let line = t('ka.stateOff')
  if (state === 'guarded') {
    line = g!.sends === 0 ? t('ka.stateNeverNudged')
      : fresh ? t('ka.stateJustNudged')
        : t('ka.stateNudged', { ago: fmtIdle(now - g!.lastSent), n: g!.sends })
  } else if (state === 'stopped') {
    line = t('ka.stateStopped', { n: g!.maxQuiet })
  } else if (!r.agent) {
    line = t('ka.stateOffNotAgent')
  }
  return { state, g, long, fresh, line }
}

function openSession(r: KaRow) {
  return `#/w?terms=${encodeURIComponent(r.session)}&active=${encodeURIComponent(r.session)}`
}

function GuardRow({ r, now, st, t, enabled, busy, onToggle, onNudge, onEdit }: {
  r: KaRow; now: number; st?: KaSettings; t: T; enabled: boolean; busy: boolean
  onToggle: (r: KaRow, on: boolean) => void; onNudge: (r: KaRow) => void; onEdit: (r: KaRow) => void
}) {
  const { state, g, long, fresh, line } = useRowBits(r, now, st, t)
  return (
    <div className={`tt-ka-row ${state}`}>
      <span className="mk">{r.agent ? <AgentLogo kind={r.agent as 'claude' | 'codex'} size={14} /> : null}</span>
      <span className="name">
        {/* 会话名是真链接（它真的导航到工作区），不是 a onClick */}
        <a href={openSession(r)}>{r.label}</a>
        <small title={r.dir}>{r.dir || r.session}</small>
      </span>
      <span className={`quiet${long ? ' long' : ''}`}>{fmtIdle(quietSec(r, now))}</span>
      <span className="guard">
        <Switch size="small" checked={state === 'guarded'} loading={busy} disabled={!enabled}
          aria-label={t('ka.colGuard')} onChange={(on) => onToggle(r, on)} />
        <span className={`st${state === 'stopped' ? ' bad' : fresh ? ' ok' : ''}`}>{line}</span>
      </span>
      <span className="ops">
        {state === 'stopped'
          ? <button type="button" className="tt-act ok" disabled={!enabled || busy}
              onClick={() => onToggle(r, true)}>{t('ka.retry')}</button>
          : <button type="button" className="tt-act" disabled={!enabled || busy}
              onClick={() => onNudge(r)}>{t('ka.nudge')}</button>}
        {!!g && (
          <button type="button" className="tt-act" disabled={!enabled}
            onClick={() => onEdit(r)}>{t('ka.perSession')}</button>
        )}
      </span>
    </div>
  )
}

/** 手机档换卡片：桌面那五列合计 ≥808px，360 的屏必然横滚。 */
function GuardCard({ r, now, st, t, enabled, busy, onToggle, onNudge, onEdit }: {
  r: KaRow; now: number; st?: KaSettings; t: T; enabled: boolean; busy: boolean
  onToggle: (r: KaRow, on: boolean) => void; onNudge: (r: KaRow) => void; onEdit: (r: KaRow) => void
}) {
  const { state, g, long, line } = useRowBits(r, now, st, t)
  return (
    <div className={`tt-ka-card ${state}`}>
      <div className="hd">
        {r.agent && <AgentLogo kind={r.agent as 'claude' | 'codex'} size={14} />}
        <b>{r.label}</b>
        <Switch size="small" checked={state === 'guarded'} loading={busy} disabled={!enabled}
          aria-label={t('ka.colGuard')} onChange={(on) => onToggle(r, on)} />
      </div>
      <div className="m">
        <span className={long ? 'long' : ''}>{t('ka.quietFor', { d: fmtIdle(quietSec(r, now)) })}</span>
        <span className="sep">·</span>
        <span>{line.replace('\n', ' · ')}</span>
      </div>
      <div className="ops">
        {state === 'stopped'
          ? <button type="button" className="tt-act ok" disabled={!enabled || busy}
              onClick={() => onToggle(r, true)}>{t('ka.retry')}</button>
          : <button type="button" className="tt-act" disabled={!enabled || busy}
              onClick={() => onNudge(r)}>{t('ka.nudge')}</button>}
        {!!g && <button type="button" className="tt-act" disabled={!enabled}
          onClick={() => onEdit(r)}>{t('ka.perSession')}</button>}
        <a className="tt-act" href={openSession(r)}>{t('ka.openSession')}</a>
      </div>
    </div>
  )
}

// ── 抽屉 A：守护语规则 ──
function RulesDrawer({ open, rules, rows, t, isPhone, runCmd, onClose, onSaved }: {
  open: boolean; rules: KaRule[]; rows: KaRow[]; t: T; isPhone: boolean
  runCmd: (c: string, a?: Record<string, string>) => Promise<any>
  onClose: () => void; onSaved: () => Promise<void>
}) {
  const [draft, setDraft] = useState<KaRule[]>(rules)
  const [saving, setSaving] = useState(false)
  const [tried, setTried] = useState<{ name: string; prompt: string; rule: number } | null>(null)
  useEffect(() => { if (open) { setDraft(rules); setTried(null) } }, [open, rules])

  const patch = (i: number, p: Partial<KaRule>) =>
    setDraft((d) => d.map((r, j) => (j === i ? { ...r, ...p } : r)))

  const save = async () => {
    setSaving(true)
    try {
      await runCmd('keepalive.rules', { rules: JSON.stringify(normalizeRules(draft)) })
      message.success(t('ka.rulesSaved'))
      await onSaved()
      onClose()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  // 「试一下」是这个抽屉里最要紧的按钮：没有它，填完一条匹配串只能等下一次真出事
  // 才知道对不对——而那正是最不想试错的时刻。
  //
  // 把**草稿**随调用一起传过去（dryrun 不落库、不发送）：试一下不该有副作用，
  // 更不该悄悄把还没决定要不要的规则存成正式的。
  const tryOn = async (r: KaRow) => {
    try {
      const res = await runCmd('keepalive.dryrun', {
        session: r.session, rules: JSON.stringify(normalizeRules(draft)),
      })
      setTried({ name: r.label, prompt: res?.prompt || '', rule: res?.rule ?? -1 })
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const last = draft.length - 1
  return (
    <Drawer open={open} onClose={onClose} width={isPhone ? '100%' : 520} destroyOnClose
      title={t('ka.rules')}
      extra={<Space size={6}>
        <Button size="small" icon={<PlusIcon size={12} />}
          onClick={() => setDraft((d) => [...d.slice(0, -1), { match: '', atNth: 0, prompt: '', enabled: true, fallback: false }, d[d.length - 1]])}>
          {t('ka.ruleAdd')}
        </Button>
        <Button size="small" type="primary" loading={saving} onClick={save}>{t('ka.save')}</Button>
      </Space>}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>{t('ka.rulesIntro')}</Typography.Paragraph>
      <div className="tt-ka-rules">
        {draft.map((r, i) => (
          <div key={i} className={`rr${r.fallback ? ' fb' : ''}`}>
            <span className="gr">
              {!r.fallback && (
                <Space direction="vertical" size={0}>
                  <button type="button" className="tt-act xs" aria-label={t('ka.ruleUp')} disabled={i === 0}
                    onClick={() => setDraft((d) => moveRule(d, i, i - 1))}><ArrowUp size={11} /></button>
                  <button type="button" className="tt-act xs" aria-label={t('ka.ruleDown')} disabled={i >= last - 1}
                    onClick={() => setDraft((d) => moveRule(d, i, i + 1))}><ArrowDown size={11} /></button>
                </Space>
              )}
            </span>
            <div className="body">
              {/* 三种条件长得不一样，别都渲染成一个空匹配框：
                  兜底条、按次数触发的条（屏幕上没有任何字样能表示「它该回头检查了」），
                  以及普通的按屏幕匹配。 */}
              {r.fallback
                ? <div className="fbnote">{t('ka.ruleFallbackNote')}</div>
                : r.atNth > 0
                  ? <div className="fbnote">{t('ka.ruleAtNth', { n: r.atNth })}</div>
                  : (
                    <Input size="small" value={r.match} placeholder={t('ka.ruleMatchPlaceholder')}
                      onChange={(e) => patch(i, { match: e.target.value })} />
                  )}
              <Input.TextArea size="small" value={r.prompt} autoSize={{ minRows: 1, maxRows: 3 }}
                placeholder={t('ka.rulePromptPlaceholder')}
                onChange={(e) => patch(i, { prompt: e.target.value })} />
            </div>
            <span className="tail">
              <Switch size="small" checked={r.enabled} disabled={r.fallback}
                aria-label={t('ka.ruleEnabled')} onChange={(v) => patch(i, { enabled: v })} />
              {!r.fallback && (
                <button type="button" className="tt-act danger xs" aria-label={t('ka.ruleRemove')}
                  onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}><TrashIcon size={12} /></button>
              )}
            </span>
          </div>
        ))}
      </div>

      {tried && (
        <Alert type="success" showIcon style={{ marginTop: 12 }}
          message={t('ka.tryHit', { name: tried.name, rule: tried.rule < 0 ? t('ka.tryFallback') : String(tried.rule + 1) })}
          description={tried.prompt} />
      )}
      <div style={{ marginTop: 12 }}>
        <Dropdown trigger={['click']} disabled={!rows.length}
          menu={{ items: rows.slice(0, 20).map((r) => ({ key: r.session, label: r.label, onClick: () => tryOn(r) })) }}>
          <Button size="small" disabled={!rows.length}>{t('ka.tryOn')}</Button>
        </Dropdown>
      </div>
    </Drawer>
  )
}

// ── 抽屉 B：单独设置 ──
function GuardDrawer({ row, st, t, isPhone, runCmd, onClose, onSaved }: {
  row: KaRow | null; st?: KaSettings; t: T; isPhone: boolean
  runCmd: (c: string, a?: Record<string, string>) => Promise<any>
  onClose: () => void; onSaved: () => Promise<void>
}) {
  const g = row?.guard
  const save = async (patch: Record<string, string>) => {
    if (!row) return
    try {
      await runCmd('keepalive.on', { session: row.session, ...patch })
      await onSaved()
    } catch (e: any) {
      message.error(e.message)
    }
  }
  return (
    <Drawer open={!!row} onClose={onClose} width={isPhone ? '100%' : 520} destroyOnClose
      title={row ? t('ka.perSessionTitle', { name: row.label }) : ''}>
      {g && st && (
        <>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            {t('ka.perSessionIntro', { min: st.idleMin, every: st.everyMin })}
          </Typography.Paragraph>
          {/* 把默认值直接印在占位符里，而不是让人回主页面去对 */}
          <PromptField label={t('ka.promptLabel')} value={g.prompt || ''} max={st.maxPromptLen} t={t}
            disabled={false} placeholder={t('ka.followGlobal', { v: st.prompt })}
            onCommit={(v) => save({ prompt: v })} />
          <div className="tt-ka-frow">
            <span className="lb">{t('ka.fieldIdle')}</span>
            <InputNumber size="small" min={1} max={1440} value={g.idleMin || null}
              placeholder={t('ka.followGlobal', { v: String(st.idleMin) })}
              onBlur={(e) => save({ idleMin: (e.target as HTMLInputElement).value || '0' })} />
          </div>
          <div className="tt-ka-frow">
            <span className="lb">{t('ka.fieldEvery')}</span>
            <InputNumber size="small" min={1} max={1440} value={g.everyMin || null}
              placeholder={t('ka.followGlobal', { v: String(st.everyMin) })}
              onBlur={(e) => save({ everyMin: (e.target as HTMLInputElement).value || '0' })} />
          </div>
          {/* 这一块是抽屉的隐藏价值：它把「这条守护此刻处在什么位置」摊开讲——
              还差几次就要被自动停掉。主列表塞不下，但那恰恰是用户最想知道的。 */}
          <div className="tt-ka-frow">
            <span className="lb">{t('ka.fieldThisOne')}</span>
            <span>
              {t('ka.guardStats', { n: g.sends, ago: g.lastSent ? fmtIdle(Math.floor(Date.now() / 1000) - g.lastSent) : '—', streak: g.streak })}
              {g.maxQuiet > 0 && g.streak > 0 && (
                <Typography.Paragraph type="secondary" style={{ fontSize: 11, margin: '3px 0 0' }}>
                  {t('ka.guardStopsIn', { n: Math.max(0, g.maxQuiet - g.streak) })}
                </Typography.Paragraph>
              )}
            </span>
          </div>
        </>
      )}
    </Drawer>
  )
}

// ── 抽屉 C：发送记录 ──
type SendRec = {
  at: number; session: string; label: string; prompt: string; trigger: string
  rule: number; nth?: number; quietSec?: number; stopped?: boolean; error?: string
}

function HistoryDrawer({ open, t, isPhone, runCmd, onClose }: {
  open: boolean; t: T; isPhone: boolean
  runCmd: (c: string, a?: Record<string, string>) => Promise<any>
  onClose: () => void
}) {
  const [rows, setRows] = useState<SendRec[]>([])
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!open) return
    let stop = false
    setLoading(true)
    runCmd('keepalive.history', { limit: '50' })
      .then((d) => { if (!stop) setRows((d?.sends as SendRec[]) || []) })
      .catch((e) => message.error(e.message))
      .finally(() => { if (!stop) setLoading(false) })
    return () => { stop = true }
  }, [open, runCmd])

  const now = Math.floor(Date.now() / 1000)
  return (
    <Drawer open={open} onClose={onClose} width={isPhone ? '100%' : 520} destroyOnClose title={t('ka.history')}>
      {loading
        ? <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>
        : rows.length === 0
          ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('ka.historyEmpty')} />
          : (
            <div className="tt-ka-hist">
              {rows.map((r) => (
                <div key={`${r.at}-${r.session}`} className={`h${r.stopped || r.error ? ' bad' : ''}`}>
                  <span className="d" aria-hidden />
                  <div className="main">
                    <div className="hd">
                      <b>{fmtIdle(now - r.at)}</b>
                      <span>{r.label}</span>
                      <span>{t(r.trigger === 'manual' ? 'ka.trigManual' : 'ka.trigWatch')}</span>
                      {!!r.quietSec && <span>{t('ka.quietThen', { d: fmtIdle(r.quietSec) })}</span>}
                      {r.rule >= 0 && <Tooltip title={t('ka.ruleHitTip')}><span className="tag">{t('ka.ruleHit', { n: r.rule + 1 })}</span></Tooltip>}
                      {r.stopped && <span className="tag bad">{t('ka.stopped')}</span>}
                    </div>
                    <div className="msg">{r.prompt}</div>
                    {r.error && <div className="err">{r.error}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
    </Drawer>
  )
}
