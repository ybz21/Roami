// 关会话的分流（W7，和会话页 Sessions.tsx 的 beginClose 同一套规则）：
//   非 worktree / 外部 worktree → 确认后 DELETE；
//   worktree 里有未收尾内容（脏、未跟踪、领先 base）→ CloseWorktreeModal 三选一（保留 / 合并 / 丢弃）；
//   干净 worktree → 确认框附「随会话删除」勾选。
// 左树的右键菜单和会话页都要这一套，抽出来共用；会话页那份先不动。
import { useEffect, useRef, useState } from 'react'
import { App as AntApp, Checkbox, Modal } from 'antd'
import { api } from '../../api'
import { submitLifecycle, lifecycleRequestError } from './session-lifecycle'
import { closeSession, sessionActionError } from './session-actions'
import { nativeSessionId } from './session-record'
import { useI18n } from '../../i18n'
import { sessionDisplay, sessionLabel } from './session-label'
import { CloseWorktreeModal } from './CloseWorktreeModal'

export function useSessionCloser(closeTerm: (n: string) => void, afterClose?: () => void) {
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const [closing, setClosing] = useState<{ name: string; st: any } | null>(null)
  const [checkingName, setCheckingName] = useState<string | null>(null)
  const checking = useRef<AbortController | null>(null)
  const cancelCheck = () => {
    const request = checking.current
    checking.current = null
    setCheckingName(null)
    request?.abort()
  }
  useEffect(() => () => { checking.current?.abort(); checking.current = null }, [])
  const done = (n: string) => { message.success(t('session.lifecycle.closeAccepted')); closeTerm(n); afterClose?.() }
  const kill = async (n: string) => {
    try { await closeSession(n); done(n) } catch (e: any) { message.error(sessionActionError(e, t)) }
  }
  const closeWith = async (n: string, mode: 'keep' | 'merge' | 'discard', st?: any) => {
    try {
      await submitLifecycle('close', { mode, path: st?.path, snapshot: st?.snapshot, sessionIdentity: st?.sessionIdentity }, n)
      done(n)
    } catch (e: any) {
      const ae = e.apiError || {}
      message.error(ae.stage ? t('worktree.close.failedAtStage', { stage: ae.stage, msg: e.message }) : lifecycleRequestError(e, t))
      throw e
    }
  }
  const beginClose = async (n: string) => {
    if (checking.current) return
    let st: any = null
    if (!nativeSessionId(n)) {
      const request = new AbortController()
      checking.current = request
      setCheckingName(n)
      try {
        st = (await api('GET', `/sessions/${encodeURIComponent(n)}/worktree-status`, undefined, { signal: request.signal }))?.data
        if (checking.current !== request) return
      } catch {
        if (checking.current === request) message.error(t('session.closeCheckFailed'))
        return
      } finally {
        if (checking.current === request) {
          checking.current = null
          setCheckingName(null)
        }
      }
    }
    const unfinished = (st?.dirty || 0) > 0 || (st?.untracked || 0) > 0 || (st?.committedAhead || 0) > 0
    // worktree 里还有别的会话：只关这一个，worktree 和分支一根毛都不碰（收尾整个任务走 finishTask）
    if (st?.inWorktree && (st.others || 0) > 0) {
      modal.confirm({
        title: t('session.closeConfirm', { name: sessionDisplay(n) }),
        content: <div style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-sm)' }}>{t('session.closeOthersNote', { n: st.others })}</div>,
        okText: t('session.close'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
        onOk: () => kill(n),
      })
      return
    }
    if (!st?.inWorktree || st.external || (!unfinished && !st.base)) {
      modal.confirm({
        title: t('session.closeConfirm', { name: sessionDisplay(n) }),
        okText: t('session.close'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
        onOk: () => kill(n),
      })
      return
    }
    if (unfinished) { setClosing({ name: n, st }); return }
    // 干净 worktree：默认勾选随会话删除（显式可见，不静默）
    const removeToo = { current: true }
    modal.confirm({
      title: t('session.closeConfirm', { name: sessionDisplay(n) }),
      content: <Checkbox defaultChecked onChange={(e) => { removeToo.current = e.target.checked }}>{t('worktree.close.removeWithSession')}</Checkbox>,
      okText: t('session.close'), cancelText: t('common.cancel'),
      onOk: () => closeWith(n, removeToo.current ? 'discard' : 'keep', st),
    })
  }
  const node = <>
    <Modal open={checkingName !== null} centered title={t('session.closeConfirm', { name: sessionLabel(checkingName || '') })}
      okText={t('session.close')} okButtonProps={{ disabled: true, danger: true }} cancelText={t('common.cancel')} onCancel={cancelCheck}>
      <p role="status" aria-live="polite" style={{ fontSize: 'var(--fs-lg)', color: 'var(--text-bright)' }}>{t('session.closeChecking')}</p>
    </Modal>
    <CloseWorktreeModal info={closing} onClose={() => setClosing(null)} onDone={(name) => { closeTerm(name); afterClose?.() }} />
  </>
  return { beginClose, kill, node }
}
