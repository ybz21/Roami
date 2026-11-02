// Office 文档展示：docx / xlsx / pptx 各有专用前端渲染器（很重，懒加载）；其余 Office
// 类型（doc/xls/ppt/odt…）走后端 soffice 转 PDF 再内嵌。
import {Suspense, useEffect, useState } from 'react'
import { Button, Spin } from 'antd'
import { PreviewShell } from './PreviewShell'
import { useI18n } from '../../../i18n'
import { type FileKind } from '../file-utils'
import { lazyRetry } from '../../lazy-retry'

const OfficePreviewers = () => import('../OfficePreviewers')
const DocxFilePreview = lazyRetry(() => OfficePreviewers().then((m) => ({ default: m.DocxFilePreview })))
const ExcelFilePreview = lazyRetry(() => OfficePreviewers().then((m) => ({ default: m.ExcelFilePreview })))
const PptxFilePreview = lazyRetry(() => OfficePreviewers().then((m) => ({ default: m.PptxFilePreview })))
const PdfDocument = lazyRetry(() => import('../../documents/PdfDocument'))

// 后端 soffice 转 PDF 后内嵌（doc/xls/ppt/odt 等无专用前端渲染器的类型）。
function OfficePdfPreview({ name, previewUrl, rawUrl, downloadUrl, downloadName, height }: { name: string; previewUrl: string; rawUrl: string; downloadUrl: string; downloadName: string; height: string }) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => {
    let stop = false
    let objectUrl = ''
    setUrl('')
    setErr('')
    fetch(previewUrl).then(async (r) => {
      if (!r.ok) {
        const data = await r.json().catch(() => null)
        throw new Error(data?.error?.message || data?.error?.code || `HTTP ${r.status}`)
      }
      return r.blob()
    }).then((blob) => {
      if (stop) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    }).catch((e) => {
      if (!stop) setErr(e.message || 'Office 预览生成失败')
    })
    return () => {
      stop = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [previewUrl])

  if (err) {
    return (
      <div style={{ minHeight: height, padding: 18, color: 'var(--text-dim)', lineHeight: 1.7 }}>
        <div style={{ color: 'var(--text-bright)', fontWeight: 700, marginBottom: 6 }}>{name}</div>
        <div>{err}</div>
        <div style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button size="small" type="primary" href={downloadUrl} download={downloadName}>{t('file.downloadFile')}</Button>
          <Button size="small" href={rawUrl} target="_blank">{t('file.openRaw')}</Button>
        </div>
      </div>
    )
  }
  if (!url) return <div style={{ height, display: 'grid', placeItems: 'center' }}><Spin /></div>
  return <Suspense fallback={<Spin />}><PdfDocument src={url} name={name} /></Suspense>
}

export function OfficeView({ kind, path, name, rawUrl, previewUrl, downloadUrl, downloadName, inline, truncated }: {
  kind: FileKind
  path: string
  name: string
  rawUrl: string
  previewUrl: string
  downloadUrl: string
  downloadName: string
  inline?: boolean
  truncated?: boolean
}) {
  const { t } = useI18n()
  if (kind.isDocx) {
    return (
      <PreviewShell path={path} title={t('file.wordPreview')} inline={inline} truncated={truncated}>
        <Suspense fallback={<Spin />}><DocxFilePreview src={rawUrl} name={name} downloadUrl={downloadUrl} /></Suspense>
      </PreviewShell>
    )
  }
  if (kind.isExcel) {
    return (
      <PreviewShell path={path} title={t('file.excelPreview')} inline={inline} truncated={truncated}>
        <Suspense fallback={<Spin />}><ExcelFilePreview src={rawUrl} name={name} downloadUrl={downloadUrl} /></Suspense>
      </PreviewShell>
    )
  }
  if (kind.isPptx) {
    return (
      <PreviewShell path={path} title={t('file.pptPreview')} inline={inline} truncated={truncated}>
        <Suspense fallback={<Spin />}><PptxFilePreview src={rawUrl} name={name} downloadUrl={downloadUrl} /></Suspense>
      </PreviewShell>
    )
  }
  return (
    <PreviewShell path={path} title={t('file.officePreview')} inline={inline} truncated={truncated}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, minHeight: 0 }}>
          <OfficePdfPreview name={name} previewUrl={previewUrl} rawUrl={rawUrl} downloadUrl={downloadUrl} downloadName={downloadName} height="100%" />
        </div>
        <div style={{ padding: '8px 10px', borderTop: '1px solid var(--border-subtle)', color: 'var(--text-dim)', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span>{t('file.officePreviewHelp')}</span>
          <Button size="small" type="primary" href={downloadUrl} download={downloadName}>{t('file.downloadFile')}</Button>
          <Button size="small" href={rawUrl} target="_blank">{t('file.openRaw')}</Button>
        </div>
      </div>
    </PreviewShell>
  )
}
