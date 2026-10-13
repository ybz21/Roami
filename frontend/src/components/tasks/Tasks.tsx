import { useEffect, useState } from 'react'
import { api } from '../../api'
import { StatusTag, TypeTag } from '../session-tags'
import { DirPicker } from '../sessions/DirPicker'
import { useI18n } from '../../i18n'
import { Button, Card, Empty, Form, Input, List, Modal, Popconfirm, Segmented, Select, Space, Typography, App as AntApp } from 'antd'
import { CloseIcon, PlusIcon } from '../../icons'

const { Text } = Typography

// ── 任务（命令 + Agent 统一） ──
export default function Tasks({ openTerm }: { openTerm: (n: string) => void }) {
  const [groups, setGroups] = useState<any[]>([])
  const [detail, setDetail] = useState<Record<string, any>>({})
  const [open, setOpen] = useState<string | null>(null)
  const [spawn, setSpawn] = useState(false)
  const [send, setSend] = useState<any[] | null>(null)
  const [collect, setCollect] = useState<string | null>(null)
  const { message } = AntApp.useApp()
  const { t } = useI18n()

  const loadGroups = () => api('GET', '/tasks').then(setGroups).catch(() => {})
  const loadDetail = (g: string) => api('GET', '/tasks/' + encodeURIComponent(g)).then((d) => setDetail((s) => ({ ...s, [g]: d }))).catch(() => {})
  useEffect(() => { loadGroups() }, [])
  useEffect(() => {
    if (!open) return
    loadDetail(open)
    const t = setInterval(() => loadDetail(open), 3000)
    return () => clearInterval(t)
  }, [open])

  const kill = async (g: string) => {
    try { await api('DELETE', '/tasks/' + encodeURIComponent(g)); message.success(t('task.cleaned')); setOpen(null); loadGroups() }
    catch (e: any) { message.error(e.message) }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div><Button type="primary" onClick={() => setSpawn(true)}>+ {t('task.create')}</Button></div>
      {groups.length === 0 && <Empty description={t('task.noGroups')} />}
      {groups.map((g: any) => (
        <Card key={g.group} size="small"
          title={<span onClick={() => setOpen(open === g.group ? null : g.group)} style={{ cursor: 'pointer' }}>
            {g.group} <Text type="secondary" style={{ fontSize: 13 }}>{t('task.aliveCount', { alive: g.alive, total: g.total })}</Text></span>}
          extra={<Popconfirm title={t('task.cleanConfirm', { group: g.group })} onConfirm={() => kill(g.group)}><Button danger size="small">{t('task.clean')}</Button></Popconfirm>}
        >
          {open === g.group && (
            <>
              <List size="small" dataSource={detail[g.group]?.tasks || []} locale={{ emptyText: t('common.loading') }}
                renderItem={(t: any) => (
                  <List.Item actions={[
                    <a key="t" onClick={() => openTerm(t.name)}>{t('common.terminal')}</a>,
                  ]}>
                    <List.Item.Meta
                      title={<Space><span>{t.label || t.name}</span><TypeTag type={t.type} /><StatusTag status={t.status} code={t.exit_code} /></Space>}
                      description={t.task ? <Text type="secondary" style={{ fontSize: 12 }}>{t.task}</Text> : null}
                    />
                  </List.Item>
                )} />
              <Space style={{ marginTop: 10 }}>
                <Button size="small" onClick={() => setCollect(g.group)}>{t('task.collectOutput')}</Button>
                <Button size="small" onClick={() => setSend(detail[g.group]?.tasks || [])}>{t('task.appendInstruction')}</Button>
              </Space>
            </>
          )}
        </Card>
      ))}
      <SpawnModal open={spawn} onClose={() => setSpawn(false)} onDone={loadGroups} />
      <SendModal tasks={send} onClose={() => setSend(null)} />
      <CollectModal group={collect} onClose={() => setCollect(null)} />
    </Space>
  )
}

