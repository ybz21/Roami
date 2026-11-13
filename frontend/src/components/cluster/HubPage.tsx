import { usePageEffect } from '../../page-activity'
// 中心页（#/hub）：让中心自己能被看见。
//
// 2026-08-11 中心因为一个 goroutine 泄漏卡死了十几个小时，是部署时碰巧撞见的——界面上
// 没有任何地方会说「中心不健康」。这一页补的就是这个洞，摆的都是**只有中心才知道**的东西：
// 它自己的内存/goroutine 曲线、经它转发的流量、每台机器的版本与能力、最近发生了什么。
//
// 它**不是切换器里的第 N 台机器**：中心不跑会话/项目/文件/终端，切过去大半个应用是空的。
// 所以入口是「去看中心」，当前机器不变（见 Navigation 的 hubEntry）。
import { useState } from 'react'
import { App as AntApp, Modal } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { relTime } from '../../time-format'
import { NodeMark, nodeDotColor } from './NodeMark'
import { setCurrentNode, useClusterNodes, useCurrentNodeId, type ClusterNode } from './node-url'
import { hubReasonText, assessHub } from './hub-health'
import HostMonitorPanel, { type Snapshot } from '../plugins/HostMonitorPanel'
import { WarnIcon } from '../../icons'

type Sample = { at: number; rss: number; goroutines: number; heap: number; tunnels: number; requests: number }
type HubEvent = { at: number; kind: string; node?: string; secs?: number }
type Host = {
  memTotal: number; memAvailable: number; swapTotal: number; swapFree: number
  load1: number; load5: number; load15: number; cpus: number
  cpuPercent: number; hostname: string; uptimeSecs: number
}
type SelfData = {
  version: string; startedAt: number; uptimeSecs: number; pprof: string
  now: Sample; host: Host; nodes: number; nodesOnline: number
  samples: Sample[]; events: HubEvent[]
}

/** 中心自己的接口永远不带 /n/<id> 前缀——加了就成了「问某台节点中心怎么样」。 */
async function getSelf(): Promise<SelfData | null> {
  try {
    const r = await fetch('/api/hub/self', { cache: 'no-store' })
    if (!r.ok) return null
    return (await r.json())?.data || null
  } catch { return null }
}

function mb(bytes: number): number { return Math.round(bytes / 1024 / 1024) }

/**
 * 把 /api/hub/self 映射成 host-monitor 插件那套 Snapshot——**为了复用同一个面板**。
 *
 * 中心没有插件宿主（NewHub 不构造业务 runtime），所以拿不到插件的数据；但面板只认形状，
 * 不认来源。与其为中心重画一套监控 UI（然后两套长期不同步、术语还不一致），
 * 不如在这里做一次映射。缺的字段照实留空：中心不采 GPU 与磁盘，disks/gpus 就是 null，
 * 面板本来就按「没有这一节」处理；网络给 0 而不是假数，因为面板会硬取这两个字段。
 */
function hubSnapshot(d: SelfData): Snapshot {
  const h = d.host || ({} as Host)
  const used = Math.max(0, h.memTotal - h.memAvailable)
  return {
    time: new Date().toISOString(),
    host: {
      hostname: h.hostname || location.hostname,
      uptimeSec: h.uptimeSecs, load1: h.load1, load5: h.load5, load15: h.load15,
    },
    cpu: { cores: h.cpus, usagePercent: h.cpuPercent || 0 },
    memory: {
      total: h.memTotal, used, available: h.memAvailable,
      usagePercent: h.memTotal ? (used / h.memTotal) * 100 : 0,
      swapTotal: h.swapTotal, swapUsed: Math.max(0, h.swapTotal - h.swapFree),
    },
    disks: null,
    gpus: null,
    network: { rxBytesPerSec: 0, txBytesPerSec: 0 },
    // 历史直接用中心自己的采样：5 分钟一点，比插件的 3 秒粗，但它问的本来就是「有没有在爬」
    history: (d.samples || []).map((x) => ({
      t: x.at, cpu: 0, gpu: 0, rx: 0, tx: 0,
      mem: h.memTotal ? (x.rss / h.memTotal) * 100 : 0,
    })),
  }
}
function gb(bytes: number): string { return (bytes / 1024 / 1024 / 1024).toFixed(1) }

