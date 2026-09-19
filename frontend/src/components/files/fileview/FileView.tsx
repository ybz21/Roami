// 文件展示组件（容器）——页面统一引用它来「展示一个文件」。
// 职责：按路径取内容、活重载轮询、脏/保存、源码⇄渲染切换、标题栏与外壳（inline/modal）；
// 正文本身按类型分发给 fileview/ 下的子组件（Image/Pdf/Html/Markdown/Csv/Code/Office）。
import { type MouseEvent, useEffect, useRef, useState } from 'react'
import { nodeApi } from '../../cluster/node-url'
import { Button, Modal, Space, Spin, App as AntApp, Tooltip } from 'antd'
import { api } from '../../../api'
import ErrorBoundary from '../../ErrorBoundary'
import { useI18n } from '../../../i18n'
import { useThemeMode } from '../../../theme'
import { MD_EXT, extOf, fileKind, fileNameOf, fmtSize, localPathFromRef, monacoLangOf } from '../file-utils'
import { CloseIcon, ExternalLinkIcon, IconButton, PreviewIcon, PreviewSideIcon } from '../file-icons'
import { ImageView } from './ImageView'
import { PdfView } from './PdfView'
import { HtmlView } from './HtmlView'
import { MarkdownView } from './MarkdownView'
import { CsvView } from './CsvView'
import { CodeView } from './CodeView'
import { OfficeView } from './OfficeView'
import { MediaView } from './MediaView'
import { ChevronRight, WarnIcon } from '../../../icons'

