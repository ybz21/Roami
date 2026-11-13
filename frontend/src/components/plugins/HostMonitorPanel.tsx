import { usePageEffect } from '../../page-activity'
// 主机监控仪表盘(roam.host-monitor 插件的宿主侧面板):轮询插件 stats
// 命令,展示 CPU/GPU/内存/磁盘/网络实时状态与趋势。趋势历史由插件在
// StorageDir 持久化,面板打开即有近期曲线,不依赖页面常驻。
import { useCallback, useRef, useState, type ReactNode } from 'react'
import { Alert, App as AntApp, Card, Empty, Progress, Segmented, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { api } from '../../api'
import { ArrowDown, ArrowUp, Swatch } from '../../icons'

type HistoryDot = { t: number; cpu: number; mem: number; gpu: number; rx: number; tx: number }

export type Snapshot = {
  time: string
  host: {
    hostname: string; os?: string; kernel?: string; arch?: string
    uptimeSec?: number; load1: number; load5: number; load15: number
  }
  cpu: { model?: string; cores: number; usagePercent: number; perCore?: number[]; tempC?: number }
  memory: {
    total: number; used: number; available: number; usagePercent: number
    swapTotal: number; swapUsed: number
  }
  disks: { device: string; mount: string; fsType: string; total: number; used: number; free: number; usagePercent: number }[] | null
  gpus: {
    index: number; name: string; utilPercent: number; memUsed: number; memTotal: number
    tempC: number; powerW: number; powerLimitW: number; fanPercent: number; memUsagePercent: number
  }[] | null
  network: { rxBytesPerSec: number; txBytesPerSec: number }
  history: HistoryDot[] | null
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

function fmtBytes(n: number, perSec = false): string {
  let v = n
  let u = 0
  while (v >= 1024 && u < UNITS.length - 1) { v /= 1024; u++ }
  return `${v >= 100 || u === 0 ? Math.round(v) : v.toFixed(1)} ${UNITS[u]}${perSec ? '/s' : ''}`
}

function usageColor(p: number): string {
  if (p >= 90) return 'var(--danger)'
  if (p >= 70) return 'var(--warn)'
  return 'var(--ok)'
}

// SwapBar 交换空间。
//
// 它和上面那个内存表盘不是一回事：内存用到 70% 很正常，交换空间用满则是**整机卡死的
// 前兆**——一旦换页无处可去，内核就在直接回收里空转，ping 还通（内核收发 ICMP 不换页）
// 但 ssh 再也进不来，只能按电源键。本机 2026-08-12 那次就是这么冻的，而那三天里 swap
// 一直贴着 98%——数字一直在这块面板上，只是画成了一根永不变色的灰条，和 5% 长得一样。
function SwapBar({ used, total, t, onClear, job }: {
  used: number; total: number
  t: (k: string, vars?: Record<string, string | number>) => string
  /** 清一次；没给就不画那颗钮（比如快照是外部喂的、没有真插件可调） */
  onClear?: () => void
  /** 后台任务在跑时的进度（起步换出多少 / 现在还剩多少） */
  job?: { state: string; startSwap: number; swapUsed: number } | null
}) {
  const pct = Math.round((used / total) * 100)
  const running = job?.state === 'running'
  return (
    <div style={{ marginTop: 'var(--sp-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
        <Typography.Text type="secondary" style={{ fontSize: 'var(--fs-meta)' }}>
          Swap {fmtBytes(used)} / {fmtBytes(total)}
        </Typography.Text>
        {running ? (
          // 跑着的时候不给按钮：再点一次就是第二个 swapoff 抢同一块内存。
          // 数字本身就是进度——「还剩多少没读回来」比一个百分比条更说明问题。
          <Typography.Text type="secondary" style={{ marginLeft: 'auto', fontSize: 'var(--fs-meta)', color: 'var(--accent)' }}>
            {t('plugins.monitor.swapRunning', { left: fmtBytes(job?.swapUsed ?? used) })}
          </Typography.Text>
        ) : onClear && used > 0 && (
          <button type="button" className="tt-act" style={{ marginLeft: 'auto' }} onClick={onClear}>
            {t('plugins.monitor.swapClear')}
          </button>
        )}
      </div>
      <Progress percent={pct} showInfo={false} size="small" strokeColor={usageColor(pct)} />
      {pct >= 90 && (
        <div style={{ color: 'var(--danger)', fontSize: 'var(--fs-micro)' }}>
          {t('plugins.monitor.swapCritical')}
        </div>
      )}
    </div>
  )
}

// ── 轻量 SVG 面积走势图(不引图表库) ──
function Sparkline({ series, color, max, height = 46 }: {
  series: number[]; color: string; max?: number; height?: number
}) {
  const W = 300
  const H = 60
  if (series.length < 2) return <div style={{ height }} />
  const top = max ?? Math.max(...series, 1e-9) * 1.1
  const pts = series.map((v, i) => {
    const x = (i / (series.length - 1)) * W
    const y = H - (Math.min(v, top) / top) * (H - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height, display: 'block' }}>
      <polygon points={`0,${H} ${pts.join(' ')} ${W},${H}`} fill={color} opacity={0.15} />
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  )
}

function StatCard({ title, extra, children }: {
  title: ReactNode; extra?: ReactNode; children: ReactNode
}) {
  return (
    <Card size="small" title={title} extra={extra}
      styles={{ body: { padding: 12 } }} style={{ minWidth: 0 }}>
      {children}
    </Card>
  )
}

/**
 * 取数可以注入。这一层是为「中心页复用同一个面板」加的——面板本来就只认 Snapshot 这个形状，
 * 谁回这个形状它就画谁：
 *   · 插件页 —— 默认走 plugin run（本机）
 *   · 中心页看某台节点 —— 经中心反代拉那台的插件
 *   · 中心页看中心自己 —— 中心没有插件宿主，由 /api/hub/self 映射成同一形状
 * 与其为中心重画一套监控 UI（然后两套长期不同步），不如把数据源变成参数。
 */
export default function HostMonitorPanel({ pluginId, enabled, t, fetchSnapshot }: {
  pluginId: string
  enabled: boolean
  t: (k: string, vars?: Record<string, string | number>) => string
  fetchSnapshot?: () => Promise<Snapshot>
}) {
  const { message, modal } = AntApp.useApp()
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')
  const [intervalSec, setIntervalSec] = useState(3)
  const busy = useRef(false)

  const poll = useCallback(async () => {
    if (busy.current || document.hidden) return
    busy.current = true
    try {
      const data = fetchSnapshot
        ? await fetchSnapshot()
        : await api('POST', `/plugins/${encodeURIComponent(pluginId)}/run`, { command: 'host-monitor.stats', args: {} })
      setSnap(data)
      setError('')
    } catch (e: any) {
      setError(e.message || String(e))
    } finally {
      busy.current = false
    }
  }, [pluginId, fetchSnapshot])

  // 清 swap：swapoff -a 把换出去的页一次性读回内存，装不下就是 OOM 当场开枪，
  // 而它挑的多半是最大的那个进程——正在跑的 agent。所以先问一次判定，
  // 把「换出多少 / 可用多少 / 读回来还剩多少」摆在确认框上，人点了才真干。
  const run = (args: Record<string, string>) =>
    api('POST', `/plugins/${encodeURIComponent(pluginId)}/run`, { command: 'host-monitor.swap-clear', args })

  // 后台任务的进度。running 时每 2 秒问一次（比整块快照的 3 秒密一点：这是人盯着看的东西）
  const [swapJob, setSwapJob] = useState<{ state: string; startSwap: number; swapUsed: number; err?: string } | null>(null)
  usePageEffect(() => {
    if (swapJob?.state !== 'running') return
    let stop = false
    const tick = async () => {
      try {
        const st = (await run({ status: '1' }))?.data ?? {}
        if (stop) return
        setSwapJob({ state: st.state || 'idle', startSwap: st.startSwap || 0, swapUsed: st.swapUsed || 0, err: st.err })
        if (st.state === 'done') { message.success(t('plugins.monitor.swapCleared')); poll() }
        if (st.state === 'failed') {
          message.error(String(st.err).includes('need-sudo') ? t('plugins.monitor.swapNeedSudo') : (st.err || ''))
        }
      } catch { /* 轮询失败就等下一轮 */ }
    }
    const timer = setInterval(tick, 2000)
    tick()
    return () => { stop = true; clearInterval(timer) }
  }, [swapJob?.state])
  const clearSwap = async () => {
    let plan: any
    try { plan = (await run({}))?.data ?? await run({}) } catch (e: any) { message.error(e.message); return }
    if (!plan?.ok) {
      message.warning(t('plugins.monitor.swapRefuse.' + (plan?.reason || 'wont-fit'), {
        used: fmtBytes(plan?.swapUsed || 0), avail: fmtBytes(plan?.available || 0),
      }))
      return
    }
    modal.confirm({
      title: t('plugins.monitor.swapConfirmTitle'),
      content: t('plugins.monitor.swapConfirmBody', {
        used: fmtBytes(plan.swapUsed), avail: fmtBytes(plan.available), left: fmtBytes(plan.headroom),
      }),
      okText: t('plugins.monitor.swapClear'),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          // 只是把任务**起**起来：swapoff 读回 7 GB 要几十秒到几分钟，等在请求里的话
          // 页面就一直转圈、超时、刷一下还不知道它在不在跑。这里立刻返回，进度靠轮询。
          const st = (await run({ apply: '1' }))?.data ?? {}
          setSwapJob({ state: st.state || 'running', startSwap: st.startSwap || plan.swapUsed, swapUsed: st.swapUsed || plan.swapUsed })
        } catch (e: any) {
          // 没开免密时给出那一行 sudoers，而不是干巴巴一句「失败」
          message.error(String(e.message).includes('need-sudo')
            ? t('plugins.monitor.swapNeedSudo') : e.message)
        }
      },
    })
  }

  usePageEffect(() => {
    if (!enabled) return
    poll()
    const timer = setInterval(poll, intervalSec * 1000)
    return () => clearInterval(timer)
  }, [poll, intervalSec, enabled])

  if (!enabled) return <Alert type="warning" showIcon message={t('plugins.monitor.enableHint')} />
  if (error && !snap) return <Alert type="error" showIcon message={t('plugins.monitor.loadFailed')} description={error} />
  if (!snap) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>

  const { host, cpu, memory, disks, gpus, network } = snap
  const history = snap.history || []
  const uptime = host.uptimeSec
    ? t('plugins.monitor.uptimeDH', { d: Math.floor(host.uptimeSec / 86400), h: Math.floor((host.uptimeSec % 86400) / 3600) })
    : ''

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {/* 头部:主机信息 + 刷新频率 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Typography.Text strong>{host.hostname}</Typography.Text>
        {host.os && <Tag>{host.os}</Tag>}
        {host.kernel && <Tag>{host.kernel}</Tag>}
        {host.arch && <Tag>{host.arch}</Tag>}
        {uptime && <Tag>{t('plugins.monitor.uptime')} {uptime}</Tag>}
        <Tooltip title={t('plugins.monitor.loadTip')}>
          <Tag>{t('plugins.monitor.load')} {host.load1} / {host.load5} / {host.load15}</Tag>
        </Tooltip>
        <span style={{ flex: 1 }} />
        {error && <Tag color="red">{t('plugins.monitor.pollFailed')}</Tag>}
        <Segmented size="small" value={intervalSec}
          options={[3, 5, 10].map((s) => ({ label: `${s}s`, value: s }))}
          onChange={(v) => setIntervalSec(v as number)} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
        {/* CPU */}
        <StatCard
          title={<Space size={6}>{t('plugins.monitor.cpu')}
            <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {cpu.model} · {t('plugins.monitor.cores', { n: cpu.cores })}</Typography.Text></Space>}
          extra={cpu.tempC ? <Tag>{cpu.tempC}°C</Tag> : null}>
          <Space align="center" size={16} style={{ width: '100%' }}>
            <Progress type="dashboard" size={88} percent={Math.round(cpu.usagePercent)}
              strokeColor={usageColor(cpu.usagePercent)} />
            <div style={{ flex: 1, minWidth: 0, alignSelf: 'stretch', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
              <Sparkline series={history.map((h) => h.cpu)} color="var(--accent)" max={100} />
            </div>
          </Space>
          {!!cpu.perCore?.length && (
            <div style={{ display: 'flex', gap: 2, marginTop: 8, alignItems: 'flex-end', height: 26 }}>
              {cpu.perCore.map((p, i) => (
                <Tooltip key={i} title={`#${i}: ${p}%`}>
                  <div style={{ flex: 1, height: Math.max(2, (p / 100) * 26), background: usageColor(p), borderRadius: 1, opacity: 0.85 }} />
                </Tooltip>
              ))}
            </div>
          )}
        </StatCard>

        {/* 内存 */}
        <StatCard
          title={t('plugins.monitor.memory')}
          extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {fmtBytes(memory.used)} / {fmtBytes(memory.total)}</Typography.Text>}>
          <Space align="center" size={16} style={{ width: '100%' }}>
            <Progress type="dashboard" size={88} percent={Math.round(memory.usagePercent)}
              strokeColor={usageColor(memory.usagePercent)} />
            <div style={{ flex: 1, minWidth: 0, alignSelf: 'stretch', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
              <Sparkline series={history.map((h) => h.mem)} color="var(--hl-title)" max={100} />
            </div>
          </Space>
          {memory.swapTotal > 0 && <SwapBar used={memory.swapUsed} total={memory.swapTotal} t={t} onClear={fetchSnapshot ? undefined : clearSwap} job={swapJob} />}
        </StatCard>

        {/* GPU */}
        <StatCard title={t('plugins.monitor.gpu')}
          extra={gpus?.length ? <Tag>{gpus.length}</Tag> : null}>
          {gpus?.length ? gpus.map((g) => (
            <div key={g.index} style={{ marginBottom: gpus.length > 1 ? 12 : 0 }}>
              <Space size={6} wrap style={{ marginBottom: 4 }}>
                <Typography.Text style={{ fontSize: 13 }}>{g.name}</Typography.Text>
                <Tag>{g.tempC}°C</Tag>
                {g.powerLimitW > 0 && <Tag>{g.powerW}/{g.powerLimitW}W</Tag>}
                {g.fanPercent > 0 && <Tag>{t('plugins.monitor.fan')} {g.fanPercent}%</Tag>}
              </Space>
              <Space align="center" size={16} style={{ width: '100%' }}>
                <Progress type="dashboard" size={88} percent={Math.round(g.utilPercent)}
                  strokeColor={usageColor(g.utilPercent)} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Sparkline series={history.map((h) => h.gpu)} color="#7ee787" max={100} />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t('plugins.monitor.vram')} {fmtBytes(g.memUsed)} / {fmtBytes(g.memTotal)}
                  </Typography.Text>
                  <Progress percent={Math.round(g.memUsagePercent)} showInfo={false} size="small"
                    strokeColor={usageColor(g.memUsagePercent)} />
                </div>
              </Space>
            </div>
          )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('plugins.monitor.noGpu')} />}
        </StatCard>

        {/* 网络 */}
        <StatCard title={t('plugins.monitor.network')}
          extra={<Typography.Text type="secondary" style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <ArrowDown size={11} />{fmtBytes(network.rxBytesPerSec, true)} · <ArrowUp size={11} />{fmtBytes(network.txBytesPerSec, true)}
          </Typography.Text>}>
          <Sparkline series={history.map((h) => h.rx)} color="#79c0ff" height={40} />
          <Sparkline series={history.map((h) => h.tx)} color="#ffa657" height={40} />
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <Swatch color="#79c0ff" /> {t('plugins.monitor.rx')}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <Swatch color="#ffa657" /> {t('plugins.monitor.tx')}
            </Typography.Text>
          </div>
        </StatCard>
      </div>

      {/* 磁盘 */}
      <StatCard title={t('plugins.monitor.disk')}>
        {disks?.length ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '4px 24px' }}>
            {disks.map((d) => (
              <div key={d.device + d.mount}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <Typography.Text ellipsis={{ tooltip: `${d.device} (${d.fsType})` }} style={{ fontSize: 13 }}>
                    {d.mount}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                    {fmtBytes(d.used)} / {fmtBytes(d.total)}
                  </Typography.Text>
                </div>
                <Progress percent={Math.round(d.usagePercent)} size="small"
                  strokeColor={usageColor(d.usagePercent)} />
              </div>
            ))}
          </div>
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </StatCard>
    </Space>
  )
}
