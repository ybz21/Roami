// 定时任务面板(roam.cron 插件的宿主侧面板):管理「什么时候 / 干什么 / 由谁干」
// 的定时任务表——增删改、启停、立即触发、改 prompt,全部走插件命令
// (cron.add / list / remove / enable / disable / run)经 backend 薄封装 REST。
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Alert, Button, Drawer, Empty, Form, Input, Modal, Popconfirm, Select, Space, Spin, Switch, Table, Tag,
  Typography, message,
} from 'antd'
import { api } from '../../api'
import { useLayout } from '../../layout'
import CronEditor from './CronEditor'
import { PlusIcon } from '../../icons'
import { AgentLogo } from '../../icons'
import { agentName, isAgentKind } from '../../agent-kind'
import { discoverAgents, type RegisteredAgent } from '../../agent-registry'

// 一条任务的原始配置 + 运行态(与 Go 端 jobView 对齐)。
type Action = 'agent' | 'exec'

type Job = {
  name: string
  schedule: string
  action: Action
  enabled: boolean
  runs: number
  cron?: string
  provider?: string
  prompt?: string
  workdir?: string
  interactive?: boolean
  command?: string
  notify?: boolean
  artifact?: string
  nextRunAt?: string
  lastRunAt?: string
}

// 一次触发的记录（与 Go 端 runsCmd 对齐）。「已触发 3」这个数字答不出的东西都在这儿。
type Run = {
  name: string
  at: number
  atStr: string
  trigger: 'schedule' | 'manual'
  action: Action
  ok: boolean
  error?: string
  session?: string
  interactive?: boolean
  exit?: number
  output?: string
  doneAt?: number
  tookSec?: number
  artifact?: string
  artifactSize?: number
}

type FormValues = {
  name: string
  cron: string
  action: Action
  provider: string
  prompt: string
  workdir: string
  interactive: boolean
  command: string
  notify: boolean
  artifact: string
}

type T = (k: string, vars?: Record<string, string | number>) => string

