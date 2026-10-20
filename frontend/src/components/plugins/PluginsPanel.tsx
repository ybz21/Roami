import { useCallback, useEffect, useMemo, useState } from 'react'
import { nodeApi } from '../cluster/node-url'
import {
  Alert, Button, Card, Checkbox, Descriptions, Divider, Empty, Form, Input, List, Modal, Popconfirm, Select,
  Space, Spin, Switch, Table, Tabs, Tag, Typography, Upload, message,
} from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import HostMonitorPanel from './HostMonitorPanel'
import CronPanel from './CronPanel'
import KeepalivePanel from './KeepalivePanel'
import MobileSubPage from '../MobileSubPage'
import { useLayout } from '../../layout'
import { pollWhileVisible } from '../../visible-poll'
import { GearIcon, PlugIcon, SearchIcon, UploadIcon } from '../../icons'
import './plugins.css'

// 有宿主侧内置面板的插件(v1 插件无自定义前端,面板由宿主按 id 挂载)
const HOST_MONITOR_ID = 'roam.host-monitor'
const CRON_ID = 'roam.cron'
const KEEPALIVE_ID = 'roam.keepalive'

type LocaleText = Record<string, string> | undefined

type ConfigField = {
  key: string
  group?: string
  title?: LocaleText
  description?: LocaleText
  secret?: boolean
  options?: string[]
  placeholder?: string
}

type ConfigGroup = {
  key: string
  title?: LocaleText
  description?: LocaleText
}

type Manifest = {
  id: string
  name: string
  version: string
  displayName?: LocaleText
  description?: LocaleText
  runtime?: { kind?: string; resident?: boolean }
  permissions?: Record<string, any>
  contributes?: {
    commands?: { id: string; title?: LocaleText }[]
    notificationSinks?: { id: string; events?: string[] }[]
    configGroups?: ConfigGroup[]
    configFields?: ConfigField[]
  }
}

type RegisteredPlugin = { manifest: Manifest; enabled: boolean; installed: string }

type AuditEntry = {
  time: string; plugin: string; actor: string; action: string
  target?: string; decision: string; result?: string
}

function lt(text: LocaleText, locale: string): string {
  if (!text) return ''
  return text[locale] || text['zh-CN'] || Object.values(text)[0] || ''
}

