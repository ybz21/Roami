// 会话内存上限：给每个会话套一层天花板，让失控的 agent 只杀死自己。
//
// 值落在 ttmux 的全局 env 文件（ROAM_SESSION_MEM_MAX），CLI 建会话时读它，
// 用 systemctl set-property 设到那个会话的 cgroup 上。
// 见 docs/design/reliability/memory-guard.html。
import { useEffect, useState } from 'react'
import { App as AntApp, Button, Checkbox, Input, Radio, Space, Tag } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import { humanBytes } from '../sessions/session-memory'
import './memory-recovery.css'

const KEY = 'ROAM_SESSION_MEM_MAX'

/** 预设档：按整机内存的比例给，而不是拍一个固定数——8G 的本子和 128G 的工作站不该同一个值。 */
const PRESETS = ['', '4G', '8G', '12G', '16G', 'off']

export function MemoryGuardSettings() {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [value, setValue] = useState('')
  const [custom, setCustom] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    api('GET', '/env')
      .then((list: any) => {
        const hit = (Array.isArray(list) ? list : []).find((kv: any) => kv?.key === KEY)
        const v = (hit?.value || '').trim()
        setValue(v)
        if (v && !PRESETS.includes(v)) setCustom(v)
      })
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [])

  const save = async (v: string) => {
    setBusy(true)
    try {
      await api('PUT', '/env', { key: KEY, value: v })
      setValue(v)
      message.success(t('set.mem.saved'))
    } catch (e: any) {
      message.error(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!loaded) return null
  const isCustom = !!value && !PRESETS.includes(value)

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Radio.Group
        value={isCustom ? 'custom' : value}
        disabled={busy}
        onChange={(e) => {
          const v = e.target.value
          if (v === 'custom') { setCustom(custom || '8G'); return }
          void save(v)
        }}
      >
        <Space direction="vertical" size={4}>
          <Radio value="">
            {t('set.mem.auto')} <Tag style={{ marginInlineStart: 6 }}>{t('set.mem.autoHint')}</Tag>
          </Radio>
          {['4G', '8G', '12G', '16G'].map((p) => (
            <Radio key={p} value={p}>{p}</Radio>
          ))}
          <Radio value="custom">{t('set.mem.custom')}</Radio>
          <Radio value="off">
            {t('set.mem.off')} <Tag color="warning" style={{ marginInlineStart: 6 }}>{t('set.mem.offHint')}</Tag>
          </Radio>
        </Space>
      </Radio.Group>

      {(isCustom || custom) && (
        <Space.Compact style={{ width: '100%', maxWidth: 320 }}>
          <Input
            value={custom}
            placeholder={t('set.mem.placeholder')}
            onChange={(e) => setCustom(e.target.value)}
            onPressEnter={() => custom.trim() && save(custom.trim())}
          />
          <Button type="primary" loading={busy} disabled={!custom.trim()} onClick={() => save(custom.trim())}>
            {t('env.set')}
          </Button>
        </Space.Compact>
      )}

      <div style={{ fontSize: 'var(--fs-meta)', color: 'var(--text-dimmer)', lineHeight: 1.7 }}>
        {t('set.mem.note')}
      </div>
      <MemoryRecoverySettings />
    </Space>
  )
}

type Compression = { zram: boolean; zswap: boolean; swapTotal: number; swapFree: number; original: number; memory: number; saved: number }

export function MemoryRecoverySettings() {
  const { t } = useI18n(), { message } = AntApp.useApp()
  const [status, setStatus] = useState<Compression | null>(null)
  const [flags, setFlags] = useState<Record<string, boolean>>({})
  const [failed, setFailed] = useState(false), [busy, setBusy] = useState(false)
  const load = async () => {
    setFailed(false)
    try {
      const [compression, entries] = await Promise.all([api('GET', '/memory/compression'), api('GET', '/env')])
      const values = Object.fromEntries((Array.isArray(entries) ? entries : []).map((e: any) => [e.key, e.value]))
      setFlags(Object.fromEntries(['ROAM_MEMORY_RECLAIM', 'ROAM_MEMORY_COMPACT'].map(key => [key, !['off', '0', 'false'].includes(String(values[key] || '').toLowerCase())])))
      setStatus(compression)
    } catch { setFailed(true) }
  }
  useEffect(() => { void load() }, [])
  const save = async (key: string, value: boolean) => {
    setBusy(true)
    try { await api('PUT', '/env', { key, value: value ? 'on' : 'off' }); setFlags(f => ({ ...f, [key]: value })) }
    catch { message.error(t('session.mem.actionFailed')) }
    finally { setBusy(false) }
  }
  return <div className="tt-memory-recovery-settings">
    <strong>{t('set.mem.recovery')}</strong>
    {failed ? <div role="alert">{t('set.mem.statusFailed')} <button type="button" className="tt-act" onClick={() => void load()}>{t('inbox.retry')}</button></div> : !status ? <span>{t('common.loading')}</span> : <>
      <Checkbox className="tt-memory-option" disabled={busy} checked={flags.ROAM_MEMORY_RECLAIM} onChange={e => void save('ROAM_MEMORY_RECLAIM', e.target.checked)}>{t('set.mem.autoReclaim')}</Checkbox>
      <Checkbox className="tt-memory-option" disabled={busy} checked={flags.ROAM_MEMORY_COMPACT} onChange={e => void save('ROAM_MEMORY_COMPACT', e.target.checked)}>{t('set.mem.autoCompact')}</Checkbox>
      <p>{t('set.mem.compactHint')}</p>
      <div><Tag color={status.zram || status.zswap ? 'success' : 'warning'}>{t(status.zram || status.zswap ? 'set.mem.compressionOn' : 'set.mem.compressionOff', { backend: status.zram ? 'zram' : 'zswap' })}</Tag></div>
      <span>{t('set.mem.swapRoom', { free: humanBytes(status.swapFree), total: humanBytes(status.swapTotal) })}</span>
      {status.zram && <span>{t('set.mem.compressionStats', { original: humanBytes(status.original), memory: humanBytes(status.memory), saved: humanBytes(status.saved) })}</span>}
      {!status.zram && !status.zswap && <>
        <p>{t('set.mem.setupHint')}</p>
        <Button href={nodeApi('/memory/setup-script')} download="roami-zram-setup.sh">{t('set.mem.downloadSetup')}</Button>
        <code>sudo bash roami-zram-setup.sh</code>
      </>}
    </>}
  </div>
}
