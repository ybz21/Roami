import { useEffect, useRef, useState } from 'react'
import { App, Input, Modal, Select } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { DirPicker } from '../sessions/DirPicker'

export function NewSwarmModal({ open, onClose, onDone, initialDir, lockDir }: { open: boolean; onClose: () => void; onDone: (name?: string) => void; initialDir?: string; lockDir?: boolean }) {
  const { t } = useI18n(), { message } = App.useApp()
  const [name, setName] = useState(''), [goal, setGoal] = useState(''), [dir, setDir] = useState(initialDir || '')
  const [cid, setCid] = useState(''), [conversations, setConversations] = useState<{ id: string; title: string }[]>([])
  const [busy, setBusy] = useState(false), [pick, setPick] = useState(false), [failed, setFailed] = useState(false)
  const key = useRef(crypto.randomUUID()), payload = useRef('')
  useEffect(() => {
    if (!open) return
    let active = true; setFailed(false)
    void Promise.all([api('GET', '/agent/conversations'), api('POST', '/agent/main-conversation')]).then(([list, main]) => {
      if (!active) return
      setConversations(list.data || []); setCid(value => value || main.data.id)
      setDir(value => value || initialDir || '')
    }).catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [open, initialDir])
  const create = async () => {
    if (!name.trim() || !goal.trim() || !cid) return
    setBusy(true)
    try {
      let target: Record<string, unknown> = { kind: 'new_session' }
      if (dir.trim()) {
        const projects = await api('GET', '/projects')
        const project = (projects.data?.projects || []).find((item: { dir: string }) => item.dir.replace(/\/+$/, '') === dir.trim().replace(/\/+$/, ''))
        if (project) target = { kind: 'project', projectId: project.key, directory: dir.trim() }
        else target = { kind: 'new_session', directory: dir.trim() }
      }
      const body = { name: name.trim(), goal: goal.trim(), mainConversationId: cid, target }
      const identity = JSON.stringify(body)
      if (payload.current && payload.current !== identity) key.current = crypto.randomUUID()
      payload.current = identity
      const result = await api('POST', '/agent/swarms', { ...body, commandKey: key.current })
      key.current = crypto.randomUUID(); payload.current = ''; setName(''); setGoal('')
      onClose(); onDone(result.data.id)
    } catch { message.error(t('swarm.managed.createFailed')) } finally { setBusy(false) }
  }
  return <><Modal open={open} title={t('swarm.new')} onCancel={onClose} onOk={create} confirmLoading={busy} okText={t('file.create')} okButtonProps={{ disabled: !name.trim() || !goal.trim() || !cid }}>
    <div className="swarm-create-fields">
      <label>{t('swarm.managed.name')}<Input value={name} onChange={e => setName(e.target.value)} /></label>
      <label>{t('swarm.managed.goal')}<Input.TextArea rows={3} value={goal} onChange={e => setGoal(e.target.value)} /></label>
      <label>{t('swarm.managed.main')}<Select value={cid || undefined} onChange={setCid} options={conversations.map(c => ({ value: c.id, label: c.title }))} /></label>
      <label>{t('swarm.managed.directory')}<Input value={dir} readOnly={lockDir} onChange={e => setDir(e.target.value)} addonAfter={!lockDir && <button type="button" className="tt-act" onClick={() => setPick(true)}>{t('common.browse')}</button>} /></label>
      <p className="swarm-note" role={failed ? 'alert' : undefined}>{t(failed ? 'swarm.managed.unavailable' : 'swarm.managed.createHint')}</p>
    </div>
  </Modal><DirPicker open={pick} start={dir || undefined} onPick={value => { setDir(value); setPick(false) }} onClose={() => setPick(false)} /></>
}
