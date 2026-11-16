// 文件标签的第二行：面包屑 + 「源码 / 预览 / 改动」三段（22 设计 §3.3）。
//
// 会话标签下面是 12 稿的工具条，文件标签下面是这一条，同样 36 高、同一套 .tt-tbar 语言。
// 「预览」只对 markdown / HTML 有（FileView 的 forcePreview）；「改动」= 这个文件对 HEAD 的
// 未提交 diff（/git/diff），就地替换编辑器，不开新标签——Orca 的 changes 模式。
import { useEffect, useState } from 'react'
import { Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { CloseIcon, CodeIcon, DiffIcon } from '../../icons'
import BackButton from '../BackButton'
import { PreviewIcon } from './file-icons'
import { extOf, MD_EXT } from './file-utils'
import DiffView from './DiffView'

export type FileTabMode = 'source' | 'preview' | 'changes'

/** 面包屑：路径相对 worktree 根；不在根下就整条绝对路径 */
function crumbsOf(path: string, root: string): string[] {
  const rel = root && path.startsWith(root.replace(/\/+$/, '') + '/') ? path.slice(root.replace(/\/+$/, '').length + 1) : path
  return rel.split('/').filter(Boolean)
}

export function canPreview(path: string): boolean {
  const ext = extOf(path)
  return MD_EXT.includes(ext) || ext === 'html' || ext === 'htm'
}

export function FilePathBar({ path, root, mode, onMode, onBack, onClose }: {
  path: string
  /** 当前任务的 worktree 根：面包屑从它下面开始 */
  root: string
  mode: FileTabMode
  onMode: (m: FileTabMode) => void
  onBack?: () => void
  onClose?: () => void
}) {
  const { t } = useI18n()
  const crumbs = crumbsOf(path, root)
  const previewable = canPreview(path)
  const seg = (m: FileTabMode, icon: React.ReactNode, label: string, disabled = false) => (
    <button key={m} type="button" className={`tt-tbtn${mode === m ? ' on' : ''}`} disabled={disabled}
      aria-pressed={mode === m} onClick={() => !disabled && onMode(m)} title={label}>
      {icon}<span>{label}</span>
    </button>
  )
  return (
    <div className="tt-tbar tt-pathbar">
      {onBack && <BackButton label={t('tabs.returnToSession')} onClick={onBack} />}
      <span className="crumbs" title={path}>
        {crumbs.map((c, i) => (
          <span key={i} className={i === crumbs.length - 1 ? 'leaf' : undefined}>
            {i > 0 && <span className="sep" aria-hidden>/</span>}{c}
          </span>
        ))}
      </span>
      {onClose && <button type="button" className="tt-act ico" aria-label={t('tabs.closeFile', { name: path.split('/').pop() || path })} onClick={onClose}><CloseIcon /></button>}
      <span className="tt-spacer" />
      <span className="tt-tgroup">
        {seg('source', <CodeIcon size={14} />, t('pathbar.source'))}
        {seg('preview', <PreviewIcon />, t('pathbar.preview'), !previewable)}
        {seg('changes', <DiffIcon size={14} />, t('pathbar.changes'))}
      </span>
    </div>
  )
}

/** 「改动」视图：这个文件对 HEAD 的未提交 diff，就地替换编辑器 */
export function ChangesView({ path, root }: { path: string; root: string }) {
  const { t } = useI18n()
  const [diff, setDiff] = useState<string | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let stop = false
    setDiff(null); setErr('')
    const rel = crumbsOf(path, root).join('/')
    if (!root || rel === path) { setErr(t('pathbar.notInWorktree')); return }
    api('GET', `/git/diff?root=${encodeURIComponent(root)}&file=${encodeURIComponent(rel)}&staged=0&untracked=0`)
      .then((r) => { if (!stop) setDiff(r?.data?.diff || '') })
      .catch((e: any) => { if (!stop) setErr(e.message) })
    return () => { stop = true }
  }, [path, root, t])
  if (err) return <div className="tt-pathbar-empty">{err}</div>
  if (diff === null) return <div className="tt-pathbar-empty"><Spin /></div>
  if (!diff.trim()) return <div className="tt-pathbar-empty">{t('pathbar.noChanges')}</div>
  return <DiffView text={diff} />
}
