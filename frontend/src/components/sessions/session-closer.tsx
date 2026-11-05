// 关会话的分流（W7，和会话页 Sessions.tsx 的 beginClose 同一套规则）：
//   非 worktree / 外部 worktree → 确认后 DELETE；
//   worktree 里有未收尾内容（脏、未跟踪、领先 base）→ CloseWorktreeModal 三选一（保留 / 合并 / 丢弃）；
//   干净 worktree → 确认框附「随会话删除」勾选。
// 左树的右键菜单和会话页都要这一套，抽出来共用；会话页那份先不动。
import { useState } from 'react'
import { App as AntApp, Checkbox } from 'antd'
import { api } from '../../api'
import { closeSession, sessionActionError } from './session-actions'
import { nativeSessionId } from './session-record'
import { useI18n } from '../../i18n'
import { sessionDisplay } from './session-label'
import { CloseWorktreeModal } from './CloseWorktreeModal'

export function useSessionCloser(closeTerm: (n: string) => void, afterClose?: () => void) {
  const { message, modal } = AntApp.useApp()
  const { t } = useI18n()
  const [closing, setClosing] = useState<{ name: string; st: any } | null>(null)
  const done = (n: string) => { message.success(t('session.closed')); closeTerm(n); afterClose?.() }
  const kill = async (n: string) => {
    try { await closeSession(n); done(n) } catch (e: any) { message.error(sessionActionError(e, t)) }
  }
  const closeWith = async (n: string, mode: 'keep' | 'merge' | 'discard', path?: string) => {
    try {
      await api('POST', `/sessions/${encodeURIComponent(n)}/close-with-worktree`, { mode, path })
      done(n)
    } catch (e: any) {
      const ae = e.apiError || {}
      message.error(ae.stage ? t('worktree.close.failedAtStage', { stage: ae.stage, msg: e.message }) : e.message)
      throw e
    }
  }
  const beginClose = async (n: string) => {
    let st: any = null
    try { if (!nativeSessionId(n)) st = (await api('GET', `/sessions/${encodeURIComponent(n)}/worktree-status`))?.data } catch {}
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
      onOk: () => closeWith(n, removeToo.current ? 'discard' : 'keep', st.path),
    })
  }
  const node = <CloseWorktreeModal info={closing} onClose={() => setClosing(null)} onDone={(name) => { closeTerm(name); afterClose?.() }} />
  return { beginClose, kill, node }
}
