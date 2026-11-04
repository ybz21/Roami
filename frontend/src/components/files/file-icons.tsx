// 文件相关的图标与小按钮组件。目录浏览器(FileBrowser)与文件展示组件(fileview/)共用。
// 纯展示，无业务逻辑；文件类型图标按扩展名映射，避免字母块图标。
import { type ReactNode } from 'react'
import { Button, Tooltip } from 'antd'
import { extOf } from './file-utils'

// ── 文件类型图标（目录/文件分类 SVG）──
const FolderIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" opacity="0.9"><path d="M20 6h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2z" /></svg>
)
const FileIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><polyline points="14 2 14 8 20 8" /></svg>
)
const CodeIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg>
const TableIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18" /><path d="M3 15h18" /><path d="M9 3v18" /></svg>
const SlidesIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8" /><path d="M12 17v4" /></svg>
const PdfIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><path d="M8 13h8" /><path d="M8 17h5" /></svg>
const ImageIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21" /></svg>
const TextIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><path d="M8 13h8" /><path d="M8 17h8" /><path d="M8 9h3" /></svg>
const ArchiveIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M12 4v16" /><path d="m10 10 4 4" /><path d="m14 10-4 4" /></svg>
const ConfigIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><circle cx="12" cy="15" r="2" /><path d="M12 11v2" /></svg>
const DatabaseIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5" /><path d="M3 12a9 3 0 0 0 18 0" /></svg>
const AudioIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></svg>
const VideoIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="2" /><path d="m10 8 6 4-6 4V8z" /></svg>
const DesignIcon = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="m12 19 7-7 3 3-7 7-3-3z" /><path d="m18 13-1.5-7.5L2 2l3.5 14.5L13 18l5-5z" /><path d="m2 2 7.586 7.586" /><circle cx="11" cy="11" r="2" /></svg>

type FileIconEntry = { icon: ReactNode; color: string }
const EXT_ICON: Record<string, FileIconEntry> = {}
function regIcon(exts: string[], icon: ReactNode, color: string) {
  for (const ext of exts) EXT_ICON[ext] = { icon, color }
}
regIcon(['py', 'pyw', 'ipynb'], <CodeIcon />, 'hsl(210,70%,58%)')
regIcon(['js', 'jsx', 'mjs', 'cjs'], <CodeIcon />, 'hsl(48,90%,50%)')
regIcon(['ts', 'tsx'], <CodeIcon />, 'hsl(210,80%,55%)')
regIcon(['go'], <CodeIcon />, 'hsl(195,70%,50%)')
regIcon(['rs'], <CodeIcon />, 'hsl(25,80%,55%)')
regIcon(['java', 'kt'], <CodeIcon />, 'hsl(20,85%,52%)')
regIcon(['rb'], <CodeIcon />, 'hsl(0,70%,55%)')
regIcon(['c', 'cpp', 'h', 'hpp'], <CodeIcon />, 'hsl(210,60%,55%)')
regIcon(['cs'], <CodeIcon />, 'hsl(265,55%,55%)')
regIcon(['swift'], <CodeIcon />, 'hsl(20,90%,55%)')
regIcon(['html', 'htm'], <CodeIcon />, 'hsl(15,85%,55%)')
regIcon(['css', 'scss', 'sass', 'less'], <CodeIcon />, 'hsl(210,70%,55%)')
regIcon(['vue'], <CodeIcon />, 'hsl(153,60%,48%)')
regIcon(['php'], <CodeIcon />, 'hsl(240,40%,58%)')
regIcon(['sh', 'bash', 'zsh', 'fish', 'ps1'], <CodeIcon />, 'var(--text-dim)')
regIcon(['sql'], <CodeIcon />, 'hsl(210,50%,55%)')
regIcon(['json', 'jsonl', 'ndjson'], <ConfigIcon />, 'hsl(158,55%,48%)')
regIcon(['yaml', 'yml', 'toml', 'ini', 'conf', 'env', 'lock'], <ConfigIcon />, 'var(--text-dim)')
regIcon(['xml'], <CodeIcon />, 'hsl(25,65%,52%)')
regIcon(['db', 'sqlite', 'parquet'], <DatabaseIcon />, 'hsl(210,50%,55%)')
regIcon(['doc', 'docx', 'odt', 'rtf', 'pages'], <TextIcon />, 'hsl(210,65%,52%)')
regIcon(['xls', 'xlsx', 'xlsm', 'csv', 'tsv', 'ods', 'numbers'], <TableIcon />, 'hsl(140,55%,42%)')
regIcon(['ppt', 'pptx', 'odp', 'key'], <SlidesIcon />, 'hsl(15,80%,52%)')
regIcon(['pdf'], <PdfIcon />, 'hsl(0,65%,50%)')
regIcon(['md', 'markdown', 'txt', 'log', 'tex', 'epub'], <TextIcon />, 'var(--text-dim)')
regIcon(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'heic', 'heif', 'avif', 'tif', 'tiff', 'svg'], <ImageIcon />, 'hsl(280,55%,58%)')
regIcon(['psd', 'ai', 'fig', 'sketch', 'xd', 'blend'], <DesignIcon />, 'hsl(280,50%,55%)')
regIcon(['mp3', 'wav', 'flac', 'ogg', 'aac', 'aiff', 'm4a', 'mid'], <AudioIcon />, 'hsl(330,60%,55%)')
regIcon(['mp4', 'mov', 'mkv', 'avi', 'webm', 'wmv', 'flv', 'm4v'], <VideoIcon />, 'hsl(340,65%,52%)')
regIcon(['zip', 'tar', 'gz', 'rar', '7z', 'bz2', 'xz', 'tgz', 'dmg', 'iso', 'pkg'], <ArchiveIcon />, 'hsl(30,50%,48%)')
regIcon(['ttf', 'otf', 'woff', 'woff2'], <FileIcon />, 'var(--text-dim)')

