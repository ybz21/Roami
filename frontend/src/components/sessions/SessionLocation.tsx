import { BranchIcon } from '../git/parts'
import { FolderIcon } from '../../icons'

export type SessionPlace = { branch?: string; worktree?: string; cwd?: string }

export function shortSessionPath(path: string) {
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
  return (parts.length > 2 ? '…/' : path.startsWith('/') ? '/' : '') + parts.slice(-2).join('/')
}

export default function SessionLocation({ branch, worktree, cwd, compact = false }: SessionPlace & { compact?: boolean }) {
  const directory = worktree || cwd
  if (!branch && !directory) return null
  return <span className="tt-session-location">
    {branch && <span className="branch" title={branch}><BranchIcon size={12} />{branch}</span>}
    {directory && <span className="directory" title={directory}><FolderIcon size={12} />{compact ? directory.replace(/\\/g, '/').split('/').filter(Boolean).pop() || directory : shortSessionPath(directory)}</span>}
  </span>
}