export default function CronPanel({ pluginId, enabled, t }: { pluginId: string; enabled: boolean; t: T }) {
  const { phone: isPhone } = useLayout()
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Job | null>(null) // 非空=编辑;{} 视图当新增用 open 区分
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState('') // 正在执行动作的任务名(禁用其行内按钮)
  const [runsOf, setRunsOf] = useState<Job | null>(null) // 正在看谁的执行记录

  // 调一个 cron 命令:command 传短名(cron.xxx),args 全为字符串。
  const runCmd = useCallback(async (command: string, args: Record<string, string> = {}) => {
    return api('POST', `/plugins/${encodeURIComponent(pluginId)}/run`, { command, args })
  }, [pluginId])

  const reload = useCallback(async () => {
    try {
      const data = await runCmd('cron.list')
      setJobs((data?.jobs as Job[]) || [])
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [runCmd])
  useEffect(() => { reload() }, [reload])

  const toggle = async (j: Job, on: boolean) => {
    setBusy(j.name)
    try {
      await runCmd(on ? 'cron.enable' : 'cron.disable', { name: j.name })
      await reload()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy('')
    }
  }

  const runNow = async (j: Job) => {
    setBusy(j.name)
    try {
      await runCmd('cron.run', { name: j.name })
      message.success(t('cron.firedOnce', { name: j.name }))
      await reload()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy('')
    }
  }

  const remove = async (j: Job) => {
    setBusy(j.name)
    try {
      await runCmd('cron.remove', { name: j.name })
      message.success(t('cron.removed', { name: j.name }))
      await reload()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy('')
    }
  }

  const openRuns = (j: Job) => setRunsOf(j)

  const columns = useMemo(() => [
    {
      title: t('cron.colName'), dataIndex: 'name', key: 'name',
      render: (v: string, j: Job) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{v}</Typography.Text>
          {/* 一行截断：这条摘要长得很（prompt 前 40 字），换行会把任务名那列撑成四行 */}
          <span className="tt-cron-sum" title={actionSummary(j, t)}>{actionSummary(j, t)}</span>
        </Space>
      ),
    },
    {
      title: t('cron.colSchedule'), dataIndex: 'schedule', key: 'schedule', width: 130,
      render: (v: string) => <Typography.Text code style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{v}</Typography.Text>,
    },
    {
      title: t('cron.colAction'), dataIndex: 'action', key: 'action', width: 90,
      render: (a: Action) => <Tag color={ACTION_COLOR[a]}>{t(`cron.action.${a}`)}</Tag>,
    },
    {
      title: t('cron.colNext'), dataIndex: 'nextRunAt', key: 'nextRunAt', width: 180,
      render: (v: string, j: Job) => j.enabled
        ? <span style={{ whiteSpace: 'nowrap' }}>{v || '—'}</span>
        : <Typography.Text type="secondary">{t('cron.paused')}</Typography.Text>,
    },
    {
      title: t('cron.colEnabled'), key: 'enabled', width: 70,
      render: (_: any, j: Job) => (
        <Switch size="small" checked={j.enabled} loading={busy === j.name}
          disabled={!enabled} onChange={(on) => toggle(j, on)} />
      ),
    },
    {
      title: t('cron.colOps'), key: 'ops', width: 250,
      render: (_: any, j: Job) => (
        <Space size={4}>
          <Button size="small" disabled={!enabled || busy === j.name} onClick={() => runNow(j)}>{t('cron.runNow')}</Button>
          {/* 执行记录得在操作里明摆着：藏在「已触发」那个数字后面，没人猜得到它能点 */}
          <Button size="small" disabled={!j.runs} title={t('cron.runsTitleShort')} onClick={() => openRuns(j)}>
            {t('cron.runs')} {j.runs || 0}
          </Button>
          <Button size="small" disabled={!enabled} onClick={() => { setEditing(j); setOpen(true) }}>{t('cron.edit')}</Button>
          <Popconfirm title={t('cron.removeConfirm', { name: j.name })} onConfirm={() => remove(j)}
            okText={t('cron.remove')} cancelText={t('cron.cancel')}>
            <Button size="small" danger disabled={!enabled}>{t('cron.remove')}</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ], [t, enabled, busy]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      {!enabled && <Alert type="warning" showIcon message={t('cron.enablePluginHint')} />}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Text type="secondary">{t('cron.intro')}</Typography.Text>
        <Button type="primary" disabled={!enabled} onClick={() => { setEditing(null); setOpen(true) }} icon={<PlusIcon size={13} />}>{t('cron.add')}</Button>
      </div>
      {jobs.length === 0
        ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('cron.empty')} />
        // 手机换卡片列表（13 §6）：这张表七列固定宽合计 730，360 的屏上必然横滚，
        // 而横滚表格在手机上等于「每一列都要滑到才看得见」。
        : isPhone ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {jobs.map((j) => (
              <div key={j.name} className="tt-cron-card">
                <div className="hd">
                  <b>{j.name}</b>
                  <Tag color={ACTION_COLOR[j.action]} style={{ margin: 0 }}>{t(`cron.action.${j.action}`)}</Tag>
                  <Switch size="small" checked={j.enabled} loading={busy === j.name}
                    disabled={!enabled} onChange={(on) => toggle(j, on)} />
                </div>
                <div className="sum">{actionSummary(j, t)}</div>
                <div className="meta">
                  <Typography.Text code style={{ fontSize: 12 }}>{j.schedule}</Typography.Text>
                  <span>{j.enabled ? (j.nextRunAt || '—') : t('cron.paused')}</span>
                </div>
                <div className="ops">
                  <Button size="small" disabled={!enabled || busy === j.name} onClick={() => runNow(j)}>{t('cron.runNow')}</Button>
                  <Button size="small" disabled={!j.runs} onClick={() => openRuns(j)}>{t('cron.runs')} {j.runs || 0}</Button>
                  <Button size="small" disabled={!enabled} onClick={() => { setEditing(j); setOpen(true) }}>{t('cron.edit')}</Button>
                  <Popconfirm title={t('cron.removeConfirm', { name: j.name })} onConfirm={() => remove(j)}
                    okText={t('cron.remove')} cancelText={t('cron.cancel')}>
                    <Button size="small" danger disabled={!enabled}>{t('cron.remove')}</Button>
                  </Popconfirm>
                </div>
              </div>
            ))}
          </div>
        ) : <Table<Job> size="small" rowKey="name" dataSource={jobs} columns={columns as any}
            pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 900 }} />}
      <RunsDrawer job={runsOf} t={t} isPhone={isPhone} runCmd={runCmd} onClose={() => setRunsOf(null)} />
      <JobModal open={open} job={editing} existing={jobs} t={t} pluginId={pluginId}
        onClose={() => setOpen(false)}
        onSaved={async () => { setOpen(false); await reload() }}
        submit={(args) => runCmd('cron.add', args)} />
    </Space>
  )
}

