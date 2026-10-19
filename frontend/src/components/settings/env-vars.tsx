import { useSettingsRead } from './settings-read'
// 全局环境变量：注入**新开**会话的 KV。已经开着的会话拿不到，要按页头那颗「推送到会话」
// 才补发一次 export（见 registry 的页级动作）。
import { useState } from 'react'
import { App as AntApp, Button, Empty, Input, List, Popconfirm, Space } from 'antd'
import { PlusIcon } from '../../icons'
import { api } from '../../api'
import { useI18n } from '../../i18n'

export function pushEnvToSessions(): Promise<void> {
  return api('POST', '/env/push').then(() => undefined)
}

export function EnvVarsSettings() {
  const [list, setList] = useState<any[]>([])
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const load = () => api('GET', '/env').then(setList)
  const readState = useSettingsRead(load)
  const add = () => {
    let key = '', value = ''
    modal.confirm({
      title: t('env.addVariable'),
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input placeholder={t('env.keyPlaceholder')} onChange={(e) => (key = e.target.value)} />
          <Input placeholder={t('env.valuePlaceholder')} onChange={(e) => (value = e.target.value)} />
        </Space>
      ),
      okText: t('env.set'),
      onOk: async () => {
        if (!key.trim()) { message.error(t('env.keyRequired')); throw new Error('empty') }
        await api('PUT', '/env', { key: key.trim(), value }); message.success(t('env.setDone')); load()
      },
    })
  }
  const del = async (key: string) => {
    try { await api('DELETE', '/env/' + encodeURIComponent(key)); message.success(t('file.deleted')); load() }
    catch (e: any) { message.error(e.message) }
  }
  if (readState) return readState
  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Button onClick={add} icon={<PlusIcon />}>{t('env.add')}</Button>
      {list.length === 0 ? <Empty description={t('env.empty')} /> : (
        <List dataSource={list} renderItem={(kv: any) => (
          <List.Item actions={[
            <Popconfirm key="d" title={t('env.deleteConfirm')} onConfirm={() => del(kv.key)}>
              <button type="button" className="tt-act danger">{t('file.delete')}</button>
            </Popconfirm>,
          ]}>
            <List.Item.Meta title={<code>{kv.key}</code>} description={<code style={{ color: 'var(--text-dim)' }}>{kv.value}</code>} />
          </List.Item>
        )} />
      )}
    </Space>
  )
}
