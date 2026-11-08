// ── 关闭 worktree 会话的收尾三选一（W7）：保留 / 合并回 base 并删除 / 丢弃并删除 ──
import { useEffect, useState } from 'react'
import { submitLifecycle, lifecycleRequestError } from './session-lifecycle'
import { useI18n } from '../../i18n'
import { Modal, Radio, Select, App as AntApp } from 'antd'

export function CloseWorktreeModal({ info, onClose, onDone }: {
  info: { name: string; st: any } | null
  onClose: () => void
  onDone: (name: string) => void
}) {
  const [mode, setMode] = useState<'keep' | 'merge' | 'discard'>('keep')
  const [strategy, setStrategy] = useState<'squash' | 'merge' | 'rebase'>('squash')
  const [busy, setBusy] = useState(false)
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const st = info?.st || {}
  const merged = !!st.mergedInto // 合入检测（10 §5）：已合入时丢弃=清理，默认直选
  useEffect(() => { if (info) { setMode(info.st?.mergedInto ? 'discard' : 'keep'); setStrategy('squash') } }, [info])
  const ok = async () => {
    if (!info) return
    setBusy(true)
    try {
      await submitLifecycle('close', {
        mode, path: st.path, snapshot: st.snapshot, sessionIdentity: st.sessionIdentity, ...(mode === 'merge' ? { strategy } : {}),
      }, info.name)
      message.success(t('session.lifecycle.closeAccepted'))
      onClose(); onDone(info.name)
    } catch (e: any) {
      const ae = e.apiError || {}
      message.error(ae.stage ? t('worktree.close.failedAtStage', { stage: ae.stage, msg: e.message }) : lifecycleRequestError(e, t))
    } finally { setBusy(false) }
  }
  return (
    <Modal open={!!info} onCancel={onClose} onOk={ok} confirmLoading={busy} destroyOnClose
      title={t('worktree.close.title', { name: info?.name || '' })}
      okText={t('session.close')}
      okButtonProps={{ danger: mode === 'discard' && (!merged || (st.dirty || 0) + (st.untracked || 0) > 0) }}>
      <div style={{ color: 'var(--text-dim)', marginBottom: 'var(--sp-3)' }}>
        {/* 已合入（10 §5）：损失叙事换成绿色定心丸；未提交改动仍如实提示 */}
        {merged
          ? (<>
            <div style={{ color: 'var(--ok)' }}>{t('project.finish.mergedRemote', { target: st.mergedInto, kind: st.mergedKind })}</div>
            {(st.dirty || 0) + (st.untracked || 0) > 0 && (
              <div style={{ color: 'var(--warn)', marginTop: 'var(--sp-1)' }}>{t('project.finish.uncommitted', { count: (st.dirty || 0) + (st.untracked || 0) })}</div>
            )}
          </>)
          : t('worktree.close.summary', {
            branch: st.branch || '?',
            dirty: (st.dirty || 0) + (st.untracked || 0),
            ahead: st.committedAhead || 0,
            base: st.base || '?',
          })}
      </div>
      <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)}
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
        <Radio value="keep">{t('worktree.close.keep')}</Radio>
        {/* 已合入后本地再合并只会空转/添乱：禁用并提示走清理 */}
        <Radio value="merge" disabled={!st.base || merged}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
            {t('worktree.close.merge', { base: st.base || '?' })}
            {merged && <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-dimmer)' }}>{t('worktree.close.mergeDisabledMerged')}</span>}
            {mode === 'merge' && (
              <Select size="small" value={strategy} onChange={(v) => setStrategy(v)} style={{ width: 100 }}
                onClick={(e) => e.stopPropagation()}
                options={[{ value: 'squash', label: 'squash' }, { value: 'merge', label: 'merge' }, { value: 'rebase', label: 'rebase' }]} />
            )}
          </span>
        </Radio>
        <Radio value="discard">
          {merged
            ? <span style={{ color: 'var(--ok)' }}>{t('worktree.close.discardMerged', { target: st.mergedInto })}</span>
            : <span style={{ color: 'var(--danger)' }}>{t('worktree.close.discard')}</span>}
        </Radio>
      </Radio.Group>
    </Modal>
  )
}