export function FileView({
  path,
  accent,
  inline,
  active = true,
  tabbed,
  forcePreview,
  onClose,
  onBack,
  onOpenPath,
  onOpenAgent,
  onDirtyChange,
  onPreviewToSide,
  revealLine,
}: {
  path: string
  accent: string
  inline?: boolean
  // 多 tab 常驻挂载时，只有激活的才渲染重型 Monaco 编辑器/预览，避免多实例吃爆内存(OOM)。
  // 组件仍挂载 → draft/dirty 等 state 保留，切回来编辑内容不丢。
  active?: boolean
  // 编辑器 tab 上下文：外层 tab 已显示文件名+关闭，这里就不再重复顶部「▸ 文件名」标题行。
  tabbed?: boolean
  // 专用预览 tab（VSCode「侧栏预览」）：始终渲染 markdown/HTML，不显示编辑器/切换钮。
  forcePreview?: boolean
  onClose: () => void
  // 移动端二级页语境：标题栏最左显「←」返回（代替右侧关闭 ×），工具按钮可换行。
  onBack?: () => void
  onOpenPath: (p: string) => void
  onOpenAgent?: (kind: 'claude' | 'codex', path: string) => void
  // 编辑器脏状态上报（供外层 tab 显示未保存圆点）
  onDirtyChange?: (path: string, dirty: boolean) => void
  // 在侧栏打开渲染预览（外层 FileWorkspace 处理，开另一栏）
  onPreviewToSide?: (path: string) => void
  // 从对话页点「Grep 命中 path:line」跳过来时定位到那一行；nonce 让重复点同一处也能再次定位
  revealLine?: { line: number; nonce: number }
}) {
  const kind = fileKind(path)
  const { isImg, isVideo, isAudio, isMd, isHtml, isPdf, isOffice, isSheet } = kind
  // 二进制里能就地播/看的那几类：都不走 /file 取正文（取回来是一大坨乱码），直接交给 raw。
  const isMedia = isVideo || isAudio
  const rawOnly = isImg || isMedia || isPdf || isOffice
  const rawUrl = nodeApi(`/file/raw?path=${encodeURIComponent(path)}`)
  // HTML 预览专用：绝对路径编进 URL 路径（逐段转义、保留斜杠），让 iframe 里同目录相对引用能解析
  const serveUrl = nodeApi(`/file/serve${path.split('/').map(encodeURIComponent).join('/')}`)
  const previewUrl = nodeApi(`/file/preview?path=${encodeURIComponent(path)}`)
  const downloadUrl = `${rawUrl}&dl=1`
  const downloadName = fileNameOf(path)
  const previewHeight = inline ? '100%' : '74vh'
  const [data, setData] = useState<any>(null)
  const [err, setErr] = useState('')
  const [source, setSource] = useState(false) // markdown/HTML：源码/渲染切换
  const [agentPick, setAgentPick] = useState(false)
  const [draft, setDraft] = useState('') // 编辑器当前文本
  const [saving, setSaving] = useState(false)
  const [stale, setStale] = useState(false) // 磁盘上文件已被外部(cc/codex)改动，但本地有未保存改动没自动覆盖
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const { mode } = useThemeMode()

  // 可编辑：文本/代码/JSON/Markdown（源码）；二进制、被截断的大文件、表格/图片/PDF/Office 不可编辑。
  const editable = !!data && !data.binary && !data.truncated && !isSheet && !rawOnly
  const dirty = editable && data ? draft !== data.content : false
  useEffect(() => { onDirtyChange?.(path, dirty); return () => onDirtyChange?.(path, false) }, [dirty, path])

  const save = async () => {
    if (!editable || saving || !dirty) return
    setSaving(true)
    try {
      const res = await api('POST', '/file/save', { path, content: draft })
      setData((d: any) => ({ ...d, content: draft, mtime: res.data?.mtime ?? d?.mtime })) // 基线更新 → dirty 归零；mtime 同步避免自触发重载
      setStale(false)
      message.success(t('file.saved'))
    } catch (e: any) {
      message.error(t('file.saveFailed', { message: e.message }))
    } finally {
      setSaving(false)
    }
  }
  // Monaco 的 Ctrl+S 命令在挂载时捕获闭包，用 ref 始终指向最新 save，避免存到旧文本。
  const saveRef = useRef(save)
  saveRef.current = save

  useEffect(() => {
    if (rawOnly) return // 图片/音视频/PDF/Office 直接走 raw 或专用面板
    // tab 语境的 markdown 默认进编辑器(源码)、点预览才渲染;HTML 则默认直接渲染
    // (打开网页多是想看效果,不是编辑),两者都可用「源码/渲染」钮切换。
    setData(null); setErr(''); setStale(false); setSource(!!tabbed && MD_EXT.includes(extOf(path))); setDraft('')
    api('GET', `/file?path=${encodeURIComponent(path)}`).then((r) => { setData(r.data); setDraft(r.data?.content || '') }).catch((e) => setErr(e.message))
  }, [path, rawOnly])

  // 从磁盘重载（放弃本地未保存改动）
  const reloadFromDisk = () => {
    api('GET', `/file?path=${encodeURIComponent(path)}`).then((r) => { setData(r.data); setDraft(r.data?.content || ''); setStale(false) }).catch(() => {})
  }
  // 外部(cc/codex 等)改动已打开的文件 → 轮询 mtime：无本地改动自动重载渲染；有未保存改动只提示不覆盖。
  useEffect(() => {
    if (!active || !data || err || rawOnly) return
    let stop = false
    const h = setInterval(async () => {
      try {
        const r = await api('GET', `/file/stat?path=${encodeURIComponent(path)}`)
        if (stop || !r.data?.mtime || r.data.mtime === data.mtime) return
        if (dirty) { setStale(true); return } // 有未保存改动 → 不覆盖，仅提示
        const fr = await api('GET', `/file?path=${encodeURIComponent(path)}`)
        if (!stop) { setData(fr.data); setDraft(fr.data?.content || '') }
      } catch {}
    }, 2000)
    return () => { stop = true; clearInterval(h) }
  }, [active, data?.mtime, dirty, path, rawOnly, err])

  // 非激活 tab：只占位、不挂载重型 Monaco/预览（state 已在上面 hook 里保留，切回来不丢编辑）。
  if (!active) return <div style={{ height: '100%' }} />

  const name = fileNameOf(path)
  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(path)
      message.success(t('file.pathCopied'))
    } catch {
      message.error(t('common.copyFailed'))
    }
  }
  const resolvePreviewHref = (href: string, refKind: 'link' | 'image') => {
    const local = localPathFromRef(path, href)
    if (!local) return href
    if (refKind === 'image') return nodeApi(`/file/raw?path=${encodeURIComponent(local)}`)
    return nodeApi(`/file/raw?path=${encodeURIComponent(local)}`)
  }
  const openPreviewLink = (href: string, ev: MouseEvent<HTMLAnchorElement>) => {
    const local = localPathFromRef(path, href)
    if (!local) return
    ev.preventDefault()
    onOpenPath(local)
  }

  const titleNode = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingRight: inline ? 0 : 28, minWidth: 0, flexWrap: onBack ? 'wrap' : undefined, rowGap: onBack ? 6 : undefined }}>
      {onBack && (
        <IconButton title={t('common.back')} onClick={onBack}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
        </IconButton>
      )}
      {!tabbed && (
        <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          <span style={{ color: accent, display: 'inline-flex', verticalAlign: -2 }}><ChevronRight size={12} /></span> {name}
        </span>
      )}
      {dirty && <span title={t('file.unsaved')} style={{ width: 8, height: 8, borderRadius: '50%', background: '#d29922', flex: '0 0 auto' }} />}
      <span style={{ flex: 1, minWidth: 8 }} />
      {editable && (
        <Button size="small" type="primary" ghost={!dirty} disabled={!dirty || saving} loading={saving} onClick={save}>{t('file.save')}</Button>
      )}
      {(isMd || isHtml) && data && !data.binary && (
        <Button size="small" onClick={() => setSource((s) => !s)}>{source ? t('file.rendered') : t('file.source')}</Button>
      )}
      {/* 新标签同样走 serveUrl：/file/raw?path= 下，页面里的 shared.css 会被浏览器解析成
          /api/file/shared.css 而 404，整页裸奔（设计稿只剩黑三角）。见 HtmlView 的同款理由。 */}
      {isHtml && (
        <Button size="small" href={serveUrl} target="_blank" rel="noreferrer">{t('file.openInNewTab')}</Button>
      )}
      {onOpenAgent && (
        <Button size="small" onClick={() => setAgentPick(true)}>{t('file.openInAgent')}</Button>
      )}
      <Button size="small" onClick={copyPath}>{t('file.copyPath')}</Button>
      <Button size="small" href={downloadUrl} download={downloadName}>{t('file.download')}</Button>
      <a href={rawUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--text-dim)', fontSize: 12 }}>{t('file.raw')}</a>
      {inline && !tabbed && !onBack && <IconButton title={t('file.closePreview')} onClick={onClose}><CloseIcon /></IconButton>}
    </div>
  )
  const bodyNode = (
    <>
      {isImg ? (
        <ImageView rawUrl={rawUrl} name={name} height={previewHeight} />
      ) : isMedia ? (
        <MediaView path={path} rawUrl={rawUrl} name={name} audio={isAudio} inline={inline} />
      ) : isPdf ? (
        <PdfView path={path} rawUrl={rawUrl} name={name} inline={inline} truncated={data?.truncated} />
      ) : isOffice ? (
        <OfficeView kind={kind} path={path} name={name} rawUrl={rawUrl} previewUrl={previewUrl} downloadUrl={downloadUrl} downloadName={downloadName} inline={inline} truncated={data?.truncated} />
      ) : (
        <>
          {err && <div style={{ color: '#f85149' }}>{err}</div>}
          {!data && !err && <div style={{ textAlign: 'center', padding: 30 }}><Spin /></div>}
          {data && data.binary && (
            <div style={{ color: 'var(--text-dim)' }}>{t('file.binaryCannotPreview', { size: fmtSize(data.size) })}<a href={rawUrl} target="_blank" rel="noreferrer" style={{ color: accent }}>{t('file.downloadOrOpenRaw')}</a></div>
          )}
          {data && !data.binary && (
            <>
              {isSheet
                ? <CsvView path={path} text={data.content} sep={extOf(path) === 'tsv' ? '\t' : ','} height={previewHeight} inline={inline} truncated={data.truncated} />
                : isMd && (!source || forcePreview)
                  ? <MarkdownView path={path} content={data.content} accent={accent} height={previewHeight} pad={forcePreview ? '0 8px' : undefined} resolveHref={resolvePreviewHref} onLinkClick={openPreviewLink} />
                  : isHtml && (!source || forcePreview)
                    ? <HtmlView path={path} rawUrl={serveUrl} name={name} mtime={data.mtime} height={previewHeight} />
                    : <CodeView stateKey={path} value={draft} language={monacoLangOf(path)} dark={mode === 'dark'} readOnly={!editable} tabbed={tabbed} height={previewHeight} onChange={setDraft} onSave={() => saveRef.current()} />}
              {data.truncated && <div style={{ color: '#d29922', fontSize: 12, marginTop: 6, display: 'flex', alignItems: 'center', gap: 5 }}><WarnIcon size={12} />{t('file.truncatedLong')}</div>}
            </>
          )}
        </>
      )}
      {onOpenAgent && (
        <Modal open={agentPick} title={t('file.openInAgent')} footer={null} onCancel={() => setAgentPick(false)}>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <div style={{ color: 'var(--text-dim)', fontFamily: 'ui-monospace, monospace', wordBreak: 'break-all' }}>{path}</div>
            <Space>
              <Button type="primary" onClick={() => { setAgentPick(false); onOpenAgent('claude', path) }}>Claude Code</Button>
              <Button onClick={() => { setAgentPick(false); onOpenAgent('codex', path) }}>Codex</Button>
            </Space>
          </Space>
        </Modal>
      )}
    </>
  )

  if (inline) {
    // flex:1 + minWidth:0 缺一不可：这块内容常挂在行向 flex 父级里（抽屉的预览层就是），
    // 不给 flex 它按内容宽收缩——代码文件表现为「编辑器只占左边一条，右边空一大片」，
    // Monaco 按容器宽排版，容器多窄它就画多窄，长行还被截掉。
    return (
      <div style={{ flex: 1, minWidth: 0, height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg-base)' }}>
        {/* 编辑器 tab 语境(tabbed)：文件名/操作已由外层 tab 承担 → 去掉整条标题栏，编辑器全屏。保存用 Ctrl/Cmd+S。 */}
        {!tabbed && <div style={{ padding: '9px 12px', borderBottom: '1px solid var(--border-subtle)' }}>{titleNode}</div>}
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', padding: tabbed ? 0 : 12, position: 'relative' }}>
          <ErrorBoundary>{bodyNode}</ErrorBoundary>
          {/* tab 语境无头部：markdown/HTML 右上角 VSCode 式按钮（切换预览 / 侧栏打开预览 / 新标签打开） */}
          {tabbed && (isMd || isHtml) && !forcePreview && data && !data.binary && (
            <div style={{ position: 'absolute', top: 6, right: 8, zIndex: 10, display: 'inline-flex', gap: 2, background: 'color-mix(in srgb, var(--bg-base) 82%, transparent)', borderRadius: 8, padding: 2 }}>
              <Tooltip title={source ? t('file.preview') : t('file.source')} placement="bottom">
                <Button type="text" size="small" onClick={() => setSource((s) => !s)} style={{ color: !source ? accent : 'var(--text-dim)', width: 28, height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><PreviewIcon /></Button>
              </Tooltip>
              {onPreviewToSide && (
                <Tooltip title={t('file.previewToSide')} placement="bottom">
                  <Button type="text" size="small" onClick={() => onPreviewToSide(path)} style={{ color: 'var(--text-dim)', width: 28, height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><PreviewSideIcon /></Button>
                </Tooltip>
              )}
              {isHtml && (
                <Tooltip title={t('file.openInNewTab')} placement="bottom">
                  <Button type="text" size="small" href={serveUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--text-dim)', width: 28, height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><ExternalLinkIcon /></Button>
                </Tooltip>
              )}
            </div>
          )}
          {/* 文件被外部(cc/codex)改动、但本地有未保存改动 → 提示条 */}
          {stale && dirty && (
            <div style={{ position: 'absolute', top: 6, left: '50%', transform: 'translateX(-50%)', zIndex: 11, display: 'inline-flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 8, fontSize: 12, background: 'var(--bg-container)', border: '1px solid #d29922', color: 'var(--text-bright)', boxShadow: 'var(--elevated-shadow)' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><WarnIcon size={12} />{t('file.changedOnDisk')}</span>
              <Button size="small" danger onClick={reloadFromDisk}>{t('file.reloadFromDisk')}</Button>
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    // 弹窗预览：代码/表格/PDF 在窄弹窗里很难看 → 尽量吃满视口宽度（大屏封顶 1440），并上移留出更高正文。
    <Modal open onCancel={onClose} footer={null} width="min(1440px, 94vw)" style={{ top: 40 }} title={titleNode}>
      <ErrorBoundary>{bodyNode}</ErrorBoundary>
    </Modal>
  )
}

// 兼容旧引用名（历史上叫 Viewer）。新代码请用 FileView。
export { FileView as Viewer }
