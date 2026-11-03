import { useState } from 'react'
import { Button, Input } from 'antd'
import { useI18n } from '../../../i18n'
import { api } from '../../../api'
import type { Workspace } from './okr-workspace'

export default function OkrTeamMemory({ workspace, onUpdated, onFiles, onDraftChange }: { workspace: Workspace; onUpdated: (workspace: Workspace) => void; onFiles: () => void; onDraftChange: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const [editing, setEditing] = useState(false), [text, setText] = useState(''), [hash, setHash] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [comparison, setComparison] = useState<string | null>(null)
  const files = workspace.projectFiles
  if (!files?.teamMemoryFile) return null
  const close = () => { setEditing(false); onDraftChange(false); setError(''); setComparison(null) }
  const compare = async () => {
    setBusy(true)
    try { const response = await api('GET', '/projects/' + encodeURIComponent(workspace.projectId) + '/okr'); const latest = response.data as Workspace; if (!latest?.projectFiles?.teamMemorySha256) throw new Error('MEMORY_UNAVAILABLE'); onUpdated(latest); setHash(latest.projectFiles.teamMemorySha256); setComparison(latest.projectFiles.teamMemory || ''); setError('') }
    catch { setError('okr.loadFailed') }
    finally { setBusy(false) }
  }
  const save = async () => {
    if (busy || error === 'okr.memoryConflict' || error === 'okr.loadFailed') return
    setBusy(true); setError('')
    try { const response = await api('PUT', '/projects/' + encodeURIComponent(workspace.projectId) + '/okr/memory', { content: text, expectedSha256: hash }); onUpdated(response.data); close() }
    catch (error) { setError((error as Error & { status?: number }).status === 409 ? 'okr.memoryConflict' : 'okr.writeFailed') }
    finally { setBusy(false) }
  }
  return <section className="okr-section okr-team-memory">
    <div className="okr-section-head"><h3>{t('okr.teamMemory')}</h3><div className="okr-actions">{!editing && files.teamMemorySha256 && <Button onClick={() => { setText(files.teamMemory || ''); setHash(files.teamMemorySha256!); setEditing(true); onDraftChange(true) }}>{t('okr.edit')}</Button>}<Button onClick={onFiles}>{t('okr.tab.files')}</Button></div></div>
    {editing ? <form onSubmit={event => { event.preventDefault(); void save() }}><label className="okr-field"><span>{t('okr.teamMemory')}</span><Input.TextArea value={text} onChange={event => setText(event.target.value)} autoSize={{ minRows: 6, maxRows: 16 }} disabled={busy} /></label>{error && <p role="alert">{t(error)}</p>}{(error === 'okr.memoryConflict' || error === 'okr.loadFailed') && <Button disabled={busy} onClick={() => void compare()}>{t('okr.compareMemory')}</Button>}{comparison !== null && <section><h4>{t('okr.latestMemory')}</h4><p>{comparison || t('okr.noMemory')}</p></section>}<div className="okr-actions"><Button htmlType="submit" type="primary" disabled={error === 'okr.memoryConflict' || error === 'okr.loadFailed'} loading={busy}>{t('okr.saveMemory')}</Button><Button disabled={busy} onClick={close}>{t('common.cancel')}</Button></div></form> : files.teamMemory ? <details><summary>{t('okr.readMemory')}</summary><p>{files.teamMemory}</p></details> : <p className="okr-muted">{t('okr.noMemory')}</p>}
    <p className="okr-muted">{t('okr.memorySource', { path: files.root + '/' + files.teamMemoryFile })}</p>
  </section>
}