// 一句话概括「干什么」,列在任务名下方。
function actionSummary(j: Job, t: T): string {
  switch (j.action) {
    case 'agent': return `${j.provider || t('cron.providerAuto')}${j.interactive ? ` · ${t('cron.fieldInteractive')}` : ''} · ${(j.prompt || '').slice(0, 40)}`
    case 'exec': return (j.command || '').slice(0, 50)
    default: return ''
  }
}

const ACTION_COLOR: Record<string, string> = { agent: 'purple', exec: 'orange' }

// 轻量 tooltip(避免多引一个组件;antd Tooltip 用 title;此处用 span title 兜底)
function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return <span title={label}>{children}</span>
}

// 工作目录：在项目里挑，而不是背路径。
//
// 「定时任务在哪跑」十有八九就是某个项目的目录——原来这里只有一个空输入框，
// 等于每次都要自己去别处把绝对路径抄过来。项目清单直接读 /api/projects
// （「临时」那种目录本身就在项目里，不用另立一档）；剩下的情况留「自定义路径」。
const CUSTOM = '__custom__'

function WorkdirPicker({ t, value, onChange }: { t: T; value: string; onChange: (v: string) => void }) {
  const [projects, setProjects] = useState<{ name: string; dir: string }[]>([])
  const [loading, setLoading] = useState(true)
  const [custom, setCustom] = useState(false)

  // /projects 这条要两秒上下（它顺带算了每个项目的 worktree 状态），
  // 期间下拉里只有「默认」和「自定义」两项——不给个 loading，看着就像项目丢了
  useEffect(() => {
    let stop = false
    api('GET', '/projects')
      .then((r) => {
        const list = (r?.data?.projects || r?.projects || []) as any[]
        if (!stop) setProjects(list.map((p) => ({ name: p.name, dir: p.dir })).filter((p) => p.dir))
      })
      .catch(() => {})
      .finally(() => { if (!stop) setLoading(false) })
    return () => { stop = true }
  }, [])

  // 编辑既有任务：路径不在项目清单里才算自定义。**必须等清单到齐再判**——
  // 清单还没回来时人人都「不在清单里」，那一判会把项目目录也认成自定义路径，
  // 而且此后再不翻身（这一版第一次就是这么错的）。只判一次，之后交给用户自己选。
  const judged = useRef(false)
  useEffect(() => {
    if (loading || judged.current) return
    judged.current = true
    setCustom(!!value && !projects.some((p) => p.dir === value))
  }, [loading, value, projects])

  const options = [
    { value: '', label: t('cron.workdirDefault') },
    ...projects.map((p) => ({ value: p.dir, label: `${p.name} · ${p.dir}` })),
    { value: CUSTOM, label: t('cron.workdirCustom') },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={6}>
      <Select
        value={custom ? CUSTOM : value || ''}
        options={options}
        loading={loading}
        onChange={(v) => {
          if (v === CUSTOM) { setCustom(true); return }
          setCustom(false)
          onChange(v)
        }}
      />
      {custom && (
        <Input placeholder={t('cron.workdirPlaceholder')} value={value}
          onChange={(e) => onChange(e.target.value)} />
      )}
    </Space>
  )
}

