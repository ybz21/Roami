import { hubConfiguration, waitForClusterRecovery } from './cluster-recovery'
import { useSettingsDraft } from '../settings/settings-draft'
import { useSettingsRead } from '../settings/settings-read'
// 设置 › 多机（设计稿 docs/design/cluster/settings.html）。
//
// 第一屏不给表单，先让人选身份——多机最容易卡住的地方是「我这台该配成什么」。
// 文案里不出现 standard / cloud / frps / frpc，那是实现的说法：
//   这台机器 = 就是你现在用的这套，可选接到一个中心上，接上之后外网也能用它
//   中心     = 只当入口，自己不跑活，别的机器接进来后在这里访问它们全部
//
// 接入用的是**一次性令牌**，不是中心的登录口令——口令是给人登录浏览器用的。
// 这一条要写在界面上：用户第一反应就是去填密码。
import { useEffect, useState } from 'react'
import { App as AntApp, Button, Card, Input, Switch, Tag } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { CloudIcon, HostIcon, LanIcon } from './cluster-icons'

type NodeState = { connected: boolean; nodeId?: string; since?: string; lastError?: string; retrying?: boolean }
type Cfg = {
  mode: 'standard' | 'hub'
  hub: string; name: string; group: string; insecure: boolean
  hasToken: boolean; state?: NodeState; lanUrls: string[]
  publicUrl?: string; enrollTtlMin?: number
}

/** 只在局域网里有效的地址：别处的机器接不进来。纯本地判断，不探测可达性。 */
function looksPrivate(raw: string): boolean {
  try {
    const h = new URL(raw).hostname
    if (h === 'localhost' || h.endsWith('.local') || h.endsWith('.lan')) return true
    if (/^10\./.test(h) || /^192\.168\./.test(h) || /^127\./.test(h)) return true
    const m = /^172\.(\d+)\./.exec(h)
    return !!m && +m[1] >= 16 && +m[1] <= 31
  } catch { return false }
}

/**
 * 设置页看的是**当前节点**的配置（请求带 /n/<id> 前缀）。中心自己的角色够不着——
 * 而那正好是「切成中心之后再也切不回来」的那个洞。所以经中心访问时，额外读一份
 * 不带前缀的 /api/cluster/config（那是中心本机的），单独给一张卡。
 */
function HubSelfCard() {
  const { t } = useI18n()
  const { message, modal } = AntApp.useApp()
  const [self, setSelf] = useState<Cfg | null>(null)
  const [busy, setBusy] = useState(false)
  const readState = useSettingsRead(() => hubConfiguration().then(r => setSelf(r?.data || null)))
  if (readState) return readState
  if (!self || self.mode !== 'hub') return null
  const backToNode = () => modal.confirm({
    title: t('cluster.hubToNodeTitle'),
    content: t('cluster.hubToNodeBody'),
    okText: t('cluster.hubToNodeOk'), cancelText: t('common.cancel'),
    onOk: async () => {
      const result = await hubConfiguration('PUT', { mode: 'standard', hub: '', name: self.name, group: self.group, insecure: false })
      setSelf(result.data)
      message.success(t('cluster.savedRestartHub'))
    },
  })
  return (
    <Card title={t('cluster.hubSelfTitle')} extra={<Tag color="processing">{t('cluster.modeHub')}</Tag>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.9 }}>{t('cluster.hubSelfHelp')}</div>
        <HubPublicFields cfg={self} saving={busy} save={async (o) => {
          setBusy(true)
          try {
            const result = await hubConfiguration('PUT', { mode: 'hub', hub: '', name: self.name, group: self.group, insecure: false, ...o })
            setSelf({ ...self, ...o, ...result.data })
            message.success(t('cluster.savedRestartHub'))
          } catch (e: any) { message.error(e.message) } finally { setBusy(false) }
        }} />
        <div><Button onClick={backToNode}>{t('cluster.hubToNode')}</Button></div>
      </div>
    </Card>
  )
}

/**
 * 中心自己的配置。两处都要用它：
 *   · 经中心访问某台机器时 —— 从 HubSelfCard 进（设置页看的是那台机器，够不到中心）
 *   · 中心一台机器都还没接时 —— 当前没有 nodeId，这一页读到的就是中心自己
 * 所以抽出来，别写两份。
 */
