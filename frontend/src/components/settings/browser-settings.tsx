import { useSettingsRead } from './settings-read'
// Chrome(浏览器镜像)启动配置：模式 / 窗口尺寸 / 全屏 / 缩放 / profile(data-dir) / 可执行路径。
// 持久化到后端 browser-config.json。
//
// 改完即存（开关与分段即时、输入框失焦），不给「保存」按钮——设置页里每一行都是改完即存，
// 单这一页留个保存按钮，用户就得记住哪一页要按、哪一页不用。尺寸与 profile 要新起的 Chrome
// 才吃得到，所以「重启 Chrome」是这一页的**页级动作**，摆在页头（见 registry）。
import { useEffect, useRef, useState } from 'react'
import { App as AntApp, Input, Segmented, Space, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'

const DEFAULTS = { headless: 'auto', windowSize: '1920,1080', fullscreen: true, scale: '2', profile: '/tmp/ttmux-chrome', bin: '' }

export function BrowserSettings({ onRestartReady }: { onRestartReady?: (run: (() => Promise<void>) | null) => void }) {
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const [cfg, setCfg] = useState<any>(DEFAULTS)
  const [pendingRestart, setPendingRestart] = useState(false)
  const writes = useRef<Promise<unknown>>(Promise.resolve())
  const cfgRef = useRef(cfg)
  useEffect(() => { cfgRef.current = cfg }, [cfg])
  const readState = useSettingsRead(() => api('GET', '/browser/config').then((r) => { setCfg({ ...DEFAULTS, ...r.data }) }))

  const persist = (next: any) => {
    const write = writes.current.catch(() => {}).then(() => api('PUT', '/browser/config', next))
    writes.current = write
    return write.then(() => setPendingRestart(true))
  }
  useEffect(() => {
    onRestartReady?.(readState ? null : () => new Promise<void>(resolve => {
      modal.confirm({
        title: t('settings.browserRelaunch'), content: t('settings.browserRestartConfirm'),
        onCancel: () => resolve(),
        onOk: async () => {
          try {
            await persist(cfgRef.current)
            const r = await api('POST', '/browser/relaunch')
            if (r?.data?.attached) message.warning(t('settings.browserAttached'))
            else { setPendingRestart(false); message.success(t('settings.browserRelaunched')) }
            resolve()
          } catch (e: any) { message.error(e.message); throw e }
        },
      })
    }))
    return () => onRestartReady?.(null)
  }, [!!readState, onRestartReady, t])
  // 输入框：只改本地状态，失焦才写——每敲一个字发一次 PUT 既吵又会打乱光标
  const edit = (k: string, v: any) => setCfg((c: any) => { const n = { ...c, [k]: v }; cfgRef.current = n; return n })
  const commit = () => { void persist(cfgRef.current).catch((e: any) => message.error(e.message)) }
  const set = (k: string, v: any) => { const n = { ...cfgRef.current, [k]: v }; cfgRef.current = n; setCfg(n); void persist(n).catch((e: any) => message.error(e.message)) }

  const dim = { color: 'var(--text-dim)', fontSize: 'var(--fs-meta)' }
  if (readState) return readState
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {pendingRestart && <span role="status">{t('settings.browserPendingRestart')}</span>}
      <Space align="center" wrap>
        <span>{t('settings.browserMode')}</span>
        <Segmented
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
        <Input addonBefore={t('settings.browserWindow')} value={cfg.windowSize} placeholder={t('settings.browserWindowPlaceholder')}
          onChange={(e) => edit('windowSize', e.target.value)} onBlur={commit} onPressEnter={commit} />
        <Space align="center">
          <Switch checked={!!cfg.fullscreen} onChange={(v) => set('fullscreen', v)} />
          <span>{t('settings.browserFullscreen')}</span>
          <span style={dim}>{t('settings.browserFullscreenHelp')}</span>
        </Space>
        <Input addonBefore={t('settings.browserScale')} value={cfg.scale} placeholder={t('settings.browserScalePlaceholder')}
          onChange={(e) => edit('scale', e.target.value)} onBlur={commit} onPressEnter={commit} />
        <Input addonBefore={t('settings.browserProfile')} value={cfg.profile} placeholder={t('settings.browserProfilePlaceholder')}
          onChange={(e) => edit('profile', e.target.value)} onBlur={commit} onPressEnter={commit} />
        <span style={dim}>{t('settings.browserProfileHelp')}</span>
        <Input addonBefore={t('settings.browserBin')} value={cfg.bin} placeholder={t('common.optional')}
          onChange={(e) => edit('bin', e.target.value)} onBlur={commit} onPressEnter={commit} />
      </Space>
    </Space>
  )
}
