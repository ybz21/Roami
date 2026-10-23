import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist/legacy/build/pdf.mjs'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import { ChevronLeft, ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import './document-preview.css'

GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfDocument({ src, name }: { src: string; name: string }) {
  const { t } = useI18n()
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1), [width, setWidth] = useState(0), [retry, setRetry] = useState(0)
  const [failed, setFailed] = useState(false), [rendering, setRendering] = useState(true)
  const container = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const element = container.current
    if (!element) return
    const observer = new ResizeObserver(() => setWidth(element.clientWidth))
    observer.observe(element)
    setWidth(element.clientWidth)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let stopped = false
    setDocument(null); setPage(1); setFailed(false); setRendering(true)
    const loading = getDocument({ url: src, withCredentials: true, useSystemFonts: true, useWasm: false,
      cMapUrl: `${import.meta.env.BASE_URL}pdfjs/cmaps/`, cMapPacked: true,
      standardFontDataUrl: `${import.meta.env.BASE_URL}pdfjs/standard_fonts/`,
    })
    void loading.promise.then(pdf => { if (!stopped) setDocument(pdf) }).catch(() => { if (!stopped) setFailed(true) })
    return () => { stopped = true; void loading.destroy() }
  }, [src, retry])
  useEffect(() => {
    if (!document || !width || !canvas.current) return
    let stopped = false
    let render: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined
    setRendering(true); setFailed(false)
    void document.getPage(page).then(pdfPage => {
      if (stopped || !canvas.current) return
      const base = pdfPage.getViewport({ scale: 1 })
      const viewport = pdfPage.getViewport({ scale: width / base.width })
      // Bound mobile canvas memory independently of display density.
      const density = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(8_000_000 / (viewport.width * viewport.height)))
      const element = canvas.current
      element.width = Math.max(1, Math.floor(viewport.width * density))
      element.height = Math.max(1, Math.floor(viewport.height * density))
      element.style.width = `${viewport.width}px`
      element.style.height = `${viewport.height}px`
      render = pdfPage.render({ canvas: element, viewport, transform: [density, 0, 0, density, 0, 0] })
      return render.promise
    }).then(() => { if (!stopped) setRendering(false) }).catch(() => { if (!stopped) { setFailed(true); setRendering(false) } })
    return () => { stopped = true; render?.cancel() }
  }, [document, page, width])
  return <div className="pdf-document">
    {document && document.numPages > 1 && <div className="pdf-document-pages">
      <button type="button" className="tt-act" aria-label={t('document.previousPage')} disabled={page === 1 || rendering} onClick={() => setPage(value => value - 1)}><ChevronLeft size={20} /></button>
      <span>{t('document.page', { page, total: document.numPages })}</span>
      <button type="button" className="tt-act" aria-label={t('document.nextPage')} disabled={page === document.numPages || rendering} onClick={() => setPage(value => value + 1)}><ChevronRight size={20} /></button>
    </div>}
    <div className="pdf-document-scroll" ref={container}>
      {failed ? <p role="alert">{t('document.loadFailed')} <button type="button" className="tt-act" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></p> : <>
        {rendering && <p role="status">{t('common.loading')}</p>}
        <canvas ref={canvas} role="img" aria-label={`${name} ${t('office.page', { page })}`} hidden={rendering} />
      </>}
    </div>
  </div>
}
