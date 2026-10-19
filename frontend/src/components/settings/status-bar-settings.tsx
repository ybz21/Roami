import { useSettingsRead } from './settings-read'
// 状态条设置（20 设计 §05「用户看得见两类格的区别」）。
//
// 条上看不出哪几格是插件的——那是刻意的。但设置里必须看得出，不然你没法回答
// 「这个 61°C 是谁报的、准不准、能不能关」。所以这一页按**来源**分组，
// 插件那组还标出来自哪个插件、是随二进制走的内置还是用户装的第三方。
import { useState } from 'react'
import { Space, Switch, Tag } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { usePreferences } from '../../preferences'
import { pluginCells, type PluginRecord } from '../shell/status-registry'

/** 系统 provider 与它们注册的格——与 shell/status-system.ts 一一对应 */
const SYSTEM_PROVIDERS = ['roam.core', 'roam.git', 'roam.tasks'] as const

export function StatusBarSettings() {
  const { t, locale } = useI18n()
  const [prefs, setPrefs] = usePreferences()
  const [plugins, setPlugins] = useState<PluginRecord[]>([])

  const readState = useSettingsRead(() => api('GET', '/plugins').then((r) => setPlugins(Array.isArray(r) ? r : r?.data || [])))

  const bar = prefs.statusBar
  const hidden = new Set(bar.hidden)
  const optIn = new Set(bar.optIn)

  const toggleHidden = (id: string, on: boolean) => {
    const next = new Set(hidden)
    if (on) next.delete(id)
    else next.add(id)
    setPrefs({ statusBar: { ...bar, hidden: [...next] } })
  }
  const toggleOptIn = (id: string, on: boolean) => {
    const next = new Set(optIn)
    if (on) next.add(id)
    else next.delete(id)
    setPrefs({ statusBar: { ...bar, optIn: [...next] } })
  }

  // 按 provider 聚合：一个插件的几格一起开关，逐格开关会让这一页比状态条还长
  const byPlugin = new Map<string, { name: string; builtin: boolean; count: number }>()
  for (const spec of pluginCells(plugins, locale).specs) {
    const p = plugins.find((x) => x.manifest.id === spec.provider)
    const name = p?.manifest.displayName?.[locale] || p?.manifest.displayName?.['zh-CN'] || spec.provider
    const cur = byPlugin.get(spec.provider)
    if (cur) cur.count += 1
    else byPlugin.set(spec.provider, { name, builtin: !!spec.builtin, count: 1 })
  }

  const dim = { color: 'var(--text-dim)', fontSize: 'var(--fs-meta)' }
  const hint = { color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)' }
  const row = {
    display: 'flex', alignItems: 'center', gap: 'var(--sp-2)',
    padding: '7px 0', borderTop: '1px solid var(--border-subtle)',
  } as const
  const group = {
    fontSize: 'var(--fs-micro)', letterSpacing: '.1em', textTransform: 'uppercase' as const,
    color: 'var(--text-dimmer)', fontWeight: 600, marginTop: 'var(--sp-3)',
  }

  if (readState) return readState
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', maxWidth: 460 }}>
      <Space align="center" wrap>
        <Switch checked={bar.enabled} onChange={(v) => setPrefs({ statusBar: { ...bar, enabled: v } })} />
        <span style={dim}>{t('status.enable')}</span>
      </Space>

      <div style={{ opacity: bar.enabled ? 1 : 0.5 }}>
        <div style={group}>{t('status.groupSystem')}</div>
        {SYSTEM_PROVIDERS.map((id) => (
          <div key={id} style={row}>
            <span>{t('status.provider.' + id.split('.')[1])}</span>
            <span className="mono" style={hint}>{id}</span>
            <Switch size="small" style={{ marginLeft: 'auto' }} disabled={!bar.enabled}
              checked={!hidden.has(id)} onChange={(v) => toggleHidden(id, v)} />
          </div>
        ))}

        <div style={group}>{t('status.groupPlugin')}</div>
        {!byPlugin.size && <div style={{ ...hint, padding: '7px 0' }}>{t('status.noPluginCells')}</div>}
        {[...byPlugin].map(([id, p]) => (
          <div key={id} style={row}>
            <span>{p.name}</span>
            <span style={hint}>{t('status.itemsN', { n: p.count })}</span>
            <Tag style={{ margin: 0 }}>{p.builtin ? t('status.builtin') : t('status.thirdParty')}</Tag>
            <span className="mono" style={hint}>{id}</span>
            <Switch size="small" style={{ marginLeft: 'auto' }} disabled={!bar.enabled}
              // 内置插件跟系统格一样默认就在，只能隐藏；第三方要显式打开
              checked={p.builtin ? !hidden.has(id) : optIn.has(id) && !hidden.has(id)}
              onChange={(v) => (p.builtin ? toggleHidden(id, v) : toggleOptIn(id, v))} />
          </div>
        ))}
        <div style={{ ...hint, marginTop: 'var(--sp-2)' }}>{t('status.optInHint')}</div>
      </div>
    </Space>
  )
}