export default function PluginsPanel({ initialId, onSelect }: { initialId?: string; onSelect?: (id: string) => void } = {}) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const [plugins, setPlugins] = useState<RegisteredPlugin[]>([])
  const [daemon, setDaemon] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [query, setQuery] = useState('')
  const [saving, setSaving] = useState('')
  const [selected, setSelected] = useState(initialId || '')
  const [detailTab, setDetailTab] = useState<string>()
  const [installOpen, setInstallOpen] = useState(false)

  const reload = useCallback(async () => {
    setError(false)
    try {
      const rows: RegisteredPlugin[] = await api('GET', '/plugins')
      setPlugins(rows || [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    const poll = pollWhileVisible(async signal => {
      const status = await api('GET', '/plugin/status', undefined, { signal })
      if (!signal.aborted) setDaemon(!!status?.daemon)
    }, 5000)
    return poll.stop
  }, [])
  useEffect(() => { setSelected(initialId || '') }, [initialId])

  const current = useMemo(() => plugins.find(p => p.manifest.id === selected), [plugins, selected])
  const name = (p: RegisteredPlugin) => lt(p.manifest.displayName, locale) || p.manifest.name
  const filtered = plugins.filter(p => `${name(p)} ${p.manifest.id} ${lt(p.manifest.description, locale)}`.toLowerCase().includes(query.trim().toLowerCase()))
  const open = (id: string, tab?: string) => {
    setDetailTab(tab)
    setSelected(id)
    onSelect?.(id)
  }
  const close = () => { setSelected(''); onSelect?.('') }
  const toggle = async (p: RegisteredPlugin, enabled: boolean) => {
    if (saving) return
    setSaving(p.manifest.id)
    try {
      await api('POST', `/plugins/${encodeURIComponent(p.manifest.id)}/${enabled ? 'enable' : 'disable'}`)
      setPlugins(rows => rows.map(row => row.manifest.id === p.manifest.id ? { ...row, enabled } : row))
      message.success(t(enabled ? 'plugins.enabled' : 'plugins.disabled'))
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSaving('')
    }
  }
  const detail = current && <PluginDetail key={`${current.manifest.id}/${detailTab || ''}`} plugin={current} initialTab={detailTab} locale={locale} t={t}
    onChanged={() => { close(); void reload() }} />

  return (
    <section className="tt-capability-catalog tt-plugin-catalog" data-kind="plugins">
      <div className="tt-capability-toolbar">
        <Input prefix={<SearchIcon size={16} />} aria-label={t('plugins.search')} placeholder={t('plugins.search')}
          value={query} onChange={event => setQuery(event.target.value)} allowClear />
        <div className="tt-capability-toolbar-actions">
          <Button type="primary" icon={<UploadIcon size={16} />} onClick={() => setInstallOpen(true)}>{t('plugins.install')}</Button>
        </div>
      </div>
      {daemon === false && <Alert className="tt-plugin-alert" type="warning" showIcon message={t('plugins.daemonStopped')} />}
      {error && <Alert className="tt-plugin-alert" type="error" showIcon message={t('plugins.loadFailed')}
        action={<Button onClick={() => { void reload() }}>{t('agent.retry')}</Button>} />}
      {loading ? <div className="tt-plugin-loading"><Spin /></div>
        : !filtered.length ? !error && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t(query.trim() ? 'plugins.noResults' : 'plugins.empty')} />
          : <div className="tt-capability-list">
            {filtered.map(plugin => <article className="tt-capability-row" key={plugin.manifest.id} aria-label={name(plugin)}>
              <div className="tt-capability-cardhead">
                <span className="tt-capability-icon"><PlugIcon size={22} /></span>
                <span className="tt-capability-source">{t('capabilities.source.' + ((plugin.manifest.runtime?.kind || 'builtin') === 'builtin' ? 'builtin' : 'managed'))}</span>
                <div className="tt-capability-state"><Switch size="small" aria-label={t('agent.capabilities.enable', { name: name(plugin) })}
                  checked={plugin.enabled} disabled={!!saving} loading={saving === plugin.manifest.id} onChange={enabled => { void toggle(plugin, enabled) }} /></div>
              </div>
              <div className="tt-plugin-cardname"><button type="button" className="tt-capability-open" onClick={() => open(plugin.manifest.id)}><strong>{name(plugin)}</strong></button><span>{plugin.manifest.version}</span></div>
              <p className="tt-capability-description">{lt(plugin.manifest.description, locale)}</p>
              <div className="tt-capability-cardfooter">
                <button type="button" className="tt-act" onClick={() => open(plugin.manifest.id)}>{t('plugins.details')}</button>
                {!!plugin.manifest.contributes?.configFields?.length && <button type="button" className="tt-act" onClick={() => open(plugin.manifest.id, 'config')}><GearIcon size={14} />{t('plugins.tabConfig')}</button>}
              </div>
            </article>)}
          </div>}
      {phone ? current && <MobileSubPage title={name(current)} onBack={close} manageHistory={!onSelect} search={false}>
        <div className="tt-capability-detail-scroll">{detail}</div>
      </MobileSubPage> : <Modal open={!!current} title={current ? name(current) : ''} onCancel={close} footer={null}
        width="var(--content-form)" className="tt-capability-modal tt-plugin-detail-modal" destroyOnClose>{detail}</Modal>}
      <InstallModal open={installOpen} locale={locale} t={t} onClose={() => setInstallOpen(false)}
        onDone={() => { setInstallOpen(false); void reload() }} />
    </section>
  )
}

// ── 安装入口:上传 .tgz 插件包,或安装开发机上的本地目录 ──
function InstallModal({ open, onClose, onDone, locale, t }: {
  open: boolean; onClose: () => void; onDone: () => void; locale: string
  t: (k: string, vars?: Record<string, string | number>) => string
}) {
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [removed, setRemoved] = useState<RegisteredPlugin[]>([])

  // 打开弹窗时拉取「已卸载的内置插件」,供一键恢复(内置编译在二进制里,不能重传包)
  useEffect(() => {
    if (!open) return
    api('GET', '/plugin/removed').then((r) => setRemoved(r || [])).catch(() => setRemoved([]))
  }, [open])

  const restore = async (id: string) => {
    setBusy(true)
    try {
      await api('POST', `/plugins/${encodeURIComponent(id)}/restore`)
      message.success(t('plugins.restored'))
      onDone()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const finish = () => {
    message.success(t('plugins.installedOk'))
    setPath('')
    onDone()
  }

  const uploadPkg = async (file: File) => {
    setBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const r = await fetch(nodeApi('/plugin/install'), { method: 'POST', body: form })
      const data = await r.json().catch(() => null)
      if (!r.ok) throw new Error(data?.error?.message || data?.error?.code || 'HTTP ' + r.status)
      finish()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const installPath = async () => {
    if (!path.trim()) return
    setBusy(true)
    try {
      await api('POST', '/plugin/install', { path: path.trim() })
      finish()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} title={t('plugins.installTitle')} destroyOnClose>
      <Spin spinning={busy}>
        <Upload.Dragger className="tt-capability-dropzone" accept=".tgz,.tar.gz" showUploadList={false} disabled={busy}
          beforeUpload={(f) => { uploadPkg(f as unknown as File); return false }}>
          <div className="tt-capability-drop-content"><span className="tt-capability-upload-icon"><UploadIcon size={24} /></span>
            <strong>{t('plugins.uploadHint')}</strong><span>{t('plugins.uploadSub')}</span></div>
        </Upload.Dragger>
        <Divider plain style={{ fontSize: 'var(--fs-meta)' }}>{t('plugins.orLocalPath')}</Divider>
        <Space.Compact style={{ width: '100%' }}>
          <Input placeholder={t('plugins.pathPlaceholder')} value={path}
            onChange={(e) => setPath(e.target.value)} onPressEnter={installPath} />
          <Button type="primary" disabled={!path.trim()} onClick={installPath}>{t('plugins.installFromPath')}</Button>
        </Space.Compact>
        {removed.length > 0 && (
          <>
            <Divider plain style={{ fontSize: 'var(--fs-meta)' }}>{t('plugins.restoreBuiltin')}</Divider>
            <List size="small" dataSource={removed}
              renderItem={(p) => (
                <List.Item actions={[
                  <Button key="r" size="small" onClick={() => restore(p.manifest.id)}>{t('plugins.restore')}</Button>,
                ]}>
                  <List.Item.Meta
                    title={lt(p.manifest.displayName, locale) || p.manifest.name}
                    description={<Typography.Text type="secondary" ellipsis={{ tooltip: true }} style={{ fontSize: 'var(--fs-meta)' }}>
                      {lt(p.manifest.description, locale)}</Typography.Text>}
                  />
                </List.Item>
              )} />
          </>
        )}
      </Spin>
    </Modal>
  )
}

function PluginDetail({ plugin, initialTab, locale, t, onChanged }: {
  plugin: RegisteredPlugin; initialTab?: string; locale: string; onChanged: () => void
  t: (k: string, vars?: Record<string, string | number>) => string
}) {
  const m = plugin.manifest
  const fields = m.contributes?.configFields || []
  const commands = m.contributes?.commands || []
  const [purge, setPurge] = useState(false)
  const uninstall = async () => {
    try {
      await api('DELETE', `/plugins/${encodeURIComponent(m.id)}${purge ? '?purge=1' : ''}`)
      message.success(t('plugins.uninstalled'))
      onChanged()
    } catch (e: any) {
      message.error(e.message)
    }
  }
  return (
    <div className="tt-plugin-detail">
      <div className="tt-plugin-detail-meta">
        <Space wrap><Tag>{t(plugin.enabled ? 'plugins.stateEnabled' : 'plugins.stateDisabled')}</Tag>
          <Tag>{m.version}</Tag><Typography.Text type="secondary">{m.id}</Typography.Text></Space>
        <Popconfirm
          title={m.runtime?.kind === 'builtin' ? t('plugins.uninstallConfirmBuiltin') : t('plugins.uninstallConfirm')}
          description={
            <Checkbox checked={purge} onChange={(e) => setPurge(e.target.checked)}>
              {t('plugins.uninstallPurge')}
            </Checkbox>
          }
          onConfirm={uninstall}
          onOpenChange={(open) => { if (!open) setPurge(false) }}
        >
          <Button size="small" danger>{t('plugins.uninstall')}</Button>
        </Popconfirm>
      </div>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 'var(--sp-3)' }}>
        {lt(m.description, locale)}
      </Typography.Paragraph>
      <Tabs defaultActiveKey={initialTab}
        items={[
          ...(m.id === HOST_MONITOR_ID ? [{
            key: 'monitor', label: t('plugins.monitor.tab'),
            children: <HostMonitorPanel pluginId={m.id} enabled={plugin.enabled} t={t} />,
          }] : []),
          ...(m.id === CRON_ID ? [{
            key: 'jobs', label: t('cron.tab'),
            children: <CronPanel pluginId={m.id} enabled={plugin.enabled} t={t} />,
          }] : []),
          // 守护 tab 排在「配置」前面:对这个插件来说「谁被守着」才是主任务,
          // 全局默认已经被提到面板顶上那句白话里了
          ...(m.id === KEEPALIVE_ID ? [{
            key: 'guards', label: t('ka.tab'),
            children: <KeepalivePanel pluginId={m.id} enabled={plugin.enabled} t={t} />,
          }] : []),
          {
            key: 'config', label: t('plugins.tabConfig'),
            children: fields.length
              ? <ConfigForm pluginId={m.id} fields={fields} groups={m.contributes?.configGroups || []} locale={locale} t={t} />
              : <Empty description={t('plugins.noConfig')} image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          },
          {
            key: 'commands', label: t('plugins.tabCommands'),
            children: <CommandList pluginId={m.id} commands={commands} enabled={plugin.enabled} locale={locale} t={t} />,
          },
          {
            key: 'perms', label: t('plugins.tabPerms'),
            children: <Descriptions size="small" column={1} bordered
              items={Object.entries(m.permissions || {}).map(([k, v]) => ({
                key: k, label: k, children: <Typography.Text code>{JSON.stringify(v)}</Typography.Text>,
              }))} />,
          },
          { key: 'audit', label: t('plugins.tabAudit'), children: <AuditTable pluginId={m.id} t={t} /> },
        ]}
      />
    </div>
  )
}

function ConfigForm({ pluginId, fields, groups, locale, t }: {
  pluginId: string; fields: ConfigField[]; groups: ConfigGroup[]; locale: string
  t: (k: string, vars?: Record<string, string | number>) => string
}) {
  const [form] = Form.useForm()
  const [initial, setInitial] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const abort = new AbortController()
    setLoadState('loading')
    void api('GET', `/plugins/${encodeURIComponent(pluginId)}/config`, undefined, { signal: abort.signal })
      .then(cfg => {
        if (abort.signal.aborted) return
        setInitial(cfg || {}); form.setFieldsValue(cfg || {}); setLoadState('ready')
      })
      .catch(() => { if (!abort.signal.aborted) setLoadState('error') })
    return () => abort.abort()
  }, [pluginId, form, attempt])

  const save = async () => {
    const values: Record<string, string> = form.getFieldsValue()
    // secret 字段展示的是掩码:只提交用户真正改动过的项,避免掩码写回。
    const set: Record<string, string> = {}
    for (const f of fields) {
      const v = values[f.key] ?? ''
      if (v !== (initial[f.key] ?? '')) set[f.key] = v
    }
    if (!Object.keys(set).length) { message.info(t('plugins.nothingChanged')); return }
    setSaving(true)
    try {
      await api('PUT', `/plugins/${encodeURIComponent(pluginId)}/config`, { set })
      message.success(t('plugins.saved'))
      const cfg = await api('GET', `/plugins/${encodeURIComponent(pluginId)}/config`)
      setInitial(cfg || {})
      form.setFieldsValue(cfg || {})
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (loadState === 'loading') return <Spin />
  if (loadState === 'error') return <Alert type="error" showIcon message={t('plugins.configLoadFailed')}
    action={<Button onClick={() => setAttempt(value => value + 1)}>{t('agent.retry')}</Button>} />

  const renderField = (f: ConfigField) => (
    <Form.Item key={f.key} name={f.key}
      label={lt(f.title, locale) || f.key}
      extra={lt(f.description, locale) || undefined}>
      {f.options?.length
        ? <Select options={f.options.map((o) => ({ value: o, label: o === '' ? t('plugins.optionAuto') : o }))} />
        : f.secret
          ? <Input.Password placeholder={f.placeholder} autoComplete="new-password" />
          : <Input placeholder={f.placeholder} />}
    </Form.Item>
  )

  // 按 manifest 的 configGroups 分节:组标题 + 多行引导说明 + 该组字段;
  // 未归组的字段渲染在最前(与旧 manifest 兼容)。
  const grouped = groups.filter((g) => fields.some((f) => f.group === g.key))
  const ungrouped = fields.filter((f) => !f.group || !grouped.some((g) => g.key === f.group))
  return (
    <Form form={form} layout="vertical" disabled={saving} style={{ maxWidth: 560 }}>
      {ungrouped.map(renderField)}
      {grouped.map((g, i) => (
        <div key={g.key}>
          <Divider orientation="left" orientationMargin={0} style={{ marginTop: i === 0 && !ungrouped.length ? 0 : 8 }}>
            <Typography.Text strong>{lt(g.title, locale) || g.key}</Typography.Text>
          </Divider>
          {lt(g.description, locale) && (
            <Typography.Paragraph type="secondary" style={{ whiteSpace: 'pre-line', fontSize: 'var(--fs-sm)', marginBottom: 'var(--sp-4)' }}>
              {lt(g.description, locale)}
            </Typography.Paragraph>
          )}
          {fields.filter((f) => f.group === g.key).map(renderField)}
        </div>
      ))}
      <Button type="primary" loading={saving} onClick={save}>{t('plugins.save')}</Button>
    </Form>
  )
}

function CommandList({ pluginId, commands, enabled, locale, t }: {
  pluginId: string; commands: { id: string; title?: LocaleText }[]; enabled: boolean; locale: string
  t: (k: string, vars?: Record<string, string | number>) => string
}) {
  const [running, setRunning] = useState('')
  const [result, setResult] = useState<{ id: string; data: any } | null>(null)

  const run = async (id: string) => {
    setRunning(id)
    setResult(null)
    try {
      const data = await api('POST', `/plugins/${encodeURIComponent(pluginId)}/run`, { command: id, args: {} })
      setResult({ id, data })
      message.success(t('plugins.runDone'))
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setRunning('')
    }
  }

  if (!commands.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <List
        dataSource={commands}
        renderItem={(c) => (
          <List.Item actions={[
            <Button key="run" size="small" disabled={!enabled} loading={running === c.id}
              onClick={() => run(c.id)}>{t('plugins.run')}</Button>,
          ]}>
            <List.Item.Meta
              title={<Typography.Text code>{c.id}</Typography.Text>}
              description={lt(c.title, locale)}
            />
          </List.Item>
        )}
      />
      {result && (
        <Card size="small" title={<Typography.Text code>{result.id}</Typography.Text>}>
          <pre style={{ margin: 0, maxHeight: 320, overflow: 'auto', fontSize: 'var(--fs-meta)', whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(result.data, null, 2)}
          </pre>
        </Card>
      )}
    </Space>
  )
}

function AuditTable({ pluginId, t }: {
  pluginId: string
  t: (k: string, vars?: Record<string, string | number>) => string
}) {
  const [rows, setRows] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api('GET', `/plugins/${encodeURIComponent(pluginId)}/audit`)
      .then((data) => setRows(data || []))
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [pluginId])
  return (
    <Table<AuditEntry> size="small" rowKey={(r, i) => `${r.time}-${i}`} loading={loading}
      dataSource={rows} pagination={{ pageSize: 15, hideOnSinglePage: true }}
      columns={[
        { title: t('plugins.auditTime'), dataIndex: 'time', width: 190, ellipsis: true },
        { title: t('plugins.auditAction'), dataIndex: 'action', width: 170,
          render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
        { title: t('plugins.auditTarget'), dataIndex: 'target', ellipsis: true },
        { title: t('plugins.auditDecision'), dataIndex: 'decision', width: 90,
          render: (v: string) => <Tag color={v === 'denied' ? 'red' : 'green'}>{v}</Tag> },
        { title: t('plugins.auditResult'), dataIndex: 'result', ellipsis: true },
      ]}
    />
  )
}
