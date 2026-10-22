import { useSettingsRead } from './settings-read'
// Chrome(浏览器镜像)启动配置：模式 / 窗口尺寸 / 全屏 / 缩放 / profile(data-dir) / 可执行路径。
// 持久化到后端 browser-config.json。
//
// 改完即存（开关与分段即时、输入框失焦），不给「保存」按钮——设置页里每一行都是改完即存，
// 单这一页留个保存按钮，用户就得记住哪一页要按、哪一页不用。尺寸与 profile 要新起的 Chrome
// 才吃得到，所以「重启 Chrome」是这一页的**页级动作**，摆在页头（见 registry）。
import { useEffect, useRef, useState } from 'react'
import { App as AntApp, Input, InputNumber, Segmented, Space, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { pollWhileVisible } from '../../visible-poll'

const DEFAULTS = { headless: 'auto', windowSize: '1920,1080', fullscreen: true, scale: '2', profile: '/tmp/ttmux-chrome', bin: '', autoRecover: true, tabPolicies: { agent: { maxTabs: 20, sleepAfterSeconds: 120, closeAfterSeconds: 600 }, human: { maxTabs: 0, sleepAfterSeconds: 1800, closeAfterSeconds: 0 } } }

export function BrowserSettings({ onRestartReady }: { onRestartReady?: (run: (() => Promise<void>) | null) => void }) {
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const [cfg, setCfg] = useState<any>(DEFAULTS)
  const [health, setHealth] = useState<{ alive: boolean; restarting?: boolean } | null>(null)
  const [restartBusy, setRestartBusy] = useState(false)
  const [pendingRestart, setPendingRestart] = useState(false)
  const writes = useRef<Promise<unknown>>(Promise.resolve())
  const cfgRef = useRef(cfg)
  useEffect(() => { cfgRef.current = cfg }, [cfg])
  const readState = useSettingsRead(() => api('GET', '/browser/config').then((r) => { setCfg({ ...DEFAULTS, ...r.data, tabPolicies: {
    agent: { ...DEFAULTS.tabPolicies.agent, ...r.data.tabPolicies?.agent },
    human: { ...DEFAULTS.tabPolicies.human, ...r.data.tabPolicies?.human },
  } }) }))

  const persist = (next: any) => {
    const write = writes.current.catch(() => {}).then(() => api('PUT', '/browser/config', next))
    writes.current = write
    return write.then(() => setPendingRestart(true))
  }
  useEffect(() => {
    onRestartReady?.(readState ? null : () => new Promise<void>((resolve, reject) => {
      modal.confirm({
        title: t('settings.browserRelaunch'), content: t('settings.browserRestartConfirm'),
        onCancel: () => resolve(),
        onOk: async () => {
          setRestartBusy(true)
          try {
            await persist(cfgRef.current)
            const r = await api('POST', '/browser/relaunch')
            if (r?.data?.ok !== true) throw new Error(t('settings.browserRestartFailed'))
            setHealth({ alive: true })
            setPendingRestart(false); message.success(t('settings.browserRelaunched'))
            resolve()
          } catch (e: any) {
            const error = e.apiError?.code === 'RELAUNCH_FAILED' ? new Error(t('settings.browserRestartFailed')) : e
            reject(error); throw error
          } finally { setRestartBusy(false) }
        },
      })
    }))
    return () => onRestartReady?.(null)
  }, [!!readState, onRestartReady, t])
  useEffect(() => {
    const poll = pollWhileVisible(async signal => {
      try { const response = await api('GET', '/browser/health', undefined, { signal }); if (!signal.aborted) setHealth(response.data) }
      catch (error) { if (!signal.aborted) setHealth(null); throw error }
    }, 5000)
    return () => poll.stop()
  }, [])
  const setRecovery = (value: boolean) => {
    const previous = cfgRef.current
    const next = { ...previous, autoRecover: value }
    cfgRef.current = next; setCfg(next)
    const write = writes.current.catch(() => {}).then(() => api('PUT', '/browser/config', next))
    writes.current = write
    void write.catch((e: any) => {
      if (cfgRef.current === next) { cfgRef.current = previous; setCfg(previous) }
      message.error(e.message)
    })
  }
  const editPolicy = (origin: 'human' | 'agent', field: 'maxTabs' | 'sleepAfterSeconds' | 'closeAfterSeconds', value: number | null) => {
    const previous = cfgRef.current
    const policy = { ...previous.tabPolicies[origin], [field]: (value || 0) * (field === 'maxTabs' ? 1 : 60) }
    const next = { ...previous, tabPolicies: { ...previous.tabPolicies, [origin]: policy } }
    cfgRef.current = next; setCfg(next)
  }
  const commitPolicies = () => {
    const next = cfgRef.current
    if (Object.values(next.tabPolicies).some((policy: any) => policy.closeAfterSeconds && policy.sleepAfterSeconds && policy.closeAfterSeconds < policy.sleepAfterSeconds)) {
      message.error(t('settings.browserPolicyOrder')); return
    }
    const write = writes.current.catch(() => {}).then(() => api('PUT', '/browser/config', next))
    writes.current = write
    void write.catch((error: any) => message.error(error.message))
  }
  // 输入框：只改本地状态，失焦才写——每敲一个字发一次 PUT 既吵又会打乱光标
  const edit = (k: string, v: any) => setCfg((c: any) => { const n = { ...c, [k]: v }; cfgRef.current = n; return n })
  const commit = () => { void persist(cfgRef.current).catch((e: any) => message.error(e.message)) }
  const set = (k: string, v: any) => { const n = { ...cfgRef.current, [k]: v }; cfgRef.current = n; setCfg(n); void persist(n).catch((e: any) => message.error(e.message)) }

  const dim = { color: 'var(--text-dim)', fontSize: 'var(--fs-meta)' }
  if (readState) return readState
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <span role="status">{t(restartBusy || health?.restarting ? 'settings.browserRestarting' : health?.alive ? 'settings.browserRunning' : health ? 'settings.browserStopped' : 'settings.browserHealthUnknown')}</span>
      <Space align="center" wrap>
        <Switch aria-label={t('settings.browserAutoRecover')} checked={!!cfg.autoRecover} disabled={restartBusy} onChange={setRecovery} />
        <span>{t('settings.browserAutoRecover')}</span>
        <span style={dim}>{t('settings.browserAutoRecoverHelp')}</span>
      </Space>
      <section aria-label={t('settings.browserTabPolicies')}>
        <h3 style={{ fontSize: 'var(--fs-sm)', margin: 'var(--sp-4) 0 var(--sp-3)' }}>{t('settings.browserTabPolicies')}</h3>
        {(['human', 'agent'] as const).map(origin => <Space key={origin} direction="vertical" size="small" style={{ marginBottom: 'var(--sp-4)', display: 'flex' }}>
          <span>{t(`browser.group.${origin}`)}</span>
          <Space wrap>
            <label>{t('settings.browserMaxTabs')} <InputNumber min={0} max={1000} precision={0} aria-label={`${t(`browser.group.${origin}`)} ${t('settings.browserMaxTabs')}`}
              value={cfg.tabPolicies[origin].maxTabs} onChange={value => editPolicy(origin, 'maxTabs', value)} onBlur={commitPolicies} onPressEnter={commitPolicies} /></label>
            <label>{t('settings.browserSleepAfter')} <InputNumber min={0} max={10080} precision={0} aria-label={`${t(`browser.group.${origin}`)} ${t('settings.browserSleepAfter')}`}
              value={cfg.tabPolicies[origin].sleepAfterSeconds / 60} onChange={value => editPolicy(origin, 'sleepAfterSeconds', value)} onBlur={commitPolicies} onPressEnter={commitPolicies} /></label>
            <label>{t('settings.browserCloseAfter')} <InputNumber min={0} max={10080} precision={0} aria-label={`${t(`browser.group.${origin}`)} ${t('settings.browserCloseAfter')}`}
              value={cfg.tabPolicies[origin].closeAfterSeconds / 60} onChange={value => editPolicy(origin, 'closeAfterSeconds', value)} onBlur={commitPolicies} onPressEnter={commitPolicies} /></label>
          </Space>
        </Space>)}
        <span style={dim}>{t('settings.browserPolicyHelp')}</span>
      </section>
      {pendingRestart && <span role="status">{t('settings.browserPendingRestart')}</span>}
      <Space align="center" wrap>
        <span>{t('settings.browserMode')}</span>
        <Segmented
          disabled={restartBusy}
          value={cfg.headless || 'auto'}
          onChange={(v) => set('headless', v)}
          options={[
            { value: 'auto', label: t('settings.browserModeAuto') },
            { value: 'on', label: t('settings.browserModeHeadless') },
            { value: 'off', label: t('settings.browserModeHeadful') },
          ]}
        />
        <span style={dim}>{t('settings.browserModeHelp')}</span>
      </Space>
      <Space direction="vertical" size="small" style={{ width: '100%', maxWidth: 560 }}>
        <Input disabled={restartBusy} addonBefore={t('settings.browserWindow')} value={cfg.windowSize} placeholder={t('settings.browserWindowPlaceholder')}
          onChange={(e) => edit('windowSize', e.target.value)} onBlur={commit} onPressEnter={commit} />
        <Space align="center">
          <Switch disabled={restartBusy} checked={!!cfg.fullscreen} onChange={(v) => set('fullscreen', v)} />
          <span>{t('settings.browserFullscreen')}</span>
          <span style={dim}>{t('settings.browserFullscreenHelp')}</span>
        </Space>
        <Input disabled={restartBusy} addonBefore={t('settings.browserScale')} value={cfg.scale} placeholder={t('settings.browserScalePlaceholder')}
          onChange={(e) => edit('scale', e.target.value)} onBlur={commit} onPressEnter={commit} />
        <Input disabled={restartBusy} addonBefore={t('settings.browserProfile')} value={cfg.profile} placeholder={t('settings.browserProfilePlaceholder')}
          onChange={(e) => edit('profile', e.target.value)} onBlur={commit} onPressEnter={commit} />
        <span style={dim}>{t('settings.browserProfileHelp')}</span>
        <Input disabled={restartBusy} addonBefore={t('settings.browserBin')} value={cfg.bin} placeholder={t('common.optional')}
          onChange={(e) => edit('bin', e.target.value)} onBlur={commit} onPressEnter={commit} />
      </Space>
    </Space>
  )
}