function HubPublicFields({ cfg, save, saving }: {
  cfg: Cfg
  save: (o: { publicUrl: string; enrollTtlMin: number }) => void
  saving: boolean
}) {
  const { t } = useI18n()
  const [pub, setPub] = useState(cfg.publicUrl || '')
  const [ttl, setTtl] = useState(cfg.enrollTtlMin || 30)
  const draftNotice = useSettingsDraft('hub-public:' + cfg.name, { pub, ttl }, { pub: cfg.publicUrl || '', ttl: cfg.enrollTtlMin || 30 }, value => { setPub(value.pub); setTtl(value.ttl) })
  const effective = pub || location.origin
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {draftNotice}
      <div className="tt-crow">
        <label className="tt-cf" style={{ flex: '2 1 320px' }}>
          <span>{t('cluster.publicUrl')}</span>
          <Input value={pub} placeholder={location.origin} onChange={(e) => setPub(e.target.value)} />
          <em>{t('cluster.publicUrlHelp')}</em>
        </label>
        <label className="tt-cf">
          <span>{t('cluster.enrollTtl')}</span>
          <Input type="number" value={ttl} onChange={(e) => setTtl(+e.target.value || 30)} />
        </label>
      </div>
      {/* 内网地址是最常见的坑：你在局域网里管中心，签出去的命令就带内网地址，别处的
          机器照着做必然连不上，而它那边只报「连接失败」，看不出是地址的问题。 */}
      <div className={`tt-cstate${looksPrivate(effective) ? ' warn' : ' ok'}`}>
        <i className="d" />
        <span>{looksPrivate(effective) ? t('cluster.publicPrivate') : t('cluster.publicOk')}</span>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button type="primary" loading={saving} onClick={() => save({ publicUrl: pub, enrollTtlMin: ttl })}>
          {t('cluster.savePublic')}
        </Button>
        <Button onClick={() => setPub(location.origin)}>{t('cluster.useCurrent')}</Button>
      </div>
      {/* 这两句用户一定会问，不写他就会自己脑补出更坏的答案 */}
      <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.9 }}>
        <div>{t('cluster.hubStores')}</div>
        <div>{t('cluster.hubDown')}</div>
      </div>
    </div>
  )
}