/** 迷你曲线。单点数字看不出「稳在 20」还是「正在爬」——曲线才是证据。
 *  只有一个点时**明说在等**，不要留一片空白让人以为是坏了：中心刚重启就是这个状态。 */
function Spark({ series, tone, waiting }: { series: number[]; tone: string; waiting: string }) {
  if (series.length < 2) return <div className="tt-hub-spark waiting">{waiting}</div>
  const max = Math.max(...series), min = Math.min(...series)
  const span = Math.max(1e-6, max - min)
  const pts = series.map((v, i) => `${(i / (series.length - 1)) * 60},${(18 - ((v - min) / span) * 16).toFixed(1)}`).join(' ')
  return (
    <svg className="tt-hub-spark" viewBox="0 0 60 20" preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: tone }} />
    </svg>
  )
}

/**
 * 一格指标。它们不等重要：平时你只想知道「正常吗」，异常时才想看具体数字。
 * 所以做成一条紧凑的横条而不是四张等大的卡片——四张 133px 高的卡片占掉三分之一首屏，
 * 却只传达了「一切正常」这一件事，而你最常看的机器列表被挤到下面去了。
 */
function Stat({ label, value, unit, sub, series, tone, waiting }: {
  label: string; value: string; unit?: string; sub: string; series?: number[]; tone?: string; waiting: string
}) {
  const bad = tone === 'var(--danger)' || tone === 'var(--warn)'
  return (
    <div className={`tt-hub-stat${bad ? ' bad' : ''}`}>
      <div className="line">
        <span className="k">{label}</span>
        <span className="v" style={bad ? { color: tone } : undefined}>{value}{unit && <span className="u">{unit}</span>}</span>
      </div>
      <div className="line2">
        <span className="s" title={sub}>{sub}</span>
        {series && series.length >= 2
          ? <Spark series={series} tone={tone || 'var(--ok)'} waiting={waiting} />
          : <span className="wait" title={waiting} />}
      </div>
    </div>
  )
}

/**
 * 拉某台节点的宿主机概况。**复用现成的 host-monitor 插件**，中心不重画监控——
 * 中心本来就是反代，这条路几乎白拿：/n/<id>/api/plugins/<插件>/run 就是节点自己那套。
 *
 * 只取两个数（CPU% / 内存%）做摘要，完整的 CPU/GPU/磁盘/网络 + 历史曲线仍在那台机器的
 * 插件面板里——在这里重画一遍监控 UI 是白费力气，还会和插件面板长期不同步。
 */
async function nodeHostSummary(nodeId: string): Promise<{ cpu: number; mem: number } | null> {
  try {
    const r = await fetch(`/n/${encodeURIComponent(nodeId)}/api/plugins/roam.host-monitor/run`, {
      method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'host-monitor.stats', args: {} }),
    })
    if (!r.ok) return null // 插件没装/没开：这台就不显示，不报错
    // 经反代回来的是插件的原始返回：Snapshot 在**顶层**，没有 data 包装
    // （节点侧的 PluginRun 直接把插件结果写回；踩过一次，按 .data 取会永远拿到 undefined）
    const j = await r.json()
    const snap = (j?.data ?? j) as { cpu?: { usagePercent: number }; memory?: { usagePercent: number } }
    if (!snap?.cpu || !snap?.memory) return null
    return { cpu: Math.round(snap.cpu.usagePercent), mem: Math.round(snap.memory.usagePercent) }
  } catch { return null }
}

