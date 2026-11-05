import { useEffect, useState } from 'react'
import { renameSession, sessionActionError } from './session-actions'
import { useI18n } from '../../i18n'
import { sessionLabel, updateSessionLabel } from './session-label'
import { Input, Modal, Space, App as AntApp } from 'antd'

export default function RenameSessionModal({ session, onClose, onDone }: { session: string | null; onClose: () => void; onDone: (oldName: string, newName: string) => void }) {
  const [name, setName] = useState('')
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  useEffect(() => { if (session) setName(sessionLabel(session)) }, [session])
  const ok = async () => {
    if (!session) return
    const next = name.trim()
    if (!next) return message.error(t('session.nameRequired'))
    try {
      const res = await renameSession(session, next)
      const label = res.data?.label || next
      updateSessionLabel(session, label)
      message.success(t('session.renamed'))
      onClose()
      onDone(session, session)
    } catch (e: any) {
      message.error(sessionActionError(e, t))
    }
  }
  return (
    <Modal open={!!session} onCancel={onClose} onOk={ok} okText={t('session.rename')} title={t('session.renameTitle')} destroyOnClose>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Input placeholder={t('session.namePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <div style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>{t('session.renameHint')}</div>
        {session && <div style={{ color: 'var(--text-dimmer)', fontSize: 12, fontFamily: 'ui-monospace, monospace' }}>id: {session}</div>}
      </Space>
    </Modal>
  )
}
