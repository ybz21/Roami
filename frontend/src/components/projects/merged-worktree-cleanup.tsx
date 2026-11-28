import { useEffect, useRef } from 'react'
import { App as AntApp } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { TrashIcon } from '../../icons'
import { currentNodeId, useCurrentNodeId } from '../cluster/node-url'
import { dirTailName } from '../files/dir-name'

type CleanupTarget = { path: string; branch: string; head: string }
type Worktree = CleanupTarget & {
  isMain?: boolean; external?: boolean; directoryOnly?: boolean; locked?: boolean; prunable?: boolean
  dirty: number; untracked: number; mergedInto?: string; sessions?: unknown[] | null
}

export function canCleanupMergedWorktree(w: Worktree) {
  return Boolean(w.head && w.mergedInto && !w.isMain && !w.external && !w.directoryOnly && !w.locked && !w.prunable
    && !w.sessions?.length && w.dirty === 0 && w.untracked === 0)
}

const cleanupErrors: Partial<Record<string, string>> = {
  WORKTREE_CHANGED: 'project.cleanupChanged',
  WORKTREE_NOT_MERGED: 'project.cleanupNoLongerMerged',
  WORKTREE_DIRTY: 'project.cleanupDirty',
  SESSIONS_INSIDE: 'project.cleanupInUse',
  WORKTREE_SESSIONS_UNKNOWN: 'project.cleanupSessionsUnknown',
  WORKTREE_BRANCH_RETAINED: 'project.cleanupBranchRetained',
}

export function useMergedWorktreeCleanup(dir: string, onDone: (removed: ReadonlySet<string>) => void) {
  const { t } = useI18n()
  const { message, modal } = AntApp.useApp()
  const node = useCurrentNodeId()
  const confirmation = useRef<ReturnType<typeof modal.confirm>>()
  useEffect(() => () => {
    confirmation.current?.destroy()
    confirmation.current = undefined
  }, [dir, node])

  return (worktrees: CleanupTarget[]) => {
    if (confirmation.current || !worktrees.length) return
    const targets = worktrees.map(({ path, branch, head }) => ({ path, branch, head }))
    const name = (target: CleanupTarget) => target.branch || dirTailName(target.path)
    const dialog = modal.confirm({
      wrapClassName: 'tt-worktree-cleanup',
      title: targets.length === 1 ? t('project.cleanupSingleConfirm', { name: name(targets[0]) }) : t('project.cleanupConfirm'),
      content: t('project.cleanupConfirmDesc', { count: targets.length }),
      okText: t('project.cleanup'),
      cancelText: t('common.cancel'),
      okButtonProps: { danger: true },
      autoFocusButton: 'cancel',
      afterClose: () => { if (confirmation.current === dialog) confirmation.current = undefined },
      onOk: async () => {
        dialog.update({ cancelButtonProps: { disabled: true }, keyboard: false })
        const removed = new Set<string>()
        const failures: { target: CleanupTarget; reason: string }[] = []
        for (const target of targets) {
          if (currentNodeId() !== node || confirmation.current !== dialog) return
          try {
            await api('POST', '/git/worktree/cleanup-merged', target)
            removed.add(target.path)
          } catch (error) {
            const code = (error as { apiError?: { code?: string } })?.apiError?.code || ''
            if (code === 'WORKTREE_BRANCH_RETAINED') removed.add(target.path)
            const reason = Object.prototype.hasOwnProperty.call(cleanupErrors, code) ? cleanupErrors[code] : 'project.cleanupFailed'
            failures.push({ target, reason: t(reason) })
          }
        }
        if (currentNodeId() !== node || confirmation.current !== dialog) return
        onDone(removed)
        const cleaned = targets.length - failures.length
        if (failures.length === 0) {
          message.success(t('project.cleanedCount', { count: cleaned }))
          return
        }
        modal.warning({
          wrapClassName: 'tt-worktree-cleanup',
          title: t('project.cleanupIncomplete', { cleaned, failed: failures.length }),
          content: (
            <details open={failures.length === 1}>
              <summary>{t('project.cleanupDetails')}</summary>
              <ul>{failures.map(({ target, reason }) => <li key={target.path}><b>{name(target)}</b> · {reason}</li>)}</ul>
            </details>
          ),
        })
      },
    })
    confirmation.current = dialog
  }
}

export function MergedWorktreeCleanupButton({ onClick }: { onClick: () => void }) {
  const { t } = useI18n()
  return <button type="button" className="tt-act danger" onClick={onClick}>
    <TrashIcon size={14} />
    {t('project.cleanupAll')}
  </button>
}