function NodeRow({ n, current, hubVersion, onEnter, onMonitor }: {
  n: ClusterNode; current: boolean; hubVersion: string; onEnter: () => void; onMonitor: () => void
}) {
  const { t } = useI18n()
  // 宿主概况按需拉，失败就当没有——插件可能没装、没开，或者那台正忙
  const [host, setHost] = useState<{ cpu: number; mem: number } | null>(null)
  usePageEffect(() => {
    if (!n.online) return
    let stop = false
    const load = () => nodeHostSummary(n.id).then((h) => { if (!stop) setHost(h) })
    load()
    const iv = setInterval(load, 30000)
    return () => { stop = true; clearInterval(iv) }
  }, [n.id, n.online])

  // 版本只在**主版本真不同**时才提示：字符串全等太脆，带个构建后缀（0083f46-mon）就误报，
  // 两台一起亮黄反而没人再信它。完整版本进 title。
  const mismatch = !!n.version && !!hubVersion && majorOf(n.version) !== majorOf(hubVersion)
  const ver = n.version && n.version.length > 14 ? n.version.slice(0, 14) + '…' : n.version

  return (
    <div className={`tt-hub-node${current ? ' cur' : ''}${n.online ? '' : ' off'}`} title={n.version}>
      <NodeMark name={n.name} size="sm" current={current} offline={!n.online} />
      <span className="who">
        <span className="l1">
          <span className="nm">{n.name}</span>
          {n.group && <span className="dim">{n.group}</span>}
          {mismatch && <span className="tt-hub-chip warn">{t('hub.versionMismatch')}</span>}
        </span>
        <span className="l2">{[n.hostname, ver].filter(Boolean).join(' · ')}</span>
      </span>
      <span className="metrics">
        {n.online ? <>
          <span>{t('node.latencyMs', { ms: n.latencyMs })}</span>
          {host && <span className={host.cpu > 85 ? 'hot' : ''}>CPU {host.cpu}%</span>}
          {host && <span className={host.mem > 85 ? 'hot' : ''}>{t('hub.memShort')} {host.mem}%</span>}
          <span>{t('node.sessionsN', { count: n.sessionCount })}</span>
        </> : <span>{t('node.offline')}</span>}
      </span>
      <i className="dot" style={{ background: nodeDotColor(n) }} />
      <span className="acts">
        {host && <button type="button" className="tt-act" onClick={onMonitor}>{t('hub.fullMonitor')}</button>}
        <button type="button" className="tt-act ico" disabled={!n.online || current} onClick={onEnter}
          title={current ? t('hub.enterCurrent') : t('hub.enter')} aria-label={t('hub.enter')}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round"><path d="M9 5l7 7-7 7" /></svg>
        </button>
      </span>
    </div>
  )
}

/** 主版本：取 vX.Y.Z 或前 7 位 sha，忽略构建后缀（-254-gbd60090 / -mon 这类）。 */
function majorOf(v: string): string {
  const m = v.match(/^v?\d+\.\d+\.\d+/)
  return m ? m[0] : v.slice(0, 7)
}

