import { Suspense } from 'react'
import { PreviewShell } from './PreviewShell'
import { useI18n } from '../../../i18n'
import { lazyRetry } from '../../lazy-retry'

const PdfDocument = lazyRetry(() => import('../../documents/PdfDocument'))

export function PdfView({ path, rawUrl, name, inline, truncated }: {
  path: string
  rawUrl: string
  name: string
  inline?: boolean
  truncated?: boolean
}) {
  const { t } = useI18n()
  return (
    <PreviewShell path={path} title={t('file.pdfPreview')} inline={inline} truncated={truncated}>
      <Suspense fallback={<p role="status">{t('common.loading')}</p>}><PdfDocument src={rawUrl} name={name} /></Suspense>
    </PreviewShell>
  )
}