export const FileTypeIcon = ({ name }: { name: string }) => {
  const entry = EXT_ICON[extOf(name)] || { icon: <FileIcon />, color: 'var(--text-dimmer)' }
  return (
    <span style={{
      width: 22, height: 22, display: 'inline-grid', placeItems: 'center', color: entry.color,
      flex: '0 0 auto',
    }}>{entry.icon}</span>
  )
}

export { FolderIcon }

// ── 目录浏览器工具栏 / 导航图标 ──
export const FolderUpIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 16V10" /><path d="m9 13 3-3 3 3" /></svg>
)
export const RefreshIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 1-15 6.7" /><path d="M3 12A9 9 0 0 1 18 5.3" /><path d="M18 2v4h-4" /><path d="M6 22v-4h4" /></svg>
)
export const BackIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
)
export const ForwardIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="m9 18 6-6-6-6" /></svg>
)
export const NewFolderIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /><path d="M12 10v6" /><path d="M9 13h6" /></svg>
)
export const UploadIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M16 16h2a4 4 0 0 0 .7-7.9A6 6 0 0 0 7.4 6.8 5 5 0 0 0 8 16h1" /><path d="M12 18V10" /><path d="m8.5 13.5 3.5-3.5 3.5 3.5" /></svg>
)
export const DownloadIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v10" /><path d="m8.5 9.5 3.5 3.5 3.5-3.5" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg>
)
export const CloseIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
)
export const EyeIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></svg>
)
export const EyeOffIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9.9 4.2A10.9 10.9 0 0 1 12 4c6.5 0 10 7 10 7a17.7 17.7 0 0 1-3 3.7" /><path d="M6.6 6.6A17.6 17.6 0 0 0 2 11s3.5 7 10 7a10.6 10.6 0 0 0 4.4-.9" /><path d="m2 2 20 20" /><path d="M9.5 9.5a3 3 0 0 0 4.2 4.2" /></svg>
)
export const SortIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h7" /><path d="M3 12h10" /><path d="M3 18h14" /><path d="M18 6v12" /><path d="m15 15 3 3 3-3" /></svg>
)
// 树形视图开关：平铺列表 <-> 可展开目录树
export const TreeIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="15" width="6" height="6" rx="1" /><path d="M9 6h6a2 2 0 0 1 2 2v7" /></svg>
)
export const ListIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 6h13" /><path d="M8 12h13" /><path d="M8 18h13" /><path d="M3 6h.01" /><path d="M3 12h.01" /><path d="M3 18h.01" /></svg>
)
export const SearchIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
)
// 文件展示（VSCode 式）：切换预览 / 侧栏打开预览 / 新标签打开
export const PreviewIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9h10" /><path d="M7 13h10" /><path d="M7 17h6" /></svg>
)
export const PreviewSideIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M13 4v16" /><path d="M16 10h3" /><path d="M16 14h3" /></svg>
)
export const ExternalLinkIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
)
// 目录展开箭头：展开时旋转 90°
export const Chevron = ({ open }: { open: boolean }) => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
    style={{ transition: 'transform .12s', transform: open ? 'rotate(90deg)' : 'none' }}><path d="m9 18 6-6-6-6" /></svg>
)

export const IconButton = ({ title, children, danger, onClick, disabled, width = 24 }: { title: string; children: ReactNode; danger?: boolean; onClick?: (e: React.MouseEvent) => void; disabled?: boolean; width?: number | string }) => (
  <Tooltip title={title}>
    <Button type="text" size="small" aria-label={title} disabled={disabled} danger={danger} onClick={(e) => { e.stopPropagation(); onClick?.(e) }}
      style={{ width, height: 24, minWidth: 24, padding: width === 24 ? 0 : '0 6px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
      {children}
    </Button>
  </Tooltip>
)

export const ClosePanelButton = ({ title, onClick }: { title: string; onClick: () => void }) => (
  <button
    type="button"
    title={title}
    aria-label={title}
    className="tt-file-close"
    onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
    onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick() }}
  >
    <CloseIcon />
  </button>
)