export default function HubPage() {
  const { t } = useI18n()
  const { message, modal } = AntApp.useApp()
  const nodes = useClusterNodes()
  const curNodeId = useCurrentNodeId()
  const [self, setSelf] = useState<SelfData | null>(null)
  const [loading, setLoading] = useState(true)
  const [hostOpen, setHostOpen] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [monitorNode, setMonitorNode] = useState<ClusterNode | null>(null)

  usePageEffect(() => {
    let stop = false
    const load = () => getSelf().then((d) => { if (!stop) { setSelf(d); setLoading(false) } })
    load()
    const iv = setInterval(load, 15000)
    return () => { stop = true; clearInterval(iv) }
  }, [])

  if (loading) return <div className="tt-hub-empty">{t('common.loading')}</div>
  if (!self) return <div className="tt-hub-empty">{t('hub.notHub')}</div>

  const s = self.samples
  const now = self.now
  // 请求速率按相邻两点差分：累计量重启后会归零，差分自然断开，而不是画出一段假的「零流量」
  const rate = (() => {
    if (s.length < 2) return null // 只有一个点：算不出速率。显示 0 会被读成「没有流量」，那是另一回事
    const a = s[s.length - 2], b = s[s.length - 1]
    const dt = Math.max(1, b.at - a.at)
    return Math.max(0, (b.requests - a.requests) / dt)
  })()
  // 判色看**占宿主机的比例**，不看绝对值：299MB 在 1.6G 的机器上是灾难，在 16G 上不算事。
  // 今早那台就是 1.6G——当时只看到「299MB」，完全没意识到它已经把整台机器拖进换页颠簸。
  const host = self.host || ({} as Host)
  const rssShare = host.memTotal ? now.rss / host.memTotal : 0
  const rssTone = rssShare > 0.5 ? 'var(--danger)' : rssShare > 0.25 ? 'var(--warn)' : 'var(--ok)'
  const gorTone = now.goroutines > 5000 ? 'var(--danger)' : now.goroutines > 1000 ? 'var(--warn)' : 'var(--ok)'

  const uptime = (() => {
    const m = Math.floor(self.uptimeSecs / 60)
    if (m < 60) return t('hub.upMinutes', { n: m })
    const h = Math.floor(m / 60)
    return h < 24 ? t('hub.upHours', { n: h }) : t('hub.upDays', { n: Math.floor(h / 24) })
  })()

  const enter = (id: string) => {
    Modal.confirm({
      title: t('hub.enterTitle'),
      content: t('hub.enterBody'),
      okText: t('hub.enter'),
      cancelText: t('common.cancel'),
      onOk: () => { setCurrentNode(id); location.hash = '#/projects'; location.reload() },
    })
  }

  const evText = (e: HubEvent): string => {
    if (e.kind === 'hub_start') return t('hub.evHubStart')
    if (e.kind === 'enroll') return t('hub.evEnroll')
    if (e.kind === 'node_down') return t('hub.evNodeDown', { node: e.node || '' })
    if (e.kind === 'node_up') {
      return e.secs && e.secs > 0
        ? t('hub.evNodeBack', { node: e.node || '', secs: e.secs })
        : t('hub.evNodeUp', { node: e.node || '' })
    }
    return e.kind
  }
  const evTone = (k: string) => (k === 'node_down' ? 'var(--danger)' : k === 'hub_start' ? 'var(--warn)' : 'var(--ok)')

  // 进了这一页就该直接看到结论，不用自己去读四条曲线
  const health = assessHub(s, Math.max(0, self.nodes - self.nodesOnline))

  // 重启中心：它是「已经出事了，先恢复」的动作，所以要二次确认并说清代价——
  // 节点会断开重连（几秒），正在跑的会话不受影响（会话在节点上，不在中心）。
  const restart = () => modal.confirm({
    title: t('hub.restartTitle'),
    content: t('hub.restartBody'),
    okText: t('hub.restart'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
    onOk: async () => {
      try { await api('POST', '/cluster/restart'); message.loading(t('hub.restarting'), 8) }
      catch (e: any) { message.error(e?.message || String(e)) }
    },
  })

  const exportDiag = () => {
    const blob = new Blob([JSON.stringify(self, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `roam-hub-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')}.json`
    a.click()
    URL.revokeObjectURL(a.href)
    message.success(t('hub.exported'))
  }

  return (
    <div className="tt-hub">
      <div className="tt-hub-head">
        <span className="tt-pagename">{t('hub.title')}</span>
        <span className="tt-pagedivider" aria-hidden="true" />
        <span className="sub">{location.host} · {uptime}</span>
        <span className="grow" />
        <button type="button" className="tt-act" onClick={() => getSelf().then(setSelf)}>{t('hub.refresh')}</button>
      </div>

      {/* 状态行：一行说完「好不好 + 三个数」。异常时整行变红、长出原因与动作——
          四张等大的指标卡占掉三分之一首屏，却只为传达「一切正常」这一件事。 */}
      <div className={`tt-hub-status${health.level !== 'ok' ? ' bad' : ''}`}>
        <i className="d" />
        <b>{health.level === 'ok' ? t('hub.allGood') : hubReasonText(health, t)}</b>
        <span className="nums">
          {t('hub.memory')} {mb(now.rss)}MB
          {host.memTotal ? `（${t('hub.ofHostShort', { pct: Math.round(rssShare * 100) })}）` : ''}
          {' · '}goroutine {now.goroutines.toLocaleString()}
          {' · '}{now.tunnels > 0 || health.level === 'ok'
            ? t('hub.fwd', { rate: rate === null ? '—' : rate.toFixed(1) })
            : t('hub.queueN', { n: 0 })}
        </span>
        <span className="grow" />
        {health.level !== 'ok' && (
          <>
            <button type="button" className="tt-act" onClick={() => setDiagOpen(true)}>{t('hub.seeDiag')}</button>
            <button type="button" className="tt-act danger" onClick={restart}>{t('hub.restart')}</button>
          </>
        )}
      </div>

      <div className="tt-hub-sec">{t('hub.machines')}<span className="grow" />
        <span className="dim">{t('hub.onlineOf', { online: self.nodesOnline, total: self.nodes })}</span>
      </div>
      {nodes.length === 0
        ? <div className="tt-hub-empty small">{t('hub.noNodes')}</div>
        : nodes.map((n) => (
          <NodeRow key={n.id} n={n} current={n.id === curNodeId} hubVersion={self.version}
            onEnter={() => enter(n.id)} onMonitor={() => setMonitorNode(n)} />
        ))}

      <div className="tt-hub-sec">{t('hub.events')}</div>
      {self.events.length === 0
        ? <div className="tt-hub-empty small">{t('hub.noEvents')}</div>
        : [...self.events].reverse().slice(0, 8).map((e, i) => (
          <div className="tt-hub-ev" key={i}>
            <span className="t">{relTime(e.at, t)}</span>
            <i className="i" style={{ background: evTone(e.kind) }} />
            <span className="x">{evText(e)}</span>
          </div>
        ))}

      {!!host.memTotal && (<>
        <div className="tt-hub-fold">
          <span className="k">{t('hub.host')}</span>
          <span className="v">{t('hub.hostBrief', {
            pct: Math.round(((host.memTotal - host.memAvailable) / host.memTotal) * 100),
            load: host.load1.toFixed(2),
          })}</span>
          <span className="grow" />
          <button type="button" className="tt-act" onClick={() => setHostOpen((v) => !v)}>
            {hostOpen ? t('hub.collapse') : t('hub.expand')}
          </button>
        </div>
        {hostOpen && (
          <div className="tt-hub-foldbody">
            {/* 用的是插件页那个面板本身，不是另画一套（见 hubSnapshot） */}
            <HostMonitorPanel pluginId="roam.host-monitor" enabled t={t}
              fetchSnapshot={async () => hubSnapshot((await getSelf()) || self)} />
          </div>
        )}
      </>)}

      <div className="tt-hub-fold">
        <span className="k">{t('hub.diagnostics')}</span>
        <span className="v">
          {self.pprof ? `pprof ${t('hub.pprofOn')}` : `pprof ${t('hub.pprofOff')}`} · {t('hub.samplesN', { n: s.length })}
        </span>
        <span className="grow" />
        <button type="button" className="tt-act" onClick={() => setDiagOpen((v) => !v)}>
          {diagOpen ? t('hub.collapse') : t('hub.expandDiag')}
        </button>
      </div>
      {diagOpen && (
        <div className="tt-hub-foldbody diag">
          {self.pprof && <div className="tt-hub-cmd">ssh -L 6060:{self.pprof} &lt;user&gt;@{location.hostname}</div>}
          <div className="row">
            <span className="hint" title={t('hub.pprofWhy')}>{t('hub.pprofShort')}</span>
            <button type="button" className="tt-act" onClick={exportDiag}>{t('hub.export')}</button>
          </div>
        </div>
      )}

      {monitorNode && (
        <Modal open width={900} footer={null} title={monitorNode.name}
          onCancel={() => setMonitorNode(null)} destroyOnClose>
          {/* 同一个面板，取数换成「经中心反代拉那台的插件」——中心不重画监控 UI */}
          <HostMonitorPanel pluginId="roam.host-monitor" enabled t={t} fetchSnapshot={async () => {
            const r = await fetch(`/n/${encodeURIComponent(monitorNode.id)}/api/plugins/roam.host-monitor/run`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
              body: JSON.stringify({ command: 'host-monitor.stats', args: {} }),
            })
            if (!r.ok) throw new Error(String(r.status))
            const j = await r.json()
            return (j?.data ?? j) as Snapshot
          }} />
        </Modal>
      )}
    </div>
  )
}
