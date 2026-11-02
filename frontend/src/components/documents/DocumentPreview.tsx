import { Suspense } from 'react'
import { Spin } from 'antd'
import { useI18n } from '../../i18n'
import { lazyRetry } from '../lazy-retry'
import './document-preview.css'

const PdfDocument = lazyRetry(() => import('./PdfDocument'))
const PptxDocument = lazyRetry(() => import('../files/OfficePreviewers').then(module => ({ default: module.PptxFilePreview })))

export const isPdfDocument = (name: string, mime: string) => mime === 'application/pdf' || name.toLowerCase().endsWith('.pdf')
export const isPptxDocument = (name: string, mime: string) => mime === 'application/vnd.openxmlformats-officedocument.presentationml.presentation' || name.toLowerCase().endsWith('.pptx')

export default function DocumentPreview({ src, name, mimeType }: { src: string; name: string; mimeType: string }) {
  const { t } = useI18n()
  return <div className="document-preview"><Suspense fallback={<Spin />}>
    {isPdfDocument(name, mimeType) ? <PdfDocument src={src} name={name} /> : isPptxDocument(name, mimeType)
      ? <PptxDocument src={src} name={name} downloadUrl={src} />
      : <p role="status">{t('document.previewUnavailable')}</p>}
  </Suspense></div>
}
