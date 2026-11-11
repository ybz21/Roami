// ── 关闭 worktree 会话的收尾三选一（W7）：保留 / 合并回 base 并删除 / 丢弃并删除 ──
import { useEffect, useState } from 'react'
import { submitLifecycle, lifecycleRequestError } from './session-lifecycle'
import { useI18n } from '../../i18n'
import { Checkbox, Modal, Radio, Select, App as AntApp } from 'antd'
import { closeSession, sessionActionError } from './session-actions'
import { sessionLabel } from './session-label'
import { SessionClosePosition } from './SessionClosePosition'

export function CloseWorktreeModal({ info, onClose, onDone, checking = false, sessionConfirmation = false }: {
  info: { name: string; st: any } | null
  onClose: () => void
  onDone: (name: string) => void
  checking?: boolean
  sessionConfirmation?: boolean
}) {
  const [mode, setMode] = useState<'keep' | 'merge' | 'discard'>('keep')
  const [strategy, setStrategy] = useState<'squash' | 'merge' | 'rebase'>('squash')
  const [busy, setBusy] = useState(false)
  const [removeToo, setRemoveToo] = useState(true)
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const st = info?.st || {}
  const merged = !!st.mergedInto // 合入检测（10 §5）：已合入时丢弃=清理，默认直选
  const unfinished = (st.dirty || 0) + (st.untracked || 0) + (st.committedAhead || 0) > 0
  const owned = st.inWorktree && !st.external && !(st.others > 0)
  const choices = !sessionConfirmation || (owned && unfinished)
  const removeOption = sessionConfirmation && owned && !unfinished && !!st.base
  useEffect(() => { if (info) { setMode(info.st?.mergedInto ? 'discard' : 'keep'); setStrategy('squash') } }, [info])
  useEffect(() => { setRemoveToo(true) }, [info?.name])
  const ok = async () => {
    if (!info || checking || busy) return
    setBusy(true)
    try {
      if (sessionConfirmation && !choices && !removeOption) await closeSession(info.name)
      else await submitLifecycle('close', {
        mode: choices ? mode : removeToo ? 'discard' : 'keep', path: st.path, snapshot: st.snapshot, sessionIdentity: st.sessionIdentity, ...(choices && mode === 'merge' ? { strategy } : {}),
      }, info.name)
      message.success(t('session.lifecycle.closeAccepted'))
      onClose(); onDone(info.name)
    } catch (e: any) {
      const ae = e.apiError || {}
      message.error(sessionConfirmation && !choices && !removeOption ? sessionActionError(e, t) : ae.stage ? t('worktree.close.failedAtStage', { stage: ae.stage, msg: e.message }) : lifecycleRequestError(e, t))
    } finally { setBusy(false) }
  }
  return (
    <Modal open={!!info} centered={sessionConfirmation} transitionName={sessionConfirmation ? '' : undefined} onCancel={() => { if (!busy) onClose() }} onOk={ok} confirmLoading={busy} destroyOnHidden
      modalRender={sessionConfirmation ? node => <SessionClosePosition>{node}</SessionClosePosition> : undefined}
      title={sessionConfirmation ? t('session.closeConfirm', { name: sessionLabel(info?.name) }) : t('worktree.close.title', { name: info?.name || '' })}
      okText={t('session.close')}
      cancelText={t('common.cancel')}
      cancelButtonProps={{ disabled: busy }} closable={!busy} maskClosable={!busy} keyboard={!busy}
      okButtonProps={{ 'aria-label': t('session.close'), loading: checking || busy, disabled: checking, danger: !choices || (mode === 'discard' && (!merged || (st.dirty || 0) + (st.untracked || 0) > 0)) }}>
      {checking ? <div role="status" aria-live="polite" style={{ fontSize: 'var(--fs-lg)', color: 'var(--text-bright)' }}>{t('session.closeChecking')}</div> : choices ? <>
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
      </> : removeOption ? <Checkbox checked={removeToo} onChange={event => setRemoveToo(event.target.checked)}>{t('worktree.close.removeWithSession')}</Checkbox> : st.inWorktree && st.others > 0 ? <div style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-sm)' }}>{t('session.closeOthersNote', { n: st.others })}</div> : null}
    </Modal>
  )
}
