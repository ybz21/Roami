// 插件统一管理/配置页(VS Code 扩展页式):左侧插件列表,右侧详情
// (配置表单按 manifest.configFields 自动渲染 / 命令 / 审计)。
// 数据全部走 backend 薄封装 REST(exec ttmux plugin ... --json),前端不感知 plugind。
import { useCallback, useEffect, useMemo, useState } from 'react'
import { nodeApi } from '../cluster/node-url'
import {
  Alert, Button, Card, Checkbox, Descriptions, Divider, Empty, Form, Input, List, Modal, Popconfirm, Select,
  Space, Spin, Switch, Table, Tabs, Tag, Tooltip, Typography, Upload, message,
} from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import HostMonitorPanel from './HostMonitorPanel'
import CronPanel from './CronPanel'
import KeepalivePanel from './KeepalivePanel'
import MobileSubPage from '../MobileSubPage'
import { useLayout } from '../../layout'

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

export default function PluginsPanel({ initialId }: { initialId?: string } = {}) {
  const { t, locale } = useI18n()
  const [plugins, setPlugins] = useState<RegisteredPlugin[]>([])
  const [daemon, setDaemon] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(true)
  // 深链选中：状态条上点某一格进来时带着插件 id（#/plugins/<id>）。
  // 从前点进来只到列表页第一项，你还得自己在左边找一遍——而你刚刚点的就是它。
  const [selected, setSelected] = useState(initialId || '')
  const [startingDaemon, setStartingDaemon] = useState(false)
  const [installOpen, setInstallOpen] = useState(false)
  // 手机(窄屏)走两级导航：一级整页插件列表，点某项后详情以全屏二级页(MobileSubPage)展开。
  const { phone: isMobile } = useLayout()
  const [mobileDetail, setMobileDetail] = useState(false)

  const reload = useCallback(async () => {
    try {
      const [list, st] = await Promise.all([api('GET', '/plugins'), api('GET', '/plugin/status')])
      const rows: RegisteredPlugin[] = list || []
      setPlugins(rows)
      setDaemon(st?.daemon || null)
      setSelected((cur) => cur || initialId || rows[0]?.manifest.id || '')
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { reload() }, [reload])

  const current = useMemo(() => plugins.find((p) => p.manifest.id === selected), [plugins, selected])

  const startDaemon = async () => {
    setStartingDaemon(true)
    try {
      await api('POST', '/plugin/daemon/start')
      message.success(t('plugins.daemonStarted'))
      await reload()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setStartingDaemon(false)
    }
  }

  const toggle = async (p: RegisteredPlugin, enabled: boolean) => {
    try {
      await api('POST', `/plugins/${encodeURIComponent(p.manifest.id)}/${enabled ? 'enable' : 'disable'}`)
      message.success(t(enabled ? 'plugins.enabled' : 'plugins.disabled'))
      reload()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  if (loading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>

  return (
    // 两栏贴在一起、共用同一张底：这一页从前是「两张浮在页面上的卡片」，圆角 + 16px 缝 +
    // 比页面亮一档的底，和会话工作区/镜像页那种「一整块，靠 1px 线断句」完全不是一套语言。
    // 卡片本身留着（antd 的头/体布局还用得上），外观由 .tt-plugins 收平，见 index.css。
    <div className="tt-plugins" style={{ display: 'flex', height: '100%', minHeight: 0 }}>
      <Card size="small" className="tt-plugins-list" style={isMobile ? { flex: 1, minWidth: 0, overflow: 'auto' } : { width: 280, flex: '0 0 280px', overflow: 'auto' }} title={t('plugins.title')}
        extra={<Space size={4}>
          <Button size="small" type="primary" onClick={() => setInstallOpen(true)}>{t('plugins.install')}</Button>
          <Tooltip title={t('plugins.marketSoon')}>
            <Button size="small" disabled>{t('plugins.market')}</Button>
          </Tooltip>
        </Space>}>
        {daemon
          ? <Alert type="success" showIcon style={{ marginBottom: 8 }} message={t('plugins.daemonRunning')} />
          : <Alert type="warning" showIcon style={{ marginBottom: 8 }} message={t('plugins.daemonStopped')}
              action={<Button size="small" type="primary" loading={startingDaemon} onClick={startDaemon}>
                {t('plugins.daemonStart')}</Button>} />}
        <List
          dataSource={plugins}
          renderItem={(p) => (
            <List.Item
              onClick={() => { setSelected(p.manifest.id); if (isMobile) setMobileDetail(true) }}
              // 直角、通栏：一列 8px 圆角的小块贴在一整块底上，读起来像卡片里又摞了一叠卡片
              style={{
                cursor: 'pointer', borderRadius: 0, padding: '8px 10px',
                background: !isMobile && p.manifest.id === selected ? 'var(--sel-bg)' : undefined,
                boxShadow: !isMobile && p.manifest.id === selected ? 'inset 2px 0 0 var(--accent)' : undefined,
              }}
              actions={[<Switch key="sw" size="small" checked={p.enabled}
                onClick={(v, e) => { e.stopPropagation(); toggle(p, v) }} />]}
            >
              <List.Item.Meta
                title={<Space size={6}>{lt(p.manifest.displayName, locale) || p.manifest.name}
                  <Tag style={{ marginInlineStart: 0 }}>{p.manifest.version}</Tag></Space>}
                description={<Typography.Text type="secondary" ellipsis={{ tooltip: true }} style={{ fontSize: 12 }}>
                  {lt(p.manifest.description, locale)}</Typography.Text>}
              />
            </List.Item>
          )}
        />
      </Card>
      {!isMobile && (
        <div className="tt-plugins-detail" style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
          {current
            ? <PluginDetail key={current.manifest.id} plugin={current} locale={locale} t={t}
                onChanged={() => { setSelected(''); reload() }} />
            : <Empty style={{ marginTop: 64 }} />}
        </div>
      )}
      {isMobile && mobileDetail && current && (
        <MobileSubPage title={lt(current.manifest.displayName, locale) || current.manifest.name}
          onBack={() => setMobileDetail(false)}>
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 12 }}>
            <PluginDetail key={current.manifest.id} plugin={current} locale={locale} t={t}
              onChanged={() => { setMobileDetail(false); setSelected(''); reload() }} />
          </div>
        </MobileSubPage>
      )}
      <InstallModal open={installOpen} locale={locale} t={t} onClose={() => setInstallOpen(false)}
        onDone={() => { setInstallOpen(false); reload() }} />
    </div>
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

  const finish = (data: any) => {
    message.success(t('plugins.installedOk'))
    const text = typeof data?.data === 'string' ? data.data : ''
    if (text) Modal.info({ title: t('plugins.installTitle'), width: 560, content: <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{text}</pre> })
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
      finish(data)
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
      finish(await api('POST', '/plugin/install', { path: path.trim() }))
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} title={t('plugins.installTitle')} destroyOnClose>
      <Spin spinning={busy}>
        <Upload.Dragger accept=".tgz,.tar.gz" showUploadList={false} disabled={busy}
          beforeUpload={(f) => { uploadPkg(f as unknown as File); return false }}>
          <p style={{ margin: '12px 0 4px' }}>{t('plugins.uploadHint')}</p>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t('plugins.uploadSub')}</Typography.Text>
        </Upload.Dragger>
        <Divider plain style={{ fontSize: 12 }}>{t('plugins.orLocalPath')}</Divider>
        <Space.Compact style={{ width: '100%' }}>
          <Input placeholder={t('plugins.pathPlaceholder')} value={path}
            onChange={(e) => setPath(e.target.value)} onPressEnter={installPath} />
          <Button type="primary" disabled={!path.trim()} onClick={installPath}>{t('plugins.installFromPath')}</Button>
        </Space.Compact>
        {removed.length > 0 && (
          <>
            <Divider plain style={{ fontSize: 12 }}>{t('plugins.restoreBuiltin')}</Divider>
            <List size="small" dataSource={removed}
              renderItem={(p) => (
                <List.Item actions={[
                  <Button key="r" size="small" onClick={() => restore(p.manifest.id)}>{t('plugins.restore')}</Button>,
                ]}>
                  <List.Item.Meta
                    title={lt(p.manifest.displayName, locale) || p.manifest.name}
                    description={<Typography.Text type="secondary" ellipsis={{ tooltip: true }} style={{ fontSize: 12 }}>
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

function PluginDetail({ plugin, locale, t, onChanged }: {
  plugin: RegisteredPlugin; locale: string; onChanged: () => void
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
    <Card size="small"
      title={<Space>{lt(m.displayName, locale) || m.name}
        <Tag color={plugin.enabled ? 'green' : undefined}>{t(plugin.enabled ? 'plugins.stateEnabled' : 'plugins.stateDisabled')}</Tag>
        <Tag>{m.runtime?.kind || 'builtin'}</Tag></Space>}
      extra={(
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
      )}
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
        {lt(m.description, locale)}
      </Typography.Paragraph>
      <Tabs
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
    </Card>
  )
}

function ConfigForm({ pluginId, fields, groups, locale, t }: {
  pluginId: string; fields: ConfigField[]; groups: ConfigGroup[]; locale: string
  t: (k: string, vars?: Record<string, string | number>) => string
}) {
  const [form] = Form.useForm()
  const [initial, setInitial] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api('GET', `/plugins/${encodeURIComponent(pluginId)}/config`)
      .then((cfg) => { setInitial(cfg || {}); form.setFieldsValue(cfg || {}) })
      .catch((e) => message.error(e.message))
  }, [pluginId, form])

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
    <Form form={form} layout="vertical" style={{ maxWidth: 560 }}>
      {ungrouped.map(renderField)}
      {grouped.map((g, i) => (
        <div key={g.key}>
          <Divider orientation="left" orientationMargin={0} style={{ marginTop: i === 0 && !ungrouped.length ? 0 : 8 }}>
            <Typography.Text strong>{lt(g.title, locale) || g.key}</Typography.Text>
          </Divider>
          {lt(g.description, locale) && (
            <Typography.Paragraph type="secondary" style={{ whiteSpace: 'pre-line', fontSize: 13, marginBottom: 16 }}>
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
          <pre style={{ margin: 0, maxHeight: 320, overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap' }}>
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