export function ClusterSettings() {
  const { t } = useI18n()
  const { message, modal } = AntApp.useApp()
  const [cfg, setCfg] = useState<Cfg | null>(null)
  const [form, setForm] = useState<{ hub: string; token: string; name: string; group: string; insecure: boolean }>(
    { hub: '', token: '', name: '', group: '', insecure: false },
  )
  const [saving, setSaving] = useState(false)
  const [baseline, setBaseline] = useState(form)
  const draftNotice = useSettingsDraft('cluster-join', form, baseline, setForm, !!cfg)

  const load = () => api('GET', '/cluster/config').then((r) => {
    const c: Cfg = r?.data
    setCfg(c)
    const next = { hub: c.hub || '', token: '', name: c.name || '', group: c.group || '', insecure: !!c.insecure }
    setForm(next); setBaseline(next)
  })

  const readState = useSettingsRead(load)
  // 接入状态是会自己变的（重连、掉线），停在旧值上比不显示更糟
  useEffect(() => {
    const id = window.setInterval(() => { api('GET', '/cluster/config').then((r) => setCfg(r?.data)).catch(() => {}) }, 5000)
    return () => window.clearInterval(id)
  }, [])

  if (readState) return readState
  if (!cfg) return null
  const isHub = cfg.mode === 'hub'

  const save = async (mode: 'standard' | 'hub', extra?: Partial<typeof form>,
                      hubOpts?: { publicUrl?: string; enrollTtlMin?: number }) => {
    setSaving(true)
    try {
      const f = { ...form, ...extra }
      const r = await api('PUT', '/cluster/config', {
        mode,
        hub: mode === 'hub' ? '' : f.hub.trim(),
        // 只在用户真填了新令牌时才传：不传 = 保留原来的
        token: f.token ? f.token.trim() : undefined,
        name: f.name, group: f.group, insecure: f.insecure,
        ...(hubOpts || {}),
      })
      if (r?.data?.needsRestart) restartPrompt()
      else message.success(t('cluster.saved'))
      load()
    } catch (e: any) {
      message.error(e?.message || t('cluster.saveFailed'))
    } finally { setSaving(false) }
  }

  const restartPrompt = () => modal.confirm({
    title: t('cluster.restartTitle'),
    content: t('cluster.restartBody'),
    okText: t('cluster.restartNow'), cancelText: t('cluster.restartLater'),
    onOk: async () => {
      try {
        await api('POST', '/cluster/restart')
      } catch (e: any) { message.error(t('cluster.restartFailed') + ' ' + e.message); throw e }
      const hide = message.loading(t('cluster.restarting'), 0)
      try { await waitForClusterRecovery(); location.reload() }
      catch (e) { message.error(t('cluster.recoveryTimeout')); throw e }
      finally { hide() }

    },
  })

  const switchMode = (next: 'standard' | 'hub') => {
    if (next === cfg.mode) return
    // 只有「这台机器 → 中心」需要拦：那个方向真会丢东西（终端断、项目不见）。
    // 反过来只是把本机能力重新打开，没有东西会消失。
    if (next === 'hub') {
      modal.confirm({
        title: t('cluster.toHubTitle'),
        content: <div style={{ lineHeight: 1.9 }}>{t('cluster.toHubBody')}</div>,
        okText: t('cluster.toHubOk'), cancelText: t('common.cancel'),
        okButtonProps: { danger: true },
        onOk: () => save('hub'),
      })
      return
    }
    save('standard')
  }

  const st = cfg.state
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {draftNotice}
      <Card title={t('cluster.roleTitle')}>
        <div className="tt-modes">
          <button type="button" className={`tt-mode${!isHub ? ' on' : ''}`} onClick={() => switchMode('standard')}>
            <span className="radio" />
            <span className="t"><HostIcon />{t('cluster.modeNode')}{!isHub && <Tag color="success" style={{ marginInlineStart: 4 }}>{t('cluster.current')}</Tag>}</span>
            <span className="d">{t('cluster.modeNodeDesc')}</span>
          </button>
          <button type="button" className={`tt-mode${isHub ? ' on' : ''}`} onClick={() => switchMode('hub')}>
            <span className="radio" />
            <span className="t"><CloudIcon />{t('cluster.modeHub')}{isHub && <Tag color="success" style={{ marginInlineStart: 4 }}>{t('cluster.current')}</Tag>}</span>
            <span className="d">{t('cluster.modeHubDesc')}</span>
          </button>
        </div>
      </Card>

      {!isHub && (
        <Card title={t('cluster.joinTitle')} extra={
          <Tag color={st?.connected ? 'success' : cfg.hub ? 'warning' : 'default'}>
            {st?.connected ? t('cluster.connected') : cfg.hub ? t('cluster.connecting') : t('cluster.notJoined')}
          </Tag>
        }>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className={`tt-cstate${st?.connected ? ' ok' : cfg.hub ? ' warn' : ''}`}>
              <i className="d" />
              {st?.connected
                ? <span>{t('cluster.joinedTo', { hub: cfg.hub })}</span>
                : cfg.hub
                  ? <span>{t('cluster.connectingTo', { hub: cfg.hub })}</span>
                  : <span>{t('cluster.notJoinedHelp')}</span>}
              {/* 上次为什么没连上——令牌过期 / 凭证失效 / 地址不是中心，三种的下一步完全不同。
                  这句话以前只进日志，用户得去翻 journalctl 才看得到。 */}
              {!st?.connected && st?.lastError && <span className="err">{st.lastError}</span>}
            </div>

            <div className="tt-crow">
              <label className="tt-cf">
                <span>{t('cluster.hubAddr')}</span>
                <Input value={form.hub} placeholder="https://…"
                  onChange={(e) => setForm({ ...form, hub: e.target.value })} />
                <em>{t('cluster.hubHelp')}</em>
              </label>
              <label className="tt-cf">
                <span>{t('cluster.token')} <Tag>{t('cluster.tokenOnce')}</Tag></span>
                <Input.Password value={form.token}
                  placeholder={cfg.hasToken ? t('cluster.tokenKeep') : t('cluster.tokenPlaceholder')}
                  onChange={(e) => setForm({ ...form, token: e.target.value })} />
                <em>{t('cluster.tokenHelp')}</em>
              </label>
            </div>
            <div className="tt-crow">
              <label className="tt-cf">
                <span>{t('cluster.nodeName')}</span>
                <Input value={form.name} placeholder={t('cluster.nodeNamePlaceholder')}
                  onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label className="tt-cf">
                <span>{t('cluster.groupName')}</span>
                <Input value={form.group} placeholder={t('cluster.optional')}
                  onChange={(e) => setForm({ ...form, group: e.target.value })} />
              </label>
            </div>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-dim)' }}>
              <Switch size="small" checked={form.insecure} onChange={(v) => setForm({ ...form, insecure: v })} />
              {t('cluster.insecure')}
            </label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button type="primary" loading={saving} onClick={() => save('standard')}>{t('cluster.saveJoin')}</Button>
              {cfg.hub && (
                <Button danger onClick={() => modal.confirm({
                  title: t('cluster.leaveTitle'), content: t('cluster.leaveBody'),
                  okText: t('cluster.leave'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
                  onOk: () => save('standard', { hub: '', token: '' }),
                })}>{t('cluster.leave')}</Button>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* 中心一台机器都还没接时：当前没有 nodeId，这一页读到的就是中心自己，
          于是在这里配它的对外地址。接了机器之后走 HubSelfCard 那条路。 */}
      {isHub && (
        <Card title={t('cluster.publicTitle')} extra={<Tag color="processing">{t('cluster.publicTag')}</Tag>}>
          <HubPublicFields cfg={cfg} saving={saving} save={(o) => save('hub', undefined, o)} />
        </Card>
      )}

      <HubSelfCard />

      <Card title={isHub ? t('cluster.hubEntry') : t('cluster.howToReach')}
        extra={!isHub && <Tag>{t('cluster.bothWork')}</Tag>}>
        <div className="tt-ways">
          <div className="tt-way">
            <div className="h"><LanIcon />{isHub ? t('cluster.entryForPeople') : t('cluster.lanDirect')}</div>
            {(cfg.lanUrls.length ? cfg.lanUrls : ['—']).map((u) => <div key={u} className="u">{u}</div>)}
            <div className="n">{isHub ? t('cluster.entryForPeopleHelp') : t('cluster.lanDirectHelp')}</div>
          </div>
          {!isHub && (
            <div className="tt-way">
              <div className="h"><CloudIcon />{t('cluster.viaHub')}</div>
              <div className="u">{cfg.hub || t('cluster.notJoined')}</div>
              <div className="n">{t('cluster.viaHubHelp')}</div>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}
