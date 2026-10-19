import { useSettingsRead } from './settings-read'
// 手机/Android 后端配置：本机模拟器(AVD) / 远程设备 / 本机真机 三选一 + 设备列表(点一下换目标)。
// 三档的分界线是「谁能起停它」：模拟器能起能停能新建，远程只能连断，真机只能连。
// Android 与 iOS 互斥（active 决定哪个驱动镜像页），未装依赖时开关会先自动装。
import { useEffect, useRef, useState } from 'react'
import { App as AntApp, Button, Card, Input, Modal, Popconfirm, Segmented, Space, Switch, Tag } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { DeviceIcon, PlusIcon } from '../../icons'
import { androidTargetOf, devKindText, devStateText, listPhoneDevices, type PhoneDevice } from '../../phone-devices'
import { AvdCreateDrawer } from './avd-create'

type PhoneCfg = { active: '' | 'android' | 'ios'; android: { mode: string; address: string; avd: string }; ios: { mode: string; address: string } }
const PHONE_DEFAULT: PhoneCfg = { active: 'android', android: { mode: 'avd', address: '', avd: '' }, ios: { mode: 'simulator', address: '' } }

export function PhoneSettings() {
  // 两张卡片：Android / iOS，各自配置(互不覆盖)；active 决定哪个驱动镜像。
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [cfg, setCfg] = useState<PhoneCfg>(PHONE_DEFAULT)
  const cfgRef = useRef(cfg)
  const [status, setStatus] = useState<any>({})
  const [devs, setDevs] = useState<{ android: PhoneDevice[]; ios: PhoneDevice[] }>({ android: [], ios: [] })
  const [plat, setPlat] = useState<{ android: { installed: boolean }; ios: { installed: boolean; supported: boolean } }>({ android: { installed: false }, ios: { installed: false, supported: false } })
  const [installing, setInstalling] = useState<'android' | 'ios' | null>(null)
  const [busy, setBusy] = useState('')
  const [log, setLog] = useState('')
  const [avdBusy, setAvdBusy] = useState('') // 正在起/停的 AVD 名：起一台要几十秒，按钮期间禁用
  const [createOpen, setCreateOpen] = useState(false)
  const [remoteOpen, setRemoteOpen] = useState(false)
  const [remoteAddr, setRemoteAddr] = useState('')
  useEffect(() => { cfgRef.current = cfg }, [cfg])

  const loadStatus = () => api('GET', '/phone/status').then((r) => { if (r?.data) setStatus(r.data) }).catch(() => {})
  const loadDevices = (p: 'android' | 'ios') => listPhoneDevices(p).then((list) => setDevs((s) => ({ ...s, [p]: list })))
  const readState = useSettingsRead(async () => {
    const [config, platforms] = await Promise.all([api('GET', '/phone/config'), api('GET', '/phone/platforms')])
    setCfg({ ...PHONE_DEFAULT, ...config.data, android: { ...PHONE_DEFAULT.android, ...config.data.android }, ios: { ...PHONE_DEFAULT.ios, ...config.data.ios } })
    setPlat({ android: { installed: !!platforms.data.android?.installed }, ios: { installed: !!platforms.data.ios?.installed, supported: !!platforms.data.ios?.supported } })
    await Promise.all([loadStatus(), loadDevices('android'), loadDevices('ios')])
  })
  useEffect(() => {
    const iv = setInterval(loadStatus, 3000) // 状态灯后台自动刷新
    // 设备列表也自动刷：插上 USB 真机 / 起了模拟器之后不该还要人去点「刷新设备」。
    const dv = setInterval(() => { void loadDevices('android').catch(() => {}); void loadDevices('ios').catch(() => {}) }, 6000)
    return () => { clearInterval(iv); clearInterval(dv) }
  }, [])

  const persist = (next: PhoneCfg) => { setCfg(next); cfgRef.current = next; return api('PUT', '/phone/config', next).then(loadStatus).catch((e: any) => message.error(e.message)) }
  const patch = (p: 'android' | 'ios', d: any) => persist({ ...cfgRef.current, [p]: { ...cfgRef.current[p], ...d } })
  const editAddr = (p: 'android' | 'ios', a: string) => setCfg((c) => { const n = { ...c, [p]: { ...c[p], address: a } }; cfgRef.current = n; return n })
  const blurPersist = () => api('PUT', '/phone/config', cfgRef.current).then(loadStatus).catch(() => {})

  // 开关：开=激活(互斥+未装先装)；关=未启用。
  const toggle = async (p: 'android' | 'ios', on: boolean) => {
    if (busy || installing || (p === 'ios' && !plat.ios.supported)) return
    if (!on) { if (cfg.active === p) persist({ ...cfgRef.current, active: '' }); return }
    if (!plat[p].installed) {
      setInstalling(p); setLog('')
      try {
        const r = await api('POST', '/phone/install', { platform: p })
        setLog(r?.data?.log || r?.error || '')
        if (!r?.data?.installed) { message.error(t('phone.installFailed')); setInstalling(null); return }
        setPlat((s) => ({ ...s, [p]: { ...s[p], installed: true } }))
      } catch (e: any) { message.error(e.message); setInstalling(null); return }
      setInstalling(null)
    }
    persist({ ...cfgRef.current, active: p }); loadDevices(p)
  }
  const act = async (name: string, endpoint: string) => {
    setBusy(name); setLog('')
    try {
      const r = await api('POST', endpoint, {})
      if (r?.error) { message.error(r.error); setLog(r.error) }
      if (r?.data?.log) setLog(r.data.log)
      const h = r?.data?.health || r?.data
      if (h?.error) message.warning(h.error)
    } catch (e: any) { message.error(e.message) } finally { setBusy(''); loadStatus() }
  }
  const dim = { color: 'var(--text-dim)', fontSize: 12 }
  const st = status || {}

  // 一台 AVD 的名字：没跑起来的条目 id 是 avd:<名>，跑着的那条 name 就是 AVD 名。
  const avdNameOf = (d: PhoneDevice) => (d.id.startsWith('avd:') ? d.id.slice(4) : d.name)
  // 起/停某台模拟器。先把它选成当前目标——/phone/start 作用于当前配置，
  // 否则在「真机」来源下点启动会被后端回一句「该来源无需启动」。
  const avdAction = async (kind: 'start' | 'stop', d: PhoneDevice) => {
    const name = avdNameOf(d)
    setAvdBusy(name); setLog('')
    try {
      await patch('android', androidTargetOf(d.id, d.name))
      const r = await api('POST', kind === 'start' ? '/phone/start' : '/phone/stop', { name })
      if (r?.error) { message.error(r.error); setLog(r?.data?.log || r.error) }
    } catch (e: any) { message.error(e.message) } finally {
      setAvdBusy(''); loadDevices('android'); loadStatus()
    }
  }
  // USB 真机的两个动作。真机的生死不归我们管，但「插着却用不了」的两种状态能从这头救：
  // 授权弹窗错过了(unauthorized)、线松或 adbd 卡了(offline)。转无线之后它就成了远程设备，线可以拔。
  const usbAction = async (kind: 'reconnect' | 'wireless', d: PhoneDevice) => {
    setAvdBusy(d.id); setLog('')
    try {
      const r = kind === 'reconnect'
        ? await api('POST', '/phone/device/reconnect', { serial: d.id, state: d.state || '' })
        : await api('POST', '/phone/device/wireless', { serial: d.id })
      if (r?.error) { message.error(r.error); setLog(r?.data?.log || r.error) }
      else if (kind === 'wireless') {
        message.success(t('phone.usb.wirelessOk', { addr: r.data.address }))
        api('GET', '/phone/config').then((x) => { if (x?.data) setCfg((cc) => ({ ...cc, ...x.data })) }).catch(() => {})
      }
    } catch (e: any) { message.error(e.message) } finally {
      setAvdBusy(''); loadDevices('android'); loadStatus()
    }
  }
  const avdDelete = async (d: PhoneDevice) => {
    const name = avdNameOf(d)
    setAvdBusy(name)
    try {
      const r = await api('DELETE', '/phone/avd/' + encodeURIComponent(name))
      if (r?.error) message.error(r.error)
      else message.success(t('phone.avd.deleted', { name }))
    } catch (e: any) { message.error(e.message) } finally {
      setAvdBusy('')
      api('GET', '/phone/config').then((r) => { if (r?.data) setCfg((c) => ({ ...c, ...r.data })) }).catch(() => {})
      loadDevices('android'); loadStatus()
    }
  }

  const renderCard = (p: 'android' | 'ios') => {
    const c = cfg[p] as any
    const active = cfg.active === p
    const inst = plat[p].installed
    const sup = p === 'ios' ? plat.ios.supported : true
    const isA = p === 'android'
    const needAddr = !isA // Android 的目标一律从列表里点；远程设备走「＋远程设备」进来
    const canSS = (isA && c.mode === 'avd') || (!isA && c.mode === 'simulator')
    const sources = isA
      ? [{ label: t('phone.mode.avd'), value: 'avd' }, { label: t('phone.mode.device'), value: 'device' }, { label: t('phone.mode.network'), value: 'network' }]
      : [{ label: t('phone.ios.simulator'), value: 'simulator' }, { label: t('phone.ios.device'), value: 'device' }]
    const list = devs[p] || []
    const picked = list.some((d) => (c.address ? d.id === c.address : !!d.current)) || !!c.avd
    // 切来源要连地址一起清：每种来源的目标形状不同(模拟器=emulator-xxxx / 远程=host:port / 真机=USB serial)。
    // 不清的话，从「远程设备」切到「真机」会把 host:port 带过去，被后端判成串档丢弃→连不上。
    const changeSrc = (m: string) => patch(p, isA ? { mode: m, address: '', avd: '' } : { mode: m, address: '' })
    // 点一台设备＝换目标。Android 连来源一起换（地址形状决定怎么连），否则会被后端判成串档丢弃；
    // iOS 同理：选中真机时来源也要从「模拟器」挪走，不然 simctl 那条路根本不认这个 UDID。
    // 点一台设备＝换目标并当场连上。选完再让人找一个「连接」按钮是多余的一步——
    // 选它就是为了用它。网络目标尤其需要：不 adb connect 就永远是 offline。
    const pick = async (d: PhoneDevice) => {
      await patch(p, isA ? androidTargetOf(d.id, d.name)
        : { mode: d.kind === 'simulator' ? 'simulator' : 'device', address: d.id })
      if (!isA || (d.state || '') === 'stopped') return // 没跑起来的模拟器先等它启动
      try { await api('POST', '/phone/connect', {}) } catch {}
      loadStatus()
    }
    // 地址留空=后端用 adb 默认设备：那台由后端标 current，否则「默认单设备」下一台都不选中。
    const isPicked = (d: PhoneDevice) => (c.address ? d.id === c.address : !!d.current)
    return (
      <Card size="small" title={
        <Space align="center">
          <Switch aria-label={t('phone.platform.' + p)} checked={active} disabled={!sup || !!busy || !!installing} loading={installing === p} onChange={(on) => toggle(p, on)} />
          <b>{t('phone.platform.' + p)}</b>
          <Tag color={inst ? 'green' : 'default'}>{inst ? t('phone.installedTag') : t('phone.notInstalled')}</Tag>
          {p === 'ios' && !sup && <span style={dim}>{t('phone.iosMacOnly')}</span>}
        </Space>
      }>
        {!sup ? <p>{t('phone.iosUnsupported')}</p> : <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {/* Android 没有「来源」这一档：设备列表就是选择器，来源由所选设备的形状定
              （后端本来就按 serial 形状判）。两处并存时它们互相打架——选了「本机模拟器」，
              列表里却照样列着 USB 真机，而那个分段实际只控制「有没有启动按钮」。
              iOS 那边留着：模拟器与真机在 simctl/idb 是两条命令，不是同一份清单。 */}
          {!isA && (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <span style={dim}>{t('phone.source')}</span>
              <Segmented value={c.mode} onChange={(v) => changeSrc(v as string)} options={sources} />
            </Space>
          )}
          {/* 设备列表：一台机器上模拟器和真机常常同时挂着——两台都摆出来，点一下就换。
              从前这里只有一个 AutoComplete，下拉按框里已有的文字过滤：选中一台之后列表里
              就只剩它自己，另一台既看不见也选不了。 */}
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Space align="center" size={8}>
              <span style={dim}>{t('phone.devices')}</span>
              {/* 安静的行尾动作用 .tt-act：antd 的 size="small" 是 24px，手指档够不着(全站按钮不随 --ctl-h 长) */}
              <button type="button" className="tt-act" onClick={() => loadDevices(p)}>{t('phone.refreshDevices')}</button>
              {isA && (
                <>
                  <button type="button" className="tt-act" onClick={() => setCreateOpen(true)}>
                    <PlusIcon size={13} />{t('phone.avd.new')}
                  </button>
                  {/* 远程设备连上之前 adb 看不见它，列表里自然没有——所以它只能从这里进来 */}
                  <button type="button" className="tt-act" onClick={() => { setRemoteAddr(''); setRemoteOpen(true) }}>
                    <PlusIcon size={13} />{t('phone.remote.add')}
                  </button>
                </>
              )}
            </Space>
            {list.length === 0 ? <span style={dim}>{isA ? t('phone.devNone') : t('phone.devNoneIOS')}</span> : (
              <div className="tt-modes tt-devices">
                {list.map((d) => {
                  const why = devStateText(d, t)
                  // 只有本机模拟器有起停/删除；真机不归我们管生死，远程只能连和断。
                  const isAvd = isA && d.kind === 'avd'
                  const isNetRow = isA && d.kind === 'network'
                  const isUsb = isA && d.kind === 'usb'
                  const stuck = ['unauthorized', 'offline'].includes((d.state || '').toLowerCase())
                  const stopped = (d.state || '') === 'stopped'
                  const wait = avdBusy === avdNameOf(d)
                  // 每行自己说清楚现在什么状态：不就绪说原因，选中且连上了写「已连接」，
                  // 在跑的模拟器写「运行中」。底下那条状态灯只说当前这台，不必逐行猜。
                  const live = !why && isPicked(d) && st.connected ? t('phone.connected')
                    : !why && isAvd ? t('phone.avd.running') : ''
                  return (
                    <div key={d.id} className={`tt-devrow${isAvd || isNetRow || isUsb ? ' acts' : ''}`}>
                      <button type="button" className={`tt-mode${isPicked(d) ? ' on' : ''}`} onClick={() => pick(d)}>
                        <i className="radio" aria-hidden />
                        <span className="t"><DeviceIcon size={15} />{d.name}</span>
                        <span className="d">{d.id} · {devKindText(d, t)}
                          {why && <> · <em style={{ fontStyle: 'normal', color: 'var(--warn)' }}>{why}</em></>}
                          {live && <> · <em style={{ fontStyle: 'normal', color: 'var(--ok)' }}>{live}</em></>}
                        </span>
                      </button>
                      {isUsb && (
                        <span className="tt-devacts">
                          <button type="button" className="tt-act" disabled={!!avdBusy}
                            onClick={() => usbAction('reconnect', d)}>
                            {stuck ? t('phone.usb.reauth') : t('phone.usb.reconnect')}
                          </button>
                          {/* 转无线要先握上手才做得了：未授权/离线时这颗按了也是白按 */}
                          {!stuck && (
                            <button type="button" className="tt-act" disabled={!!avdBusy}
                              onClick={() => usbAction('wireless', d)}>
                              {avdBusy === d.id ? t('phone.usb.switching') : t('phone.usb.wireless')}
                            </button>
                          )}
                        </span>
                      )}
                      {isNetRow && (
                        <span className="tt-devacts">
                          <button type="button" className="tt-act" onClick={() => act('disconnect', '/phone/disconnect')}>
                            {t('phone.disconnect2')}
                          </button>
                        </span>
                      )}
                      {isAvd && (
                        <span className="tt-devacts">
                          {stopped ? (
                            <>
                              <button type="button" className="tt-act ok" disabled={!!avdBusy}
                                onClick={() => avdAction('start', d)}>
                                {wait ? t('phone.avd.starting') : t('phone.avd.start')}
                              </button>
                              {/* 删除是真删：连 ~/.android/avd/<名>.avd 里的应用和数据一起没 */}
                              <Popconfirm title={t('phone.avd.deleteAsk', { name: avdNameOf(d) })}
                                description={t('phone.avd.deleteWarn')} okButtonProps={{ danger: true }}
                                onConfirm={() => avdDelete(d)}>
                                <button type="button" className="tt-act danger" disabled={!!avdBusy}>
                                  {t('phone.avd.delete')}
                                </button>
                              </Popconfirm>
                            </>
                          ) : (
                            <button type="button" className="tt-act" disabled={!!avdBusy}
                              onClick={() => avdAction('stop', d)}>
                              {wait ? t('phone.avd.stopping') : t('phone.avd.stop')}
                            </button>
                          )}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </Space>
          {needAddr && (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <span style={dim}>{t('phone.addrManual')}</span>
              <Input value={c.address} onChange={(e) => editAddr(p, e.target.value)} onBlur={blurPersist} onPressEnter={blurPersist}
                style={{ maxWidth: 380 }} placeholder={isA ? t('phone.addrPlaceholder') : t('phone.addrPlaceholderIOS')} />
              <span style={dim}>{isA ? (c.mode === 'network' ? t('phone.addrHelpRemote') : t('phone.addrHelpDevice')) : t('phone.addrHelpIOS')}</span>
            </Space>
          )}
          {/* 动作条 + 状态：仅激活卡片（动作作用于当前激活平台） */}
          {active ? (
            <>
              {/* Android：一台设备的所有动作都贴在它自己那行上，底下只剩「现在连的是谁」。
                  原来那排「一键连接 / 启动 / 停止 / 连接 / 断开 / 测试连接」说不清彼此关系，
                  而且启动/停止作用于「当前选中的那台」——一台都没选中时尤其费解。 */}
              {isA ? (
                <div className={`tt-cstate${st.connected ? ' ok' : (picked ? ' warn' : '')}`}>
                  <i className="d" aria-hidden />
                  <span style={{ flex: 1, minWidth: 0 }}>
                    {!picked ? t('phone.pickToStart')
                      : st.connected ? (st.device || t('phone.connected'))
                      : (st.error || t('phone.disconnected'))}
                  </span>
                  {picked && (
                    <button type="button" className="tt-act" disabled={busy === 'auto'}
                      onClick={() => act('auto', '/phone/auto')}>
                      {busy === 'auto' ? t('phone.retrying') : t('phone.retry')}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <Space wrap>
                    <Button type="primary" loading={busy === 'auto'} onClick={() => act('auto', '/phone/auto')}>{t('phone.auto')}</Button>
                    {canSS && <Button loading={busy === 'start'} disabled={st.running === true} onClick={() => act('start', '/phone/start')}>{t('phone.avd.start')}</Button>}
                    {canSS && <Button loading={busy === 'stop'} disabled={st.running === false} onClick={() => act('stop', '/phone/stop')}>{t('phone.avd.stop')}</Button>}
                    <Button loading={busy === 'test'} onClick={() => act('test', '/phone/test')}>{t('phone.test')}</Button>
                  </Space>
                  <Space wrap size={8}>
                    <Tag color={st.connected ? 'green' : (st.error ? 'red' : 'default')}>
                      {st.connected ? (st.device || t('phone.connected')) : (st.error || t('phone.disconnected'))}
                    </Tag>
                  </Space>
                </>
              )}
              {/* 升级后可能还留着一个旧的 redroid 容器在跑：ttmux 已经不管它了，说一声，删不删是用户的事 */}
              {isA && st.legacyRedroid && (
                <div className="tt-cstate warn">
                  <i className="d" aria-hidden />
                  <span>{t('phone.legacyRedroid')} <code>docker rm -f ttmux-redroid</code></span>
                </div>
              )}
            </>
          ) : <span style={dim}>{t('phone.enableHint')}</span>}
        </Space>}
      </Card>
    )
  }

  if (readState) return readState
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {renderCard('android')}
      {renderCard('ios')}
      <Modal open={remoteOpen} title={t('phone.remote.title')} okText={t('phone.remote.connect')}
        onCancel={() => setRemoteOpen(false)}
        onOk={async () => {
          const addr = remoteAddr.trim()
          if (!addr.includes(':')) { message.warning(t('phone.remote.needPort')); return }
          setRemoteOpen(false)
          await persist({ ...cfgRef.current, active: 'android', android: { ...cfgRef.current.android, mode: 'network', address: addr, avd: '' } })
          await act('connect', '/phone/connect')
          loadDevices('android')
        }}>
        <Input value={remoteAddr} onChange={(e) => setRemoteAddr(e.target.value)} placeholder={t('phone.addrPlaceholder')}
          onPressEnter={(e) => (e.target as HTMLInputElement).blur()} />
        <div className="tt-hint">{t('phone.remote.help')}</div>
      </Modal>
      <AvdCreateDrawer open={createOpen} onClose={() => setCreateOpen(false)}
        onCreated={() => { loadDevices('android'); loadStatus() }} />
      {log && <pre style={{ maxHeight: 160, overflow: 'auto', margin: 0, padding: 8, fontSize: 11, lineHeight: 1.5, background: 'var(--bg-base)', border: '1px solid var(--border-subtle)', borderRadius: 6, whiteSpace: 'pre-wrap' }}>{log}</pre>}
    </Space>
  )
}

// 关于页：Logo / roam 版本号 / 检测更新（跳 release 页）/ GitHub 仓库链接
