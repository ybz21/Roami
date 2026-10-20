// 带边框的预览容器：顶部一条「类型图标 + 标题（+ 截断提示）」，下面放预览正文。
// PDF / Office / CSV 等非编辑器预览共用这层外壳。
import { type ReactNode } from 'react'
import { FileTypeIcon } from '../file-icons'
import { useI18n } from '../../../i18n'

export function PreviewShell({ path, title, truncated, inline, children }: {
  path: string
  title: string
  truncated?: boolean
  inline?: boolean
  children: ReactNode
}) {
  const { t } = useI18n()
  return (
    <div style={{ border: inline ? 0 : '1px solid var(--border-subtle)', borderRadius: inline ? 0 : 'var(--r-card)', overflow: 'hidden', background: inline ? 'var(--bg-base)' : 'var(--bg-container)', height: inline ? '100%' : undefined, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-dim)', fontSize: 12 }}>
        <FileTypeIcon name={path} />
        <span>{title}</span>
        {truncated && <span style={{ marginLeft: 'auto', color: '#d29922' }}>{t('file.truncatedShort')}</span>}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>{children}</div>
    </div>
  )
}