// ── 创建任务（命令 / Agent） ──
function SpawnModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [form] = Form.useForm()
  const [type, setType] = useState('cmd')
  const [pickDir, setPickDir] = useState(false)
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const submit = async () => {
    const v = await form.validateFields()
    const tasks = (v.tasks || []).filter((t: any) => t?.name && t?.payload)
      .map((t: any) => (type === 'agent' ? { name: t.name, task: t.payload } : { name: t.name, cmd: t.payload }))
    if (!tasks.length) return message.error(t('task.needOne'))
    const body: any = { group: v.group, type, tasks }
    if (type === 'agent') { body.dir = v.dir; body.perm = v.perm; body.model = v.model }
    try { await api('POST', '/tasks', body); message.success(t('session.created')); onClose(); onDone() }
    catch (e: any) { message.error(e.message) }
  }
  return (
    <>
      <Modal open={open} onCancel={onClose} onOk={submit} okText={t('file.create')} title={t('task.create')} destroyOnClose>
        <Segmented block value={type} onChange={(v) => setType(v as string)}
          options={[{ label: t('common.command'), value: 'cmd' }, { label: 'Agent', value: 'agent' }]} style={{ marginBottom: 12 }} />
        <Form form={form} layout="vertical" preserve={false} initialValues={{ tasks: [{}, {}], perm: 'auto' }}>
          <Form.Item name="group" label={t('task.groupName')} rules={[{ required: true }]}><Input placeholder={t('task.groupPlaceholder')} /></Form.Item>
          <Form.List name="tasks">
            {(fields, { add, remove }) => (
              <>
                {fields.map((f) => (
                  <Space key={f.key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                    <Form.Item {...f} name={[f.name, 'name']} noStyle><Input placeholder={t('common.name')} style={{ width: 110 }} /></Form.Item>
                    <Form.Item {...f} name={[f.name, 'payload']} noStyle><Input placeholder={type === 'agent' ? t('task.description') : t('common.command')} style={{ width: 240 }} /></Form.Item>
                    <a onClick={() => remove(f.name)} style={{ color: '#f85149', display: 'inline-flex' }}><CloseIcon size={13} /></a>
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add()} block icon={<PlusIcon size={13} />}>{t('task.addRow')}</Button>
              </>
            )}
          </Form.List>
          {type === 'agent' && (
            <div style={{ marginTop: 12 }}>
              <Form.Item label={t('task.workdirLabel')}>
                <Space.Compact style={{ width: '100%' }}>
                  <Form.Item name="dir" noStyle><Input placeholder={t('task.dirExample')} /></Form.Item>
                  <Button onClick={() => setPickDir(true)}>{t('common.browse')}</Button>
                </Space.Compact>
              </Form.Item>
              <Space>
                <Form.Item name="perm" label={t('task.permission')}><Input placeholder={t('task.permissionPlaceholder')} /></Form.Item>
                <Form.Item name="model" label={t('task.model')}><Input placeholder={t('common.optional')} /></Form.Item>
              </Space>
            </div>
          )}
        </Form>
      </Modal>
      <DirPicker open={pickDir} start={form.getFieldValue('dir') || undefined}
        onPick={(p) => { form.setFieldValue('dir', p); setPickDir(false) }} onClose={() => setPickDir(false)} />
    </>
  )
}

function SendModal({ tasks, onClose }: { tasks: any[] | null; onClose: () => void }) {
  const [sess, setSess] = useState<string>()
  const [msg, setMsg] = useState('')
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  useEffect(() => { if (tasks?.length) setSess(tasks[0].name) }, [tasks])
  const go = async () => {
    if (!sess || !msg) return
    try { await api('POST', '/tasks/_/send', { sess, msg, activity: 'dialogue' }); message.success(t('task.sent')); onClose() } catch (e: any) { message.error(e.message) }
  }
  return (
    <Modal open={!!tasks} onCancel={onClose} onOk={go} okText={t('common.send')} title={t('task.appendInstruction')} destroyOnClose>
      <Select style={{ width: '100%', marginBottom: 10 }} value={sess} onChange={setSess}
        options={(tasks || []).map((t: any) => ({ value: t.name, label: `${t.label || t.name} [${t.type}]` }))} />
      <Input.TextArea rows={3} value={msg} onChange={(e) => setMsg(e.target.value)} placeholder={t('task.instructionPlaceholder')} />
    </Modal>
  )
}

function CollectModal({ group, onClose }: { group: string | null; onClose: () => void }) {
  const { t } = useI18n()
  const [text, setText] = useState(t('common.loading'))
  useEffect(() => {
    if (!group) return
    setText(t('common.loading'))
    api('GET', '/tasks/' + encodeURIComponent(group) + '/collect')
      .then((r) => setText((r.results || []).map((x: any) => `━━━ ${x.task} [${x.type}] ━━━\n${x.prompt ? t('task.promptPrefix') + x.prompt + '\n' : ''}${x.output}`).join('\n\n') || t('task.noOutput')))
      .catch((e) => setText(e.message))
  }, [group, t])
  return (
    <Modal open={!!group} onCancel={onClose} footer={null} title={t('task.collectTitle', { group: group || '' })} width="min(720px,94vw)">
      <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '60vh', overflow: 'auto', background: 'var(--bg-term)', padding: 12, borderRadius: 'var(--r-sm)', fontSize: 12.5 }}>{text}</pre>
    </Modal>
  )
}
