// 快捷命令：终端工具条上的自定义按钮，点一下把这行字送进当前会话。
// 标签式增删，改完即存——设置页里没有「保存」按钮。
import { useEffect, useState } from 'react'
import { App as AntApp, Button, Input, Space, Tag } from 'antd'
import { PlusIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { usePreferences } from '../../preferences'

export function QuickCommandsSettings() {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [prefs, setPrefs] = usePreferences()
  const [cmds, setCmds] = useState<string[]>(prefs.quickCommands || [])
  const [draft, setDraft] = useState('')
  useEffect(() => { setCmds(prefs.quickCommands || []) }, [prefs.quickCommands])
  const save = async (next: string[]) => { setCmds(next); if (await setPrefs({ quickCommands: next })) message.success(t('settings.saved')) }
  const add = () => { const v = draft.trim(); if (!v || cmds.includes(v)) return; save([...cmds, v]); setDraft('') }
  const remove = (i: number) => save(cmds.filter((_, j) => j !== i))
  return (
    <Space direction="vertical" size="small" style={{ width: '100%', maxWidth: 520 }}>
      {cmds.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>
          {cmds.map((cmd, i) => (
            <Tag key={i} closable onClose={() => remove(i)} color="blue" style={{ margin: 0 }}>{cmd}</Tag>
          ))}
        </div>
      )}
      <Space.Compact style={{ width: '100%' }}>
        <Input value={draft} onChange={(e) => setDraft(e.target.value)}
          onPressEnter={add} placeholder={t('settings.quickCommandPlaceholder')} />
        <Button type="primary" onClick={add} aria-label={t('env.add')} icon={<PlusIcon />} />
      </Space.Compact>
    </Space>
  )
}
