import { Popover } from 'antd'
import { useI18n } from '../../i18n'
import { FolderIcon } from '../../icons'
import { BranchIcon } from '../git/parts'
import { shortSessionPath, type SessionPlace } from './SessionLocation'

export default function SessionContext({ branch, worktree, cwd }: SessionPlace) {
  const { t } = useI18n()
  const directory = worktree || cwd
  if (!branch && !directory) return null

  return <Popover trigger="click" placement="bottomRight" content={
    <dl className="tt-session-context-detail">
      {branch && <div><dt>{t('git.refs.branchShort')}</dt><dd>{branch}</dd></div>}
      {directory && <div><dt>{t('file.directory')}</dt><dd>{directory}</dd></div>}
    </dl>
  }>
    <button type="button" className="tt-tbtn tt-session-context" aria-label={t('session.context')}>
      {branch ? <BranchIcon size={14} /> : <FolderIcon size={14} />}
      <span>{branch || shortSessionPath(directory!)}</span>
    </button>
  </Popover>
}