// ── 执行记录 ──
//
// 定时任务最要紧的问题不是「排期对不对」，而是**上次到底跑了没、跑成什么样**。
// 表上原来只有一个「已触发 3」，点不开——出了事只能去翻 tmux 里那个会话还在不在。
function RunsDrawer({ job, t, isPhone, runCmd, onClose }: {
  job: Job | null; t: T; isPhone: boolean
  runCmd: (command: string, args?: Record<string, string>) => Promise<any>
  onClose: () => void
}) {
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(false)
  const [live, setLive] = useState<Set<string>>(new Set()) // 还活着的会话名
  const [openOut, setOpenOut] = useState<Set<number>>(new Set()) // 展开了输出的那几条

  useEffect(() => {
    if (!job) { setRuns([]); setOpenOut(new Set()); return }
    let stop = false
    setLoading(true)
    ;(async () => {
      try {
        const data = await runCmd('cron.runs', { name: job.name, limit: '30' })
        if (!stop) setRuns((data?.runs as Run[]) || [])
        // 会话可能早就退了：拿一次在册名单，退了的那条就不给「打开会话」的入口，
        // 免得点进去是个 4404
        const ss = await api('GET', '/sessions').catch(() => null)
        const list: any[] = Array.isArray(ss) ? ss : (ss?.data || [])
        if (!stop) setLive(new Set(list.map((x: any) => x?.name).filter(Boolean)))
      } catch (e: any) {
        message.error(e.message)
      } finally {
        if (!stop) setLoading(false)
      }
    })()
    return () => { stop = true }
  }, [job, runCmd])

  const openSession = (name: string) => {
    // 会话在工作区里开，不在插件页：直接换路由，把它设成当前标签
    location.hash = `#/w?terms=${encodeURIComponent(name)}&active=${encodeURIComponent(name)}`
  }
  const toggleOut = (at: number) => setOpenOut((prev) => {
    const next = new Set(prev)
    next.has(at) ? next.delete(at) : next.add(at)
    return next
  })

  const failed = runs.filter((r) => !r.ok).length

  return (
    <Drawer open={!!job} onClose={onClose} width={isPhone ? '100%' : 520} destroyOnClose
      title={job ? t('cron.runsTitle', { name: job.name }) : ''}>
      {loading
        ? <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>
        : runs.length === 0
          ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('cron.runsEmpty')} />
          : (
            <>
              {/* 一句话交代这几条是什么：几次、错了几次。失败数是这张抽屉里唯一的红 */}
              <div className="tt-runs-sum">
                {t('cron.runsCount', { n: runs.length })}
                {failed > 0 && <b className="bad">{t('cron.runsFailed', { n: failed })}</b>}
              </div>
              <div className="tt-runs">
                {runs.map((r) => {
                  const out = (r.output || '').trimEnd()
                  const lines = out ? out.split('\n').length : 0
                  const on = openOut.has(r.at)
                  return (
                    <div key={r.at} className={`run${r.ok ? '' : ' bad'}`}>
                      <span className="dot" aria-hidden />
                      <div className="main">
                        <div className="hd">
                          {/* 相对时间在前：看记录问的是「最近那次怎么样」，绝对时刻挂在 title 上 */}
                          <b title={r.atStr}>{relTime(r.at, t)}</b>
                          <span className="trig">{t(`cron.trigger.${r.trigger}`)}</span>
                          {r.exit != null && (
                            <span className={`ex${r.exit === 0 ? '' : ' bad'}`}>exit {r.exit}</span>
                          )}
                          {/* 「失败」只在没有别的东西替它说话时才写：exit 码和错误行都已经是红的 */}
                          {!r.ok && r.exit == null && !r.error && <span className="ex bad">{t('cron.runFail')}</span>}
                          {r.tookSec != null && <span className="trig">{t('cron.took', { s: fmtDur(r.tookSec, t) })}</span>}
                        </div>
                        {r.error && <div className="err">{r.error}</div>}
                        {/* 产物：人要的是「结果在哪」，路径写全，没写出来就直说 */}
                        {r.artifact && (
                          <div className="art" title={r.artifact}>
                            <code>{r.artifact}</code>
                            <span className="gone">
                              {r.artifactSize != null && r.artifactSize >= 0
                                ? fmtSize(r.artifactSize)
                                : t('cron.artifactMissing')}
                            </span>
                          </div>
                        )}
                        {r.session && (
                          <div className="sess">
                            <code>{r.session}</code>
                            {live.has(r.session)
                              ? <button type="button" className="tt-act" onClick={() => openSession(r.session!)}>
                                  {t('cron.openSession')}
                                </button>
                              : <span className="gone">{t('cron.sessionGone')}</span>}
                          </div>
                        )}
                        {/* 输出默认收着：三条记录各摊一个 200px 的黑框，重点就没了 */}
                        {out && (
                          <>
                            <button type="button" className="tt-act sm" aria-expanded={on} onClick={() => toggleOut(r.at)}>
                              {on ? t('cron.hideOutput') : t('cron.showOutput', { n: lines })}
                            </button>
                            {on && <pre className="out">{out}</pre>}
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )}
    </Drawer>
  )
}

/** 用时：秒 → 「2 小时 5 分钟」，和插件侧那份口径一致 */
function fmtDur(sec: number, t: T): string {
  if (sec < 60) return t('cron.durSec', { n: sec })
  if (sec < 3600) return t('cron.durMin', { n: Math.floor(sec / 60) })
  return t('cron.durHour', { h: Math.floor(sec / 3600), m: Math.floor((sec % 3600) / 60) })
}

/** 产物大小 */
function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/** 「3 分钟前」。抽屉比树行宽，放得下整句话，比 `3m` 好读 */
function relTime(sec: number, t: T): string {
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec))
  if (d < 60) return t('time.justNow')
  if (d < 3600) return t('time.minutesAgo', { count: Math.floor(d / 60) })
  if (d < 86400) return t('time.hoursAgo', { count: Math.floor(d / 3600) })
  return t('time.daysAgo', { count: Math.floor(d / 86400) })
}

// ── 新增/编辑弹窗 ──
function JobModal({ open, job, existing, t, pluginId, onClose, onSaved, submit }: {
  open: boolean; job: Job | null; existing: Job[]; t: T; pluginId: string
  onClose: () => void; onSaved: () => void
  submit: (args: Record<string, string>) => Promise<any>
}) {
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)
  const [agents, setAgents] = useState<RegisteredAgent[]>([])
  const [agentsLoading, setAgentsLoading] = useState(false)
  const [agentsError, setAgentsError] = useState(false)
  const isEdit = !!job

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setAgentsLoading(true)
    setAgentsError(false)
    discoverAgents()
      .then((rows) => { if (!cancelled) setAgents(rows) })
      .catch(() => { if (!cancelled) setAgentsError(true) })
      .finally(() => { if (!cancelled) setAgentsLoading(false) })
    return () => { cancelled = true }
  }, [open])

  useEffect(() => {
    if (!open) return
    if (job) {
      form.setFieldsValue({
        name: job.name,
        cron: job.cron || '',
        action: job.action,
        provider: job.provider || '', prompt: job.prompt || '', workdir: job.workdir || '',
        interactive: !!job.interactive,
        notify: !!job.notify, artifact: job.artifact || '',
        command: job.command || '',
      })
    } else {
      form.resetFields()
      form.setFieldsValue({ cron: '', action: 'agent', provider: '', interactive: false, notify: true, artifact: '' })
    }
  }, [open, job, form])

  const save = async () => {
    let v: FormValues
    try { v = await form.validateFields() } catch { return }
    const args: Record<string, string> = { name: v.name.trim(), action: v.action, cron: (v.cron || '').trim() }
    if (v.action === 'agent') {
      args.prompt = v.prompt
      if (v.provider) args.provider = v.provider
      if (v.workdir) args.workdir = v.workdir
      args.interactive = v.interactive ? 'true' : 'false'
    } else if (v.action === 'exec') { args.command = v.command }
    args.notify = v.notify ? 'true' : 'false'
    if (v.artifact) args.artifact = v.artifact.trim()
    setSaving(true)
    try {
      await submit(args)
      message.success(isEdit ? t('cron.updated', { name: v.name }) : t('cron.added', { name: v.name }))
      onSaved()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} onOk={save} confirmLoading={saving} destroyOnClose
      title={isEdit ? t('cron.editTitle') : t('cron.addTitle')} okText={t('cron.save')} cancelText={t('cron.cancel')} width={560}>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label={t('cron.fieldName')} rules={[
          { required: true, message: t('cron.nameRequired') },
          // 新增时禁止撞已有名字(会被 upsert 悄悄覆盖)
          () => ({ validator: (_, val) => (!isEdit && existing.some((j) => j.name === (val || '').trim()))
            ? Promise.reject(new Error(t('cron.nameTaken'))) : Promise.resolve() }),
        ]}>
          <Input placeholder={t('cron.namePlaceholder')} disabled={isEdit} />
        </Form.Item>

        <Form.Item name="cron" label={t('cron.fieldSchedule')}
          rules={[{ required: true, message: t('cron.cronRequired') }]}>
          <CronEditor pluginId={pluginId} t={t} />
        </Form.Item>

        <Form.Item name="action" label={t('cron.fieldAction')} rules={[{ required: true }]}>
          <Select options={[
            { value: 'agent', label: t('cron.action.agent') + ' · ' + t('cron.actionAgentHint') },
            { value: 'exec', label: t('cron.action.exec') + ' · ' + t('cron.actionExecHint') },
          ]} />
        </Form.Item>

        <Form.Item noStyle shouldUpdate={(a, b) => a.action !== b.action}>
          {({ getFieldValue }) => {
            if (getFieldValue('action') === 'agent') return (
              <>
                <Form.Item name="provider" label={t('cron.fieldProvider')} extra={agentsError
                  ? <a href="#/plugins/roam.agent-discovery">{t('agentDiscovery.unavailable')}</a> : undefined}>
                  <Select allowClear loading={agentsLoading} placeholder={t('cron.providerAuto')}
                    options={agents.map((agent) => ({
                      value: agent.kind,
                      disabled: !agent.installed,
                      label: <Space size={6}>
                        {isAgentKind(agent.kind) && <AgentLogo kind={agent.kind} size={14} />}
                        {isAgentKind(agent.kind) ? agentName(agent.kind) : agent.kind}
                        {!agent.installed && <Typography.Text type="secondary">{t('agentDiscovery.missing')}</Typography.Text>}
                      </Space>,
                    }))} />
                </Form.Item>
                <Form.Item name="prompt" label={t('cron.fieldPrompt')} rules={[{ required: true, message: t('cron.promptRequired') }]}>
                  <Input.TextArea rows={5} placeholder={t('cron.promptPlaceholder')} />
                </Form.Item>
                <Form.Item label={t('cron.fieldWorkdir')} extra={t('cron.workdirHint')}>
                  <WorkdirPicker t={t} value={getFieldValue('workdir') || ''}
                    onChange={(v) => form.setFieldValue('workdir', v)} />
                </Form.Item>
                <Form.Item name="workdir" hidden><Input /></Form.Item>
                <Form.Item name="interactive" valuePropName="checked" label={t('cron.fieldInteractive')}
                  extra={t('cron.interactiveHint')}>
                  <Switch />
                </Form.Item>
              </>
            )
            return (
              <Form.Item name="command" label={t('cron.fieldCommand')} extra={t('cron.commandHint')}
                rules={[{ required: true, message: t('cron.commandRequired') }]}>
                <Input.TextArea rows={3} placeholder={t('cron.commandPlaceholder')} />
              </Form.Item>
            )
          }}
        </Form.Item>

        {/* 「跑完通知我」对两种动作都成立：拉 Agent 等会话退出，跑命令等命令返回 */}
        <Form.Item name="notify" valuePropName="checked" label={t('cron.fieldNotify')} extra={t('cron.notifyHint')}>
          <Switch />
        </Form.Item>
        <Form.Item name="artifact" label={t('cron.fieldArtifact')} extra={t('cron.artifactHint')}>
          <Input placeholder={t('cron.artifactPlaceholder')} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
